"""
API de paiement fictive — Project Resilience-Alpha.
Expose des métriques Prometheus sur /metrics pour la collecte et la détection ML.
Aucune donnée réelle : tout est simulé.
"""
import os
import time
import contextlib
import psycopg2
from psycopg2 import pool as pgpool
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
)
from starlette.responses import Response

app = FastAPI(title="PayDemo API")
DB_URL = os.environ.get("DATABASE_URL", "postgresql://payuser:paypass@db:5432/paydb")

# ---------- Métriques Prometheus (les KPI que le ML va surveiller) ----------
REQ_TOTAL = Counter(
    "http_requests_total", "Nombre total de requêtes",
    ["method", "endpoint", "status"]
)
REQ_LATENCY = Histogram(
    "http_request_duration_seconds", "Temps de réponse",
    ["endpoint"]
)
LOGIN_FAILED = Counter("login_failed_total", "Échecs de connexion", ["username"])
LOGIN_OK = Counter("login_success_total", "Connexions réussies")
TX_TOTAL = Counter("transactions_total", "Transactions", ["status"])
SQL_ERRORS = Counter("sql_errors_total", "Erreurs SQL (signal injection)")
INPROGRESS = Gauge("http_inprogress_requests", "Requêtes en cours")


# Pool de connexions : réutilise les connexions au lieu d'en ouvrir une par
# requête (ce qui saturait PostgreSQL et générait de fausses erreurs SQL).
POOL = pgpool.SimpleConnectionPool(1, 20, dsn=DB_URL)


@contextlib.contextmanager
def db_conn():
    """Emprunte une connexion au pool et la REND toujours, même en cas d'erreur."""
    conn = POOL.getconn()
    try:
        yield conn
    finally:
        try:
            conn.rollback()   # annule toute transaction en cours avant de rendre
        except psycopg2.Error:
            pass
        POOL.putconn(conn)


# ---------- Middleware : mesure CHAQUE requête ----------
@app.middleware("http")
async def measure(request: Request, call_next):
    INPROGRESS.inc()
    start = time.time()
    endpoint = request.url.path
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception:
        status = 500
        response = JSONResponse({"error": "internal"}, status_code=500)
    finally:
        INPROGRESS.dec()
    REQ_LATENCY.labels(endpoint=endpoint).observe(time.time() - start)
    REQ_TOTAL.labels(request.method, endpoint, str(status)).inc()
    return response


# ---------- Modèles ----------
class LoginIn(BaseModel):
    username: str
    password: str


class TxIn(BaseModel):
    from_acc: int
    to_acc: int
    amount: float


# ---------- Endpoints métier ----------
@app.get("/health")
def health():
    """Sonde de vie : utilisée pour vérifier que le service est rétabli."""
    try:
        with db_conn() as c:
            cur = c.cursor(); cur.execute("SELECT 1"); cur.close()
        return {"status": "up"}
    except Exception:
        raise HTTPException(503, "db down")


@app.post("/login")
def login(data: LoginIn):
    try:
        with db_conn() as c:
            cur = c.cursor()
            cur.execute("SELECT id FROM users WHERE username=%s AND password=%s",
                        (data.username, data.password))
            row = cur.fetchone(); cur.close()
    except psycopg2.Error:
        SQL_ERRORS.inc()
        raise HTTPException(500, "sql error")
    if row:
        LOGIN_OK.inc()
        return {"token": f"demo-token-{row[0]}"}
    LOGIN_FAILED.labels(username=data.username).inc()
    raise HTTPException(401, "bad credentials")


@app.post("/transaction")
def transaction(tx: TxIn):
    """Exécute une transaction fictive : débit + crédit + journal."""
    try:
        with db_conn() as c:
            cur = c.cursor()
            cur.execute("UPDATE accounts SET balance = balance - %s WHERE id=%s",
                        (tx.amount, tx.from_acc))
            cur.execute("UPDATE accounts SET balance = balance + %s WHERE id=%s",
                        (tx.amount, tx.to_acc))
            cur.execute(
                "INSERT INTO transactions (from_acc,to_acc,amount) VALUES (%s,%s,%s) RETURNING id",
                (tx.from_acc, tx.to_acc, tx.amount))
            tid = cur.fetchone()[0]
            c.commit(); cur.close()
        TX_TOTAL.labels("OK").inc()
        return {"transaction_id": tid, "status": "OK"}
    except psycopg2.Error:
        SQL_ERRORS.inc()
        TX_TOTAL.labels("ERROR").inc()
        raise HTTPException(500, "sql error")


@app.get("/accounts/{acc_id}")
def get_account(acc_id: int):
    try:
        with db_conn() as c:
            cur = c.cursor()
            cur.execute("SELECT owner, balance FROM accounts WHERE id=%s", (acc_id,))
            row = cur.fetchone(); cur.close()
    except psycopg2.Error:
        SQL_ERRORS.inc()
        raise HTTPException(500, "sql error")
    if not row:
        raise HTTPException(404, "not found")
    return {"owner": row[0], "balance": float(row[1])}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)