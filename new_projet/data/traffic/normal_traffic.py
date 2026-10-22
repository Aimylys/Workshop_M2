"""Générateur de trafic NORMAL sur la plateforme (référence saine pour la détection).

Simule des clients fictifs (alice, bob, charlie) qui se connectent, consultent leurs
comptes et leur historique, et font de petits virements entre eux. Une faible part de
fautes de frappe au mot de passe est volontairement incluse : un trafic « normal » réel
en contient, et le modèle ne doit pas les confondre avec une attaque par force brute.

Usage :
    python data/traffic/normal_traffic.py                       # 6 clients, via le WAF
    python data/traffic/normal_traffic.py --users 12 --url http://127.0.0.1:8088
Ctrl+C pour arrêter. Bibliothèque standard uniquement.
"""
import argparse
import collections
import json
import random
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_SECRET = Path(__file__).resolve().parents[2] / "deploy" / "secrets" / "demo_password"
CUSTOMERS = {"alice": 1, "bob": 2, "charlie": 3}     # utilisateur -> son compte (fictif)

stats = collections.Counter()
stats_lock = threading.Lock()


def record(key):
    with stats_lock:
        stats[key] += 1


class Client:
    def __init__(self, base, username, password, typo_rate):
        self.base, self.username, self.password = base, username, password
        self.typo_rate = typo_rate
        self.token, self.token_until = None, 0.0

    def call(self, method, path, body=None, headers=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "AlphaPay-Web/1.0 (trafic normal)")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            record("injoignable")
            return None, None
        record(status)
        try:
            return status, json.loads(raw) if raw else None
        except ValueError:
            return status, None

    def login(self):
        password = self.password
        if random.random() < self.typo_rate:          # faute de frappe occasionnelle
            password = password[:-1] + "x"
        self.token = None
        status, body = self.call("POST", "/api/auth/login", {"username": self.username, "password": password})
        if status == 200:
            self.token = body["access_token"]
            self.token_until = time.time() + body["expires_in"] - 30
        return status == 200

    def step(self):
        if not self.token or time.time() > self.token_until:
            if not self.login():
                return
        action = random.random()
        if action < 0.40:
            status, _ = self.call("GET", "/api/pay/accounts")
        elif action < 0.60:
            status, _ = self.call("GET", "/api/pay/transactions")
        elif action < 0.95:
            others = [acc for user, acc in CUSTOMERS.items() if user != self.username]
            status, _ = self.call(
                "POST", "/api/pay/transactions",
                {"source_account_id": CUSTOMERS[self.username],
                 "destination_account_id": random.choice(others),
                 "amount": f"{random.uniform(1, 30):.2f}"},
                headers={"Idempotency-Key": f"{self.username}-{time.time_ns()}"},
            )
        else:
            status = 200 if self.login() else None    # reconnexion (nouvelle session)
        if status == 401:
            self.token = None


def run_client(client, stop, think_min, think_max):
    stop.wait(random.uniform(0, think_max))           # départs étalés
    while not stop.is_set():
        try:
            client.step()
        except Exception as exc:  # noqa: BLE001 - le générateur ne doit jamais s'arrêter seul
            record(f"erreur:{type(exc).__name__}")
        stop.wait(random.uniform(think_min, think_max))


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--url", default="http://127.0.0.1:8088", help="point d'entrée (le WAF)")
    p.add_argument("--users", type=int, default=6, help="clients simultanés")
    p.add_argument("--think-min", type=float, default=0.5, help="pause min entre deux actions (s)")
    p.add_argument("--think-max", type=float, default=2.0, help="pause max entre deux actions (s)")
    p.add_argument("--typo-rate", type=float, default=0.03, help="part des connexions avec faute de frappe")
    p.add_argument("--password-file", default=str(DEFAULT_SECRET))
    args = p.parse_args()

    password = Path(args.password_file).read_text(encoding="utf-8").strip()
    names = list(CUSTOMERS)
    stop = threading.Event()
    threads = [
        threading.Thread(target=run_client, daemon=True, args=(
            Client(args.url.rstrip("/"), names[i % len(names)], password, args.typo_rate),
            stop, args.think_min, args.think_max))
        for i in range(args.users)
    ]
    for t in threads:
        t.start()
    print(f"Trafic normal : {args.users} clients sur {args.url}. Ctrl+C pour arrêter.")
    try:
        last = collections.Counter()
        while True:
            time.sleep(10)
            with stats_lock:
                now = collections.Counter(stats)
            delta = now - last
            last = now
            total = sum(delta.values())
            detail = ", ".join(f"{k}: {v}" for k, v in sorted(delta.items(), key=lambda kv: str(kv[0])))
            print(f"  {time.strftime('%H:%M:%S')}  {total / 10:.1f} req/s  ({detail})")
    except KeyboardInterrupt:
        stop.set()
        print("\nArrêt du trafic normal.")


if __name__ == "__main__":
    main()
