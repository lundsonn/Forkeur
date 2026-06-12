"""Shared pytest setup.

`auth.py` reads `JWT_SECRET` at import time (module-level `os.environ["JWT_SECRET"]`),
so any test that imports the app/auth/routers fails at collection unless the var
is present. Set deterministic test values BEFORE the app modules are imported so
the suite is hermetic and does not depend on a developer's shell environment.
"""
import os

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-for-production")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

import pytest


@pytest.fixture
def auth_headers():
    """Authorization header carrying a real, fully-valid admin JWT.

    Endpoints are now protected by `require_auth`, which runs the hardened
    `auth._decode` (validates aud/iss/exp/iat). Minting via `auth.create_token`
    keeps the test exercising the genuine token path instead of a hand-built
    payload that the hardened decoder would reject.
    """
    import auth

    return {"Authorization": f"Bearer {auth.create_token()}"}
