"""Métriques Prometheus communes et journal des requêtes HTTP.

Les métriques sont servies sur un port séparé (METRICS_PORT, 9000) qui n'est jamais
relayé par le proxy frontal : seul Prometheus, sur le réseau interne, peut les lire.
"""
import time

from fastapi import FastAPI, Request
from prometheus_client import Counter, Gauge, Histogram, start_http_server

from .config import env_int
from .logs import client_ip, log

REQUESTS = Counter("http_requests_total", "Requêtes HTTP traitées", ["method", "route", "status"])
LATENCY = Histogram(
    "http_request_duration_seconds", "Durée de traitement des requêtes HTTP", ["route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
INPROGRESS = Gauge("http_inprogress_requests", "Requêtes HTTP en cours de traitement")
DB_ERRORS = Counter("db_errors_total", "Erreurs d'accès à la base", ["kind"])
for _kind in ("pool_timeout", "unavailable", "query"):
    DB_ERRORS.labels(_kind)   # séries créées à 0 pour que rate() fonctionne dès le départ

QUIET_ROUTES = {"/health"}   # sondes : comptées, mais pas journalisées (bruit)


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def observe(request: Request, call_next):
        INPROGRESS.inc()
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            INPROGRESS.dec()
            elapsed = time.perf_counter() - start
            # Gabarit de route (/accounts/{account_id}) et non chemin brut : cardinalité bornée.
            route = getattr(request.scope.get("route"), "path", "unmatched")
            REQUESTS.labels(request.method, route, str(status)).inc()
            LATENCY.labels(route).observe(elapsed)
            if route not in QUIET_ROUTES:
                log("http_request", ip=client_ip(request), method=request.method, route=route,
                    path=request.url.path, status=status, duration_ms=round(elapsed * 1000, 1))


def start_metrics_server() -> None:
    start_http_server(env_int("METRICS_PORT", 9000))
