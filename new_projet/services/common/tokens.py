"""Jetons d'accès JWT (HS256) : délivrés par le service auth, vérifiés par l'API de paiement."""
import time
from functools import lru_cache

import jwt

from .config import env_int, secret

ISSUER = "resilience-auth"
AUDIENCE = "resilience-payment"
TTL_SECONDS = env_int("JWT_TTL_SECONDS", 900)


@lru_cache(maxsize=1)
def _key() -> str:
    key = secret("JWT_SECRET")
    if len(key) < 32:
        raise RuntimeError("JWT_SECRET trop court (32 caractères minimum)")
    return key


def issue_token(subject: str, now: int | None = None) -> tuple[str, int]:
    now = int(time.time()) if now is None else now
    claims = {"sub": subject, "iat": now, "exp": now + TTL_SECONDS, "iss": ISSUER, "aud": AUDIENCE}
    return jwt.encode(claims, _key(), algorithm="HS256"), TTL_SECONDS


def verify_token(token: str) -> str:
    """Renvoie l'utilisateur du jeton ; lève jwt.InvalidTokenError sinon."""
    claims = jwt.decode(
        token, _key(), algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER,
        options={"require": ["exp", "iat", "sub", "iss", "aud"]},
    )
    return claims["sub"]
