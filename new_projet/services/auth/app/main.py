"""Service d'authentification : vérifie les identifiants (fictifs) et délivre des JWT.

Protection contre la force brute : après LOCKOUT_THRESHOLD échecs consécutifs, le compte est
verrouillé LOCKOUT_MINUTES minutes (0 désactive). Chaque tentative est comptée dans
login_attempts_total{result} et journalisée avec l'IP source (exploitée par le SIEM).
"""
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from prometheus_client import Counter
from pydantic import BaseModel, Field

from common import db, observability
from common.config import env, env_int, secret
from common.logs import client_ip, log
from common.tokens import issue_token

from . import passwords

LOGINS = Counter("login_attempts_total", "Tentatives de connexion", ["result"])
for _result in ("success", "failure", "locked"):
    LOGINS.labels(_result)

LOCKOUT_THRESHOLD = env_int("LOCKOUT_THRESHOLD", 10)
LOCKOUT_MINUTES = env_int("LOCKOUT_MINUTES", 5)

# Comptes fictifs créés au démarrage. Les mots de passe viennent des secrets, jamais du code.
# « probe » est le compte technique utilisé par la remédiation pour sa transaction de test.
SEED_USERS = (
    ("alice", "DEMO_PASSWORD"),
    ("bob", "DEMO_PASSWORD"),
    ("charlie", "DEMO_PASSWORD"),
    ("probe", "PROBE_PASSWORD"),
)

pool = db.make_pool()


def seed_users(stop: threading.Event) -> None:
    """Crée les comptes de démonstration (idempotent). Réessaie tant que la base n'est pas prête."""
    while not stop.is_set():
        try:
            with pool.connection() as conn:
                for username, password_var in SEED_USERS:
                    conn.execute(
                        "INSERT INTO users (username, password_hash) VALUES (%s, %s) "
                        "ON CONFLICT (username) DO NOTHING",
                        (username, passwords.hash_password(secret(password_var))),
                    )
            log("seed_users", users=len(SEED_USERS))
            return
        except Exception as exc:  # noqa: BLE001 - base pas encore prête : on réessaie
            log("seed_users_retry", level="warning", error=type(exc).__name__)
            stop.wait(3)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open(wait=False)
    observability.start_metrics_server()
    stop = threading.Event()
    threading.Thread(target=seed_users, args=(stop,), daemon=True).start()
    yield
    stop.set()
    pool.close()


docs = env("DOCS_ENABLED", "1") == "1"
app = FastAPI(title="Resilience-Alpha — Auth", version="1.0.0", lifespan=lifespan,
              docs_url="/docs" if docs else None, openapi_url="/openapi.json" if docs else None)
observability.install(app)
db.install_error_handlers(app)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@app.get("/health")
def health():
    db.ping(pool)
    return {"status": "up", "db": "up"}


@app.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request):
    # 1. Lecture de l'état du compte (connexion rendue aussitôt au pool).
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT password_hash, locked_until > now() FROM users WHERE username = %s",
            (body.username,),
        ).fetchone()

    # 2. Vérification Argon2 hors connexion : elle coûte du CPU, pas une connexion du pool.
    if row is None:
        passwords.verify(passwords.DUMMY_HASH, body.password)
        result, reason = "failure", "unknown_user"
    elif row[1]:
        result, reason = "locked", "account_locked"
    elif passwords.verify(row[0], body.password):
        result, reason = "success", None
    else:
        result, reason = "failure", "bad_password"

    # 3. Mise à jour atomique des compteurs d'échec.
    if result == "success":
        with pool.connection() as conn:
            new_hash = passwords.hash_password(body.password) if passwords.needs_rehash(row[0]) else row[0]
            conn.execute(
                "UPDATE users SET failed_attempts = 0, locked_until = NULL, password_hash = %s "
                "WHERE username = %s",
                (new_hash, body.username),
            )
    elif reason == "bad_password":
        with pool.connection() as conn:
            locked = conn.execute(
                "UPDATE users SET failed_attempts = failed_attempts + 1, "
                "locked_until = CASE WHEN %(threshold)s > 0 AND failed_attempts + 1 >= %(threshold)s "
                "THEN now() + make_interval(mins => %(minutes)s) ELSE locked_until END "
                "WHERE username = %(username)s RETURNING locked_until IS NOT NULL AND locked_until > now()",
                {"threshold": LOCKOUT_THRESHOLD, "minutes": LOCKOUT_MINUTES, "username": body.username},
            ).fetchone()[0]
        if locked:
            reason = "locked_now"

    LOGINS.labels(result).inc()
    log("login", level="info" if result == "success" else "warning",
        user=body.username, ip=client_ip(request), result=result, reason=reason)

    if result == "locked":
        raise HTTPException(status_code=423, detail="compte temporairement verrouillé")
    if result == "failure":
        raise HTTPException(status_code=401, detail="identifiants invalides",
                            headers={"WWW-Authenticate": "Bearer"})
    token, ttl = issue_token(body.username)
    return TokenOut(access_token=token, expires_in=ttl)
