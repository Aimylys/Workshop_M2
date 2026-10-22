"""Accès aux KPI de la plateforme, partagé par le collecteur et la détection.

La liste des KPI n'est écrite nulle part ici : elle est lue dans les règles d'enregistrement
Prometheus (observability/prometheus/rules/kpi.yml), la définition unique.
"""
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KPI_RULES = ROOT / "observability" / "prometheus" / "rules" / "kpi.yml"

# États reconnus. « normal » est la référence ; les autres correspondent aux scénarios du runbook.
LABELS = ("normal", "ddos", "brute_force", "sql_injection", "service_down", "port_scan")


# Les KPI sont des débits sur 30 s (6 échantillons). Juste après un (re)démarrage de
# Prometheus, la fenêtre est incomplète et les débits valent 0 alors que le trafic continue :
# ces valeurs ne doivent pas entrer dans le jeu de données. L'auto-surveillance de Prometheus
# (job « prometheus ») indique combien d'échantillons la fenêtre contient réellement.
WARMUP_EXPR = 'count_over_time(up{job="prometheus"}[30s])'
MIN_SAMPLES = 5
# Instant du dernier calcul des règles KPI (évite d'enregistrer deux fois le même calcul).
EVALUATED_AT_EXPR = "timestamp(kpi:api_up)"


class PrometheusError(RuntimeError):
    """Prometheus injoignable ou réponse invalide."""


class NotReady(PrometheusError):
    """Prometheus répond mais n'a pas encore assez d'historique pour des KPI fiables."""


def kpi_names(rules_file: Path = KPI_RULES) -> list[str]:
    """Noms des KPI (« kpi:req_per_sec »...), dans l'ordre du fichier de règles."""
    text = rules_file.read_text(encoding="utf-8")
    names = re.findall(r"^\s*-\s*record:\s*(kpi:[a-z0-9_]+)\s*$", text, flags=re.MULTILINE)
    if not names:
        raise ValueError(f"aucun KPI trouvé dans {rules_file}")
    return names


def column(name: str) -> str:
    """kpi:req_per_sec -> req_per_sec (nom de colonne du jeu de données)."""
    return name.removeprefix("kpi:")


def _number(raw) -> float | None:
    """Valeur Prometheus -> float ; NaN/Inf (ex. latence sans aucune requête) -> None."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


class Prometheus:
    def __init__(self, url: str, timeout: float = 4.0):
        self.url = url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: dict) -> dict:
        query = urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(f"{self.url}{path}?{query}", timeout=self.timeout) as r:
                body = json.load(r)
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as exc:
            raise PrometheusError(f"Prometheus injoignable ({self.url}) : {exc}") from exc
        if body.get("status") != "success":
            raise PrometheusError(f"requête refusée par Prometheus : {body.get('error', body)}")
        return body["data"]

    def scalar(self, expr: str, at: float | None = None) -> float | None:
        params = {"query": expr}
        if at is not None:
            params["time"] = f"{at:.3f}"
        result = self._get("/api/v1/query", params)["result"]
        return _number(result[0]["value"][1]) if result else None

    def check_ready(self) -> None:
        samples = self.scalar(WARMUP_EXPR)
        if samples is None or samples < MIN_SAMPLES:
            raise NotReady(f"Prometheus démarre ({int(samples or 0)}/6 échantillons sur 30 s)")

    def evaluated_at(self) -> float | None:
        return self.scalar(EVALUATED_AT_EXPR)

    def snapshot(self, names: list[str], at: float | None = None) -> dict[str, float | None]:
        """Valeur instantanée de chaque KPI. Un KPI absent vaut None (jamais 0 inventé)."""
        params = {"query": '{__name__=~"kpi:.+"}'}
        if at is not None:
            params["time"] = f"{at:.3f}"
        data = self._get("/api/v1/query", params)
        found = {s["metric"]["__name__"]: _number(s["value"][1]) for s in data["result"]}
        return {n: found.get(n) for n in names}

    def history(self, names: list[str], start: float, end: float, step: int) -> dict[int, dict]:
        """Valeurs des KPI sur une période : {horodatage: {kpi: valeur}}.
        Les instants où Prometheus n'avait pas une fenêtre complète sont écartés."""
        window = {"start": f"{start:.0f}", "end": f"{end:.0f}", "step": str(step)}
        data = self._get("/api/v1/query_range", {"query": '{__name__=~"kpi:.+"}', **window})
        warm = self._get("/api/v1/query_range", {"query": WARMUP_EXPR, **window})["result"]
        ready = {int(float(ts)) for ts, raw in (warm[0]["values"] if warm else [])
                 if (_number(raw) or 0) >= MIN_SAMPLES}
        rows: dict[int, dict] = {}
        for serie in data["result"]:
            name = serie["metric"]["__name__"]
            if name not in names:
                continue
            for ts, raw in serie["values"]:
                rows.setdefault(int(float(ts)), {})[name] = _number(raw)
        return {ts: {n: values.get(n) for n in names} for ts, values in sorted(rows.items()) if ts in ready}
