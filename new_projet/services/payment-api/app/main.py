"""API de paiement (données 100 % fictives) : consultation des comptes et virements.

Chaque virement est atomique : les deux comptes sont verrouillés dans un ordre stable
(pas d'interblocage), le solde est vérifié, puis débit, crédit et écriture du journal
sont validés ensemble ou pas du tout. Un en-tête Idempotency-Key évite qu'un virement
rejoué (double clic, nouvelle tentative réseau) soit exécuté deux fois.
"""
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal

import jwt
import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import Counter
from pydantic import BaseModel, ConfigDict, Field, model_validator

from common import db, observability
from common.config import env
from common.logs import client_ip, log
from common.tokens import verify_token

MAX_AMOUNT = Decimal("10000.00")

TRANSACTIONS = Counter("transactions_total", "Virements traités", ["status", "reason"])
for _status, _reason in (("success", "ok"), ("failed", "insufficient_funds"), ("failed", "forbidden"),
                         ("failed", "unknown_account"), ("failed", "error")):
    TRANSACTIONS.labels(_status, _reason)

pool = db.make_pool()


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open(wait=False)
    observability.start_metrics_server()
    yield
    pool.close()


docs = env("DOCS_ENABLED", "1") == "1"
app = FastAPI(title="Resilience-Alpha — Paiement", version="1.0.0", lifespan=lifespan,
              docs_url="/docs" if docs else None, openapi_url="/openapi.json" if docs else None)
observability.install(app)
db.install_error_handlers(app)

bearer = HTTPBearer(auto_error=False)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    if credentials is None:
        raise HTTPException(status_code=401, detail="authentification requise",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        return verify_token(credentials.credentials)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="jeton invalide ou expiré",
                            headers={"WWW-Authenticate": "Bearer"}) from None


# ---------- Modèles ----------
class AccountOut(BaseModel):
    id: int
    label: str
    balance: Decimal


class TransferIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_account_id: int = Field(gt=0)
    destination_account_id: int = Field(gt=0)
    amount: Decimal = Field(gt=0, le=MAX_AMOUNT, max_digits=12, decimal_places=2)

    @model_validator(mode="after")
    def distinct_accounts(self):
        if self.source_account_id == self.destination_account_id:
            raise ValueError("les comptes source et destination doivent être différents")
        return self


class TransactionOut(BaseModel):
    id: int
    source_account_id: int
    destination_account_id: int
    amount: Decimal
    created_at: datetime


class Rejected(Exception):
    """Refus métier : rien n'est écrit, la transaction SQL est annulée."""

    def __init__(self, status: int, reason: str, detail: str):
        self.status, self.reason, self.detail = status, reason, detail


TX_COLUMNS = "id, source_account_id, destination_account_id, amount, created_at"


def _tx(row) -> TransactionOut:
    return TransactionOut(id=row[0], source_account_id=row[1], destination_account_id=row[2],
                          amount=row[3], created_at=row[4])


def _transfer(user: str, body: TransferIn, key: str | None) -> tuple[TransactionOut, bool]:
    """Exécute le virement. Renvoie (transaction, rejouée?)."""
    src, dst = body.source_account_id, body.destination_account_id
    with pool.connection() as conn:
        if key:
            row = conn.execute(f"SELECT {TX_COLUMNS} FROM transactions "
                               "WHERE initiated_by = %s AND idempotency_key = %s", (user, key)).fetchone()
            if row:
                return _tx(row), True

        accounts = {
            r[0]: r for r in conn.execute(
                "SELECT id, owner, balance FROM accounts WHERE id = ANY(%s) ORDER BY id FOR UPDATE",
                ([src, dst],),
            )
        }
        if src not in accounts or dst not in accounts:
            raise Rejected(404, "unknown_account", "compte introuvable")
        if accounts[src][1] != user:
            raise Rejected(403, "forbidden", "le compte source ne vous appartient pas")
        if accounts[src][2] < body.amount:
            raise Rejected(409, "insufficient_funds", "solde insuffisant")

        conn.execute("UPDATE accounts SET balance = balance - %s WHERE id = %s", (body.amount, src))
        conn.execute("UPDATE accounts SET balance = balance + %s WHERE id = %s", (body.amount, dst))
        row = conn.execute(
            f"INSERT INTO transactions (source_account_id, destination_account_id, amount, initiated_by, "
            f"idempotency_key) VALUES (%s, %s, %s, %s, %s) RETURNING {TX_COLUMNS}",
            (src, dst, body.amount, user, key),
        ).fetchone()
        return _tx(row), False


# ---------- Routes ----------
@app.get("/health")
def health():
    db.ping(pool)
    return {"status": "up", "db": "up"}


@app.get("/accounts", response_model=list[AccountOut])
def list_accounts(user: str = Depends(current_user)):
    with pool.connection() as conn:
        rows = conn.execute("SELECT id, label, balance FROM accounts WHERE owner = %s ORDER BY id",
                            (user,)).fetchall()
    return [AccountOut(id=r[0], label=r[1], balance=r[2]) for r in rows]


@app.get("/accounts/{account_id}", response_model=AccountOut)
def get_account(account_id: int, user: str = Depends(current_user)):
    with pool.connection() as conn:
        row = conn.execute("SELECT id, label, balance FROM accounts WHERE id = %s AND owner = %s",
                           (account_id, user)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="compte introuvable")
    return AccountOut(id=row[0], label=row[1], balance=row[2])


@app.get("/transactions", response_model=list[TransactionOut])
def list_transactions(user: str = Depends(current_user)):
    with pool.connection() as conn:
        rows = conn.execute(
            f"SELECT {TX_COLUMNS} FROM transactions WHERE source_account_id IN "
            "(SELECT id FROM accounts WHERE owner = %(u)s) OR destination_account_id IN "
            "(SELECT id FROM accounts WHERE owner = %(u)s) ORDER BY id DESC LIMIT 50",
            {"u": user},
        ).fetchall()
    return [_tx(r) for r in rows]


@app.post("/transactions", response_model=TransactionOut, status_code=201)
def create_transaction(body: TransferIn, request: Request, user: str = Depends(current_user),
                       idempotency_key: str | None = Header(default=None, max_length=64)):
    try:
        try:
            tx, replayed = _transfer(user, body, idempotency_key)
        except psycopg.errors.UniqueViolation:
            # Deux requêtes concurrentes avec la même clé : la seconde relit la première.
            tx, replayed = _transfer(user, body, idempotency_key)
    except Rejected as rej:
        TRANSACTIONS.labels("failed", rej.reason).inc()
        log("transaction_rejected", level="warning", user=user, ip=client_ip(request),
            reason=rej.reason, amount=body.amount)
        raise HTTPException(status_code=rej.status, detail=rej.detail) from None
    except Exception:
        TRANSACTIONS.labels("failed", "error").inc()
        raise
    if not replayed:
        TRANSACTIONS.labels("success", "ok").inc()
        log("transaction", user=user, ip=client_ip(request), tx_id=tx.id, amount=tx.amount,
            source=tx.source_account_id, destination=tx.destination_account_id)
    return tx
