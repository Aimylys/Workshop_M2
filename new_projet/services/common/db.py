"""Pool de connexions PostgreSQL.

`with pool.connection() as conn:` emprunte une connexion, valide la transaction si le bloc
se termine normalement, l'annule sinon, et REND TOUJOURS la connexion au pool : aucune fuite
possible, même sur exception. Le pool est borné (POOL_MAX) et l'attente d'une connexion
libre est limitée (POOL_TIMEOUT) : sous forte charge, l'API répond 503 au lieu de s'empiler.
"""
import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg.conninfo import make_conninfo
from psycopg_pool import ConnectionPool, PoolTimeout

from .config import env, env_int, secret
from .logs import SERVICE, log
from .observability import DB_ERRORS


def _conninfo() -> str:
    return make_conninfo(
        host=env("DB_HOST", "db"),
        port=env_int("DB_PORT", 5432),
        dbname=env("DB_NAME", "payments"),
        user=env("DB_USER", ""),
        password=secret("DB_PASSWORD"),
        connect_timeout=3,
        application_name=SERVICE,
    )


class LazyPool(ConnectionPool):
    """Lit les identifiants à l'ouverture et non à l'import (les tests unitaires
    importent les services sans secrets)."""

    def open(self, wait: bool = False, timeout: float = 30.0) -> None:
        self.conninfo = _conninfo()
        super().open(wait=wait, timeout=timeout)


def make_pool() -> ConnectionPool:
    """Crée le pool sans l'ouvrir : l'ouverture se fait au démarrage (lifespan),
    sans attendre la base (wait=False) pour que le service démarre même si elle est absente."""
    return LazyPool(
        "",
        min_size=env_int("POOL_MIN", 2),
        max_size=env_int("POOL_MAX", 10),
        timeout=env_int("POOL_TIMEOUT", 3),
        max_idle=300,
        check=ConnectionPool.check_connection,   # écarte les connexions mortes (ex. base redémarrée)
        name=SERVICE,
        open=False,
    )


def ping(pool: ConnectionPool) -> None:
    with pool.connection(timeout=2) as conn:
        conn.execute("SELECT 1")


def install_error_handlers(app: FastAPI) -> None:
    """Traduit les erreurs de base en réponses HTTP propres, comptées dans db_errors_total."""

    def handler(kind: str, status: int, detail: str):
        async def _handle(request: Request, exc: Exception):
            DB_ERRORS.labels(kind).inc()
            log("db_error", level="error", kind=kind, error=type(exc).__name__, path=request.url.path)
            return JSONResponse(status_code=status, content={"detail": detail})
        return _handle

    app.add_exception_handler(PoolTimeout, handler("pool_timeout", 503, "service temporairement saturé"))
    app.add_exception_handler(psycopg.OperationalError, handler("unavailable", 503, "base de données indisponible"))
    app.add_exception_handler(psycopg.Error, handler("query", 500, "erreur base de données"))
