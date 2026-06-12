import os
import pytest
import jwt
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET", "test-secret-for-auth-tests")

import auth


def test_create_token_returns_string():
    token = auth.create_token()
    assert isinstance(token, str)
    assert len(token) > 20


def test_verify_token_accepts_valid_token():
    token = auth.create_token()
    assert auth.verify_token(token) is True


def test_verify_token_rejects_wrong_secret():
    token = jwt.encode({"admin": True}, "wrong-secret", algorithm="HS256")
    assert auth.verify_token(token) is False


def test_verify_token_rejects_expired():
    from datetime import datetime, timedelta, timezone
    payload = {
        "admin": True,
        "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
    }
    token = jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")
    assert auth.verify_token(token) is False


def test_verify_token_rejects_garbage():
    assert auth.verify_token("not.a.token") is False


def test_verify_token_rejects_empty():
    assert auth.verify_token("") is False


def test_token_contains_admin_claim():
    token = auth.create_token()
    # Tokens now carry aud/iss claims that pyjwt validates on decode, so the
    # audience/issuer must be supplied or decode raises InvalidAudienceError.
    decoded = jwt.decode(
        token,
        os.environ["JWT_SECRET"],
        algorithms=["HS256"],
        audience="forkeur-admin",
        issuer="forkeur-backend",
    )
    assert decoded["admin"] is True


def test_create_token_is_deterministic_same_secret():
    # Two tokens must both verify — they may differ in exp precision
    t1 = auth.create_token()
    t2 = auth.create_token()
    assert auth.verify_token(t1)
    assert auth.verify_token(t2)
