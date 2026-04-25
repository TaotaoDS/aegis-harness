"""Tests for api/auth.py — JWT utilities and password hashing.

These tests run without a database and without SECRET_KEY by default.
Tests that need SECRET_KEY set it on the module being tested directly.
"""

import os
import pytest
from unittest.mock import patch
from uuid import UUID, uuid4

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SECRET = "test-secret-key-at-least-32-bytes-long!!"
SAMPLE_USER_ID   = uuid4()
SAMPLE_TENANT_ID = uuid4()


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    """Patch SECRET_KEY into api.auth for every test in this module."""
    monkeypatch.setenv("SECRET_KEY", SAMPLE_SECRET)
    # Also patch the module-level constant (already evaluated at import time)
    import api.auth as auth_module
    monkeypatch.setattr(auth_module, "SECRET_KEY", SAMPLE_SECRET)
    monkeypatch.setattr(auth_module, "DEV_MODE", False)


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        from api.auth import hash_password
        hashed = hash_password("mypassword")
        assert hashed != "mypassword"
        assert hashed.startswith("$2b$")

    def test_verify_correct_password(self):
        from api.auth import hash_password, verify_password
        hashed = hash_password("correct")
        assert verify_password("correct", hashed) is True

    def test_verify_wrong_password(self):
        from api.auth import hash_password, verify_password
        hashed = hash_password("correct")
        assert verify_password("wrong", hashed) is False

    def test_two_hashes_of_same_password_differ(self):
        """bcrypt uses a random salt — same input produces different hashes."""
        from api.auth import hash_password
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2


# ---------------------------------------------------------------------------
# Refresh-token hashing
# ---------------------------------------------------------------------------

class TestHashRefreshToken:
    def test_deterministic(self):
        from api.auth import hash_refresh_token
        assert hash_refresh_token("abc") == hash_refresh_token("abc")

    def test_length_is_64(self):
        from api.auth import hash_refresh_token
        assert len(hash_refresh_token("any-token")) == 64

    def test_different_inputs_differ(self):
        from api.auth import hash_refresh_token
        assert hash_refresh_token("token-a") != hash_refresh_token("token-b")


# ---------------------------------------------------------------------------
# create_access_token / decode_access_token
# ---------------------------------------------------------------------------

class TestAccessToken:
    def test_roundtrip(self):
        from api.auth import create_access_token, decode_access_token
        token = create_access_token(SAMPLE_USER_ID, SAMPLE_TENANT_ID, "admin", "a@b.com")
        payload = decode_access_token(token)
        assert payload.sub   == SAMPLE_USER_ID
        assert payload.tid   == SAMPLE_TENANT_ID
        assert payload.role  == "admin"
        assert payload.email == "a@b.com"

    def test_owner_role(self):
        from api.auth import create_access_token, decode_access_token
        token = create_access_token(SAMPLE_USER_ID, SAMPLE_TENANT_ID, "owner", "o@b.com")
        assert decode_access_token(token).role == "owner"

    def test_member_role(self):
        from api.auth import create_access_token, decode_access_token
        token = create_access_token(SAMPLE_USER_ID, SAMPLE_TENANT_ID, "member", "m@b.com")
        assert decode_access_token(token).role == "member"

    def test_tampered_token_raises_401(self):
        from api.auth import create_access_token, decode_access_token
        from fastapi import HTTPException
        token = create_access_token(SAMPLE_USER_ID, SAMPLE_TENANT_ID, "member", "m@b.com")
        bad_token = token[:-4] + "XXXX"
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(bad_token)
        assert exc_info.value.status_code == 401

    def test_garbage_string_raises_401(self):
        from api.auth import decode_access_token
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token("not.a.jwt")
        assert exc_info.value.status_code == 401

    def test_empty_string_raises_401(self):
        from api.auth import decode_access_token
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token("")
        assert exc_info.value.status_code == 401

    def test_wrong_token_type_raises_401(self):
        """A refresh token JWT must not be accepted as an access token."""
        from api.auth import create_refresh_token, decode_access_token
        from fastapi import HTTPException
        raw, _ = create_refresh_token(SAMPLE_USER_ID)
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(raw)
        assert exc_info.value.status_code == 401

    def test_expired_token_raises_401(self):
        from api.auth import decode_access_token
        from fastapi import HTTPException
        import api.auth as auth_module
        # Patch expiry to -1 minute so the token is already expired
        import importlib
        original = auth_module.ACCESS_TOKEN_EXPIRE_MINUTES
        auth_module.ACCESS_TOKEN_EXPIRE_MINUTES = -1
        try:
            token = auth_module.create_access_token(
                SAMPLE_USER_ID, SAMPLE_TENANT_ID, "member", "e@b.com"
            )
        finally:
            auth_module.ACCESS_TOKEN_EXPIRE_MINUTES = original
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(token)
        assert exc_info.value.status_code == 401

    def test_wrong_secret_raises_401(self):
        from api.auth import create_access_token
        from fastapi import HTTPException
        import api.auth as auth_module
        token = create_access_token(SAMPLE_USER_ID, SAMPLE_TENANT_ID, "member", "x@b.com")
        # Decode with wrong secret
        original_secret = auth_module.SECRET_KEY
        auth_module.SECRET_KEY = "totally-different-secret-key-here!!"
        try:
            with pytest.raises(HTTPException) as exc_info:
                auth_module.decode_access_token(token)
            assert exc_info.value.status_code == 401
        finally:
            auth_module.SECRET_KEY = original_secret


# ---------------------------------------------------------------------------
# create_refresh_token / decode_refresh_token_sub
# ---------------------------------------------------------------------------

class TestRefreshToken:
    def test_returns_raw_and_hash(self):
        from api.auth import create_refresh_token, hash_refresh_token
        raw, token_hash = create_refresh_token(SAMPLE_USER_ID)
        assert isinstance(raw, str)
        assert token_hash == hash_refresh_token(raw)

    def test_decode_sub(self):
        from api.auth import create_refresh_token, decode_refresh_token_sub
        raw, _ = create_refresh_token(SAMPLE_USER_ID)
        assert decode_refresh_token_sub(raw) == SAMPLE_USER_ID

    def test_wrong_type_raises_401(self):
        from api.auth import create_access_token, decode_refresh_token_sub
        from fastapi import HTTPException
        access_token = create_access_token(SAMPLE_USER_ID, SAMPLE_TENANT_ID, "member", "x@b.com")
        with pytest.raises(HTTPException) as exc_info:
            decode_refresh_token_sub(access_token)
        assert exc_info.value.status_code == 401

    def test_two_tokens_have_different_raw(self):
        from api.auth import create_refresh_token
        raw1, _ = create_refresh_token(SAMPLE_USER_ID)
        raw2, _ = create_refresh_token(SAMPLE_USER_ID)
        assert raw1 != raw2


# ---------------------------------------------------------------------------
# DEV_MODE behaviour (SECRET_KEY not set)
# ---------------------------------------------------------------------------

class TestDevMode:
    def test_create_access_token_raises_without_secret(self):
        import api.auth as auth_module
        original = auth_module.SECRET_KEY
        auth_module.SECRET_KEY = None
        try:
            with pytest.raises(RuntimeError, match="SECRET_KEY"):
                auth_module.create_access_token(
                    SAMPLE_USER_ID, SAMPLE_TENANT_ID, "owner", "d@b.com"
                )
        finally:
            auth_module.SECRET_KEY = original

    def test_decode_raises_without_secret(self):
        import api.auth as auth_module
        from fastapi import HTTPException
        original = auth_module.SECRET_KEY
        auth_module.SECRET_KEY = None
        try:
            with pytest.raises(HTTPException) as exc_info:
                auth_module.decode_access_token("any-token")
            assert exc_info.value.status_code == 401
        finally:
            auth_module.SECRET_KEY = original
