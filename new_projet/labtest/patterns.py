"""Profils de charge du laboratoire — produisent les signatures KPI de chaque état.

IMPORTANT (matériel contraint) : sur une VM Docker Desktop à 2 cœurs, le proxy de ports localhost
sature sur le NOMBRE de connexions simultanées — quelques dizaines de connexions neuves suffisent
à rendre toute la plateforme (Prometheus compris) injoignable. Ces profils utilisent donc PEU de
connexions PERSISTANTES (keep-alive) et un débit de requêtes BORNÉ : la signature reste nette
(débit, échecs, requêtes bloquées, 404…) sans effondrer l'observabilité.

Correspondance profil -> signature attendue :
  ddos          : req_per_sec ↑↑ (200 sur /health), inprogress ↑, latence paiement ↑, tx_ok ↓
  brute_force   : login_fail_per_sec ↑↑, latence login ↑
  sql_injection : waf_blocked_per_sec ↑↑ (403, arrêtées au WAF)
  port_scan     : waf_404_per_sec ↑↑ (chemins d'API inexistants)

Toute cible passe par guard.ensure_local (127.0.0.1 / 192.168.137.0/24 uniquement).
"""
import http.client
import random
import string
import threading
import time
from collections import Counter
from urllib.parse import urlparse

from .guard import ensure_local_url


class KeepAliveClient:
    """Une connexion HTTP réutilisée (keep-alive), reconnectée en cas d'erreur."""

    def __init__(self, host: str, port: int):
        self.host, self.port, self.conn = host, port, None

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None) -> int:
        h = {"Connection": "keep-alive"}
        if headers:
            h.update(headers)
        if body is not None:
            h.setdefault("Content-Type", "application/json")
        for _ in range(2):                       # une reconnexion si la connexion est tombée
            try:
                if self.conn is None:
                    self.conn = http.client.HTTPConnection(self.host, self.port, timeout=5)
                self.conn.request(method, path, body=body, headers=h)
                resp = self.conn.getresponse()
                status = resp.status
                resp.read()
                return status
            except Exception:  # noqa: BLE001
                self.close()
        return 0

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001
                pass
            self.conn = None


def _run(base: str, duration: float, workers: int, rate_per_worker: float, make_request) -> Counter:
    """`workers` connexions persistantes, chacune limitée à `rate_per_worker` requêtes/s."""
    base = ensure_local_url(base)
    parts = urlparse(base)
    host, port = parts.hostname, parts.port or 80
    stop = threading.Event()
    threading.Timer(duration, stop.set).start()
    results, lock = Counter(), threading.Lock()
    delay = 1.0 / rate_per_worker if rate_per_worker else 0.0

    def worker():
        client = KeepAliveClient(host, port)
        local = Counter()
        while not stop.is_set():
            t = time.time()
            local[make_request(client)] += 1
            wait = delay - (time.time() - t)
            if wait > 0:
                stop.wait(wait)
        client.close()
        with lock:
            results.update(local)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


# ------------------------------------------------------------------ DDoS (débit)
def ddos(base: str, duration: float, workers: int = 2, rate: float = 30.0) -> dict:
    """Débit soutenu de requêtes sur un point public (keep-alive). ~60 req/s, ~12× le normal."""
    codes = _run(base, duration, workers, rate,
                 lambda c: c.request("GET", "/api/pay/health"))
    return {"pattern": "ddos", "requests": sum(codes.values()), "codes": dict(codes)}


# ---------------------------------------------------------- Force brute (connexion)
def brute_force(base: str, duration: float, workers: int = 2, rate: float = 8.0,
                username: str = "admin") -> dict:
    """Connexions répétées avec de mauvais mots de passe. Cible « admin » (compte inexistant) :
    échecs de connexion sans verrouiller un vrai compte. Débit modéré (hachage Argon2 côté auth)."""
    def attempt(c: KeepAliveClient) -> int:
        pw = "".join(random.choices(string.ascii_letters, k=12))
        body = f'{{"username": "{username}", "password": "{pw}"}}'.encode()
        return c.request("POST", "/api/auth/login", body=body)

    codes = _run(base, duration, workers, rate, attempt)
    return {"pattern": "brute_force", "attempts": sum(codes.values()), "codes": dict(codes)}


# ----------------------------------------------- Injection SQL (arrêtée au WAF, 403)
_SQLI_PROBES = ("1' OR '1'='1", "1; DROP TABLE x--", "' UNION SELECT NULL--",
                "1' AND SLEEP(2)--", "admin'--", "' OR 1=1--")


def sql_injection(base: str, duration: float, workers: int = 2, rate: float = 25.0) -> dict:
    """Charges SQLi : arrêtées par le WAF (403). But : produire la signature « bloquées au WAF »,
    pas exfiltrer (les requêtes paramétrées de l'API neutralisent de toute façon l'injection)."""
    def attempt(c: KeepAliveClient) -> int:
        probe = "".join(ch if ch.isalnum() else "%%%02X" % ord(ch) for ch in random.choice(_SQLI_PROBES))
        return c.request("GET", f"/api/pay/accounts?id={probe}")

    codes = _run(base, duration, workers, rate, attempt)
    return {"pattern": "sql_injection", "requests": sum(codes.values()), "codes": dict(codes)}


# ------------------------------------------------- Reconnaissance (énumération, 404)
def port_scan(base: str, duration: float, workers: int = 2, rate: float = 25.0) -> dict:
    """Énumération de chemins d'API inexistants (-> 404 renvoyés par les services). Signature de
    reconnaissance via waf_404_per_sec, sans ouvrir des milliers de connexions."""
    prefixes = ("/api/pay/", "/api/auth/")

    def probe(c: KeepAliveClient) -> int:
        path = random.choice(prefixes) + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        return c.request("GET", path)

    codes = _run(base, duration, workers, rate, probe)
    return {"pattern": "port_scan", "requests": sum(codes.values()), "codes": dict(codes)}


PATTERNS = {
    "ddos": ddos,
    "brute_force": brute_force,
    "sql_injection": sql_injection,
    "port_scan": port_scan,
}
