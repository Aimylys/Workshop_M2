import time

import jwt
import pytest

from common import tokens


def test_round_trip():
    token, ttl = tokens.issue_token("alice")
    assert ttl == tokens.TTL_SECONDS
    assert tokens.verify_token(token) == "alice"


def test_expired_token_rejected():
    token, _ = tokens.issue_token("alice", now=int(time.time()) - tokens.TTL_SECONDS - 10)
    with pytest.raises(jwt.ExpiredSignatureError):
        tokens.verify_token(token)


def test_wrong_audience_rejected():
    forged = jwt.encode({"sub": "alice", "iat": int(time.time()), "exp": int(time.time()) + 60,
                         "iss": tokens.ISSUER, "aud": "autre-service"}, tokens._key(), algorithm="HS256")
    with pytest.raises(jwt.InvalidAudienceError):
        tokens.verify_token(forged)


def test_wrong_key_rejected():
    forged = jwt.encode({"sub": "alice", "iat": int(time.time()), "exp": int(time.time()) + 60,
                         "iss": tokens.ISSUER, "aud": tokens.AUDIENCE}, "x" * 40, algorithm="HS256")
    with pytest.raises(jwt.InvalidSignatureError):
        tokens.verify_token(forged)


def test_alg_none_rejected():
    forged = jwt.encode({"sub": "alice", "iat": int(time.time()), "exp": int(time.time()) + 60,
                         "iss": tokens.ISSUER, "aud": tokens.AUDIENCE}, None, algorithm="none")
    with pytest.raises(jwt.InvalidTokenError):
        tokens.verify_token(forged)
