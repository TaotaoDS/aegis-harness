"""Tests for api/deps.py — CurrentUser dependency injection.

Tests cover:
- Dev-mode bypass (no SECRET_KEY → synthetic owner returned)
- Token extraction from Authorization header and cookie
- Role-gating helpers: require_admin, require_owner
- CurrentUser helper properties: is_admin, is_owner
"""

import pytest
from uuid import UUID, uuid4

SAMPLE_USER_ID   = uuid4()
SAMPLE_TENANT_ID = uuid4()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(role: str = "member") -> "CurrentUser":
    from api.deps import CurrentUser
    return CurrentUser(
        user_id   = SAMPLE_USER_ID,
        tenant_id = SAMPLE_TENANT_ID,
        role      = role,
        email     = f"{role}@example.com",
    )


# ---------------------------------------------------------------------------
# CurrentUser properties
# ---------------------------------------------------------------------------

class TestCurrentUserProperties:
    def test_owner_is_admin(self):
        u = _make_user("owner")
        assert u.is_admin is True
        assert u.is_owner is True

    def test_admin_is_admin_not_owner(self):
        u = _make_user("admin")
        assert u.is_admin is True
        assert u.is_owner is False

    def test_member_is_neither(self):
        u = _make_user("member")
        assert u.is_admin is False
        assert u.is_owner is False

    def test_frozen_dataclass(self):
        u = _make_user("owner")
        with pytest.raises((AttributeError, TypeError)):
            u.role = "member"   # type: ignore[misc]


# ---------------------------------------------------------------------------
# Dev-mode: get_current_user returns synthetic owner
# ---------------------------------------------------------------------------

class TestDevMode:
    def test_returns_bootstrap_owner(self, monkeypatch):
        import api.auth as auth_module
        import api.deps as deps_module
        monkeypatch.setattr(auth_module, "DEV_MODE", True)
        monkeypatch.setattr(deps_module, "DEV_MODE", True)

        import asyncio
        user = asyncio.get_event_loop().run_until_complete(
            deps_module.get_current_user(token=None)
        )
        assert user.role      == "owner"
        assert user.user_id   == deps_module.BOOTSTRAP_USER_ID
        assert user.tenant_id == deps_module.BOOTSTRAP_TENANT_ID

    def test_dev_user_is_admin(self, monkeypatch):
        import api.deps as deps_module
        monkeypatch.setattr(deps_module, "DEV_MODE", True)
        assert deps_module._DEV_USER.is_admin is True


# ---------------------------------------------------------------------------
# Production mode: token required
# ---------------------------------------------------------------------------

class TestProductionMode:
    @pytest.fixture(autouse=True)
    def _prod_mode(self, monkeypatch):
        import api.auth as auth_module
        import api.deps as deps_module
        monkeypatch.setenv("SECRET_KEY", "test-secret-at-least-32-bytes-long!!")
        monkeypatch.setattr(auth_module, "SECRET_KEY", "test-secret-at-least-32-bytes-long!!")
        monkeypatch.setattr(auth_module, "DEV_MODE", False)
        monkeypatch.setattr(deps_module, "DEV_MODE", False)

    def test_no_token_raises_401(self):
        import asyncio
        from fastapi import HTTPException
        from api.deps import get_current_user
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                get_current_user(token=None)
            )
        assert exc_info.value.status_code == 401

    def test_valid_token_resolves_user(self):
        import asyncio
        from api.auth import create_access_token
        from api.deps import get_current_user

        token = create_access_token(SAMPLE_USER_ID, SAMPLE_TENANT_ID, "admin", "a@b.com")
        user = asyncio.get_event_loop().run_until_complete(
            get_current_user(token=token)
        )
        assert user.user_id   == SAMPLE_USER_ID
        assert user.tenant_id == SAMPLE_TENANT_ID
        assert user.role      == "admin"
        assert user.email     == "a@b.com"

    def test_invalid_token_raises_401(self):
        import asyncio
        from fastapi import HTTPException
        from api.deps import get_current_user
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                get_current_user(token="bad.token.here")
            )
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# require_admin
# ---------------------------------------------------------------------------

class TestRequireAdmin:
    def _run(self, role: str):
        import asyncio
        from api.deps import require_admin
        return asyncio.get_event_loop().run_until_complete(
            require_admin(current_user=_make_user(role))
        )

    def test_owner_passes(self):
        user = self._run("owner")
        assert user.role == "owner"

    def test_admin_passes(self):
        user = self._run("admin")
        assert user.role == "admin"

    def test_member_raises_403(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            self._run("member")
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# require_owner
# ---------------------------------------------------------------------------

class TestRequireOwner:
    def _run(self, role: str):
        import asyncio
        from api.deps import require_owner
        return asyncio.get_event_loop().run_until_complete(
            require_owner(current_user=_make_user(role))
        )

    def test_owner_passes(self):
        user = self._run("owner")
        assert user.role == "owner"

    def test_admin_raises_403(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            self._run("admin")
        assert exc_info.value.status_code == 403

    def test_member_raises_403(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            self._run("member")
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# BOOTSTRAP constants sanity checks
# ---------------------------------------------------------------------------

class TestBootstrapConstants:
    def test_bootstrap_tenant_is_valid_uuid(self):
        from api.deps import BOOTSTRAP_TENANT_ID
        assert isinstance(BOOTSTRAP_TENANT_ID, UUID)

    def test_bootstrap_user_is_valid_uuid(self):
        from api.deps import BOOTSTRAP_USER_ID
        assert isinstance(BOOTSTRAP_USER_ID, UUID)

    def test_bootstrap_tenant_matches_migration_003(self):
        """The constant in deps.py must match the UUID in migration 003."""
        from api.deps import BOOTSTRAP_TENANT_ID
        assert str(BOOTSTRAP_TENANT_ID) == "00000000-0000-0000-0000-000000000001"
