"""Tests for Sprint C — API route protection and tenant isolation.

These tests verify:
1. Tenant isolation: users in tenant A cannot see tenant B's jobs/settings
2. Member visibility: members only see their own jobs
3. Admin guard: sensitive settings writes are blocked for members
4. Job ownership guard: _assert_job_access enforces the rules
5. Settings service: tenant_id scoping + backward compat (no tenant_id → bootstrap)
6. DEV_MODE: all routes return data for bootstrap owner without any token

All tests are unit/functional with mocked DB — no real database needed.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_A1  = UUID("a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1")   # owner in A
USER_A2  = UUID("a2a2a2a2-a2a2-a2a2-a2a2-a2a2a2a2a2a2")   # member in A
USER_B1  = UUID("b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1")   # owner in B

BOOTSTRAP_TENANT = UUID("00000000-0000-0000-0000-000000000001")


def _make_user(user_id=USER_A1, tenant_id=TENANT_A, role="owner"):
    from api.deps import CurrentUser
    return CurrentUser(user_id=user_id, tenant_id=tenant_id, role=role, email=f"{role}@a.com")


# ---------------------------------------------------------------------------
# _assert_job_access
# ---------------------------------------------------------------------------

class TestAssertJobAccess:
    def _make_job(self, tenant_id=None, created_by=None):
        job = MagicMock()
        job.tenant_id  = str(tenant_id) if tenant_id else None
        job.created_by = str(created_by) if created_by else None
        return job

    def test_owner_can_access_own_tenant_job(self):
        from api.routes.jobs import _assert_job_access
        job  = self._make_job(tenant_id=TENANT_A, created_by=USER_B1)  # different creator
        user = _make_user(role="owner")
        _assert_job_access(job, user)   # no exception

    def test_admin_can_access_any_tenant_job(self):
        from api.routes.jobs import _assert_job_access
        job  = self._make_job(tenant_id=TENANT_A, created_by=USER_B1)
        user = _make_user(role="admin")
        _assert_job_access(job, user)   # no exception

    def test_member_can_access_own_job(self):
        from api.routes.jobs import _assert_job_access
        job  = self._make_job(tenant_id=TENANT_A, created_by=USER_A2)
        user = _make_user(user_id=USER_A2, role="member")
        _assert_job_access(job, user)   # no exception

    def test_member_cannot_access_other_member_job(self):
        from api.routes.jobs import _assert_job_access
        from fastapi import HTTPException
        job  = self._make_job(tenant_id=TENANT_A, created_by=USER_A1)
        user = _make_user(user_id=USER_A2, role="member")
        with pytest.raises(HTTPException) as exc:
            _assert_job_access(job, user)
        assert exc.value.status_code == 404     # 404, not 403

    def test_cross_tenant_access_raises_404(self):
        from api.routes.jobs import _assert_job_access
        from fastapi import HTTPException
        job  = self._make_job(tenant_id=TENANT_B)
        user = _make_user(tenant_id=TENANT_A, role="owner")
        with pytest.raises(HTTPException) as exc:
            _assert_job_access(job, user)
        assert exc.value.status_code == 404

    def test_legacy_job_no_tenant_id_is_accessible(self):
        """Jobs without tenant_id (pre-multitenancy) must remain accessible."""
        from api.routes.jobs import _assert_job_access
        job  = self._make_job(tenant_id=None, created_by=None)
        user = _make_user(role="owner")
        _assert_job_access(job, user)   # no exception

    def test_legacy_job_accessible_to_member_with_no_creator(self):
        """Legacy jobs with no created_by are visible even to members."""
        from api.routes.jobs import _assert_job_access
        job  = self._make_job(tenant_id=None, created_by=None)
        user = _make_user(role="member")
        _assert_job_access(job, user)   # no exception


# ---------------------------------------------------------------------------
# CurrentUser role properties (re-verify for the dep integration)
# ---------------------------------------------------------------------------

class TestCurrentUserRoles:
    def test_owner_role_properties(self):
        u = _make_user(role="owner")
        assert u.is_admin and u.is_owner

    def test_admin_role_properties(self):
        u = _make_user(role="admin")
        assert u.is_admin and not u.is_owner

    def test_member_role_properties(self):
        u = _make_user(role="member")
        assert not u.is_admin and not u.is_owner


# ---------------------------------------------------------------------------
# Settings service — tenant_id scoping
# ---------------------------------------------------------------------------

class TestSettingsServiceTenantScoping:
    """Verify settings_service uses tenant_id correctly in memory mode."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def setup_method(self):
        """Clear the in-memory settings store before each test."""
        import api.settings_service as svc
        svc._MEMORY.clear()

    def test_set_and_get_scoped_to_tenant(self):
        import api.settings_service as svc
        self._run(svc.set_setting("foo", "bar", tenant_id=str(TENANT_A)))
        val_a = self._run(svc.get_setting("foo", tenant_id=str(TENANT_A)))
        val_b = self._run(svc.get_setting("foo", tenant_id=str(TENANT_B)))
        assert val_a == "bar"
        assert val_b is None    # tenant B should not see tenant A's setting

    def test_default_tenant_is_bootstrap(self):
        import api.settings_service as svc
        BOOTSTRAP = "00000000-0000-0000-0000-000000000001"
        self._run(svc.set_setting("shared_key", "shared_val"))   # no tenant_id
        val = self._run(svc.get_setting("shared_key"))
        assert val == "shared_val"
        # Should be stored under bootstrap
        assert svc._MEMORY.get((BOOTSTRAP, "shared_key")) == "shared_val"

    def test_fallback_to_bootstrap_for_unknown_tenant(self):
        """When a tenant has no value, fall back to bootstrap (global) setting."""
        import api.settings_service as svc
        BOOTSTRAP = "00000000-0000-0000-0000-000000000001"
        # Write under bootstrap only
        self._run(svc.set_setting("global_setting", "global_val", tenant_id=BOOTSTRAP))
        # Reading as a different tenant should still see it via fallback
        val = self._run(svc.get_setting("global_setting", tenant_id=str(TENANT_A)))
        assert val == "global_val"

    def test_tenant_setting_overrides_bootstrap(self):
        """Per-tenant value takes precedence over bootstrap fallback."""
        import api.settings_service as svc
        BOOTSTRAP = "00000000-0000-0000-0000-000000000001"
        self._run(svc.set_setting("model_config", "global_model", tenant_id=BOOTSTRAP))
        self._run(svc.set_setting("model_config", "tenant_model", tenant_id=str(TENANT_A)))
        val = self._run(svc.get_setting("model_config", tenant_id=str(TENANT_A)))
        assert val == "tenant_model"

    def test_user_profile_per_user_key(self):
        """load_user_profile_dict with user_id reads user_profile:{user_id}."""
        import api.settings_service as svc
        tid = str(TENANT_A)
        uid = str(USER_A1)
        self._run(svc.set_setting(f"user_profile:{uid}", {"name": "Alice"}, tenant_id=tid))
        result = self._run(svc.load_user_profile_dict(tenant_id=tid, user_id=uid))
        assert result == {"name": "Alice"}

    def test_get_all_settings_is_tenant_scoped(self):
        import api.settings_service as svc
        tid_a = str(TENANT_A)
        tid_b = str(TENANT_B)
        self._run(svc.set_setting("k1", "val_a", tenant_id=tid_a))
        self._run(svc.set_setting("k1", "val_b", tenant_id=tid_b))
        all_a = self._run(svc.get_all_settings(tid_a))
        all_b = self._run(svc.get_all_settings(tid_b))
        assert all_a.get("k1") == "val_a"
        assert all_b.get("k1") == "val_b"


# ---------------------------------------------------------------------------
# Settings route — write permission guards
# ---------------------------------------------------------------------------

class TestSettingsWritePermission:
    """Unit-test _check_write_permission without hitting the route handler."""

    def test_member_blocked_from_api_keys(self):
        from fastapi import HTTPException
        from api.routes.settings import _check_write_permission
        member = _make_user(role="member")
        with pytest.raises(HTTPException) as exc:
            _check_write_permission("api_keys", member)
        assert exc.value.status_code == 403

    def test_member_blocked_from_model_config(self):
        from fastapi import HTTPException
        from api.routes.settings import _check_write_permission
        member = _make_user(role="member")
        with pytest.raises(HTTPException) as exc:
            _check_write_permission("model_config", member)
        assert exc.value.status_code == 403

    def test_admin_allowed_api_keys(self):
        from api.routes.settings import _check_write_permission
        admin = _make_user(role="admin")
        _check_write_permission("api_keys", admin)   # no exception

    def test_owner_allowed_all_sensitive_keys(self):
        from api.routes.settings import _check_write_permission
        owner = _make_user(role="owner")
        for key in ("api_keys", "model_config", "ceo_config", "mcp_servers"):
            _check_write_permission(key, owner)   # no exception

    def test_member_allowed_user_profile_write(self):
        """Members can write user_profile (auto-namespaced to their user_id)."""
        from api.routes.settings import _check_write_permission
        member = _make_user(role="member")
        _check_write_permission("user_profile", member)   # no exception

    def test_effective_key_namespaces_user_profile(self):
        from api.routes.settings import _effective_key
        member = _make_user(user_id=USER_A2, role="member")
        eff_key, tid = _effective_key("user_profile", member)
        assert eff_key == f"user_profile:{USER_A2}"
        assert tid == str(TENANT_A)

    def test_effective_key_leaves_other_keys_unchanged(self):
        from api.routes.settings import _effective_key
        owner = _make_user(role="owner")
        eff_key, _ = _effective_key("model_config", owner)
        assert eff_key == "model_config"


# ---------------------------------------------------------------------------
# JobRecord — tenant_id and created_by fields
# ---------------------------------------------------------------------------

class TestJobRecordFields:
    def test_new_job_has_none_tenant(self):
        from api.job_store import create_job
        job = create_job("build", "ws", "req")
        assert job.tenant_id is None
        assert job.created_by is None

    def test_can_set_tenant_and_owner(self):
        from api.job_store import create_job
        job = create_job("build", "ws", "req")
        job.tenant_id  = str(TENANT_A)
        job.created_by = str(USER_A1)
        assert job.tenant_id  == str(TENANT_A)
        assert job.created_by == str(USER_A1)

    def test_import_job_preserves_tenant_fields(self):
        from api.job_store import import_job, _store
        job_data = {
            "id":           "testXXX1",
            "type":         "build",
            "workspace_id": "ws",
            "requirement":  "req",
            "status":       "completed",
            "created_at":   "2026-01-01T00:00:00+00:00",
            "tenant_id":    str(TENANT_A),
            "created_by":   str(USER_A1),
        }
        if job_data["id"] in _store:
            del _store[job_data["id"]]
        job = import_job(job_data)
        assert job.tenant_id  == str(TENANT_A)
        assert job.created_by == str(USER_A1)

    def test_import_job_legacy_no_tenant(self):
        """Legacy jobs without tenant_id must import cleanly."""
        from api.job_store import import_job, _store
        job_data = {
            "id":           "legacyJ1",
            "type":         "build",
            "workspace_id": "ws",
            "requirement":  "req",
            "status":       "completed",
            "created_at":   "2026-01-01T00:00:00+00:00",
        }
        if job_data["id"] in _store:
            del _store[job_data["id"]]
        job = import_job(job_data)
        assert job.tenant_id  is None
        assert job.created_by is None


# ---------------------------------------------------------------------------
# DEV_MODE — get_current_user returns bootstrap owner
# ---------------------------------------------------------------------------

class TestDevModeRoutePassThrough:
    """In dev mode, all routes behave as bootstrap owner (no auth required)."""

    def test_dev_user_can_access_any_tenant_job(self):
        """Bootstrap owner (dev mode) sees jobs with no tenant_id."""
        from api.routes.jobs import _assert_job_access
        from api.deps import _DEV_USER

        job = MagicMock()
        job.tenant_id  = None
        job.created_by = None
        _assert_job_access(job, _DEV_USER)   # no exception

    def test_dev_user_is_admin(self):
        from api.deps import _DEV_USER
        assert _DEV_USER.is_admin is True

    def test_dev_user_is_owner(self):
        from api.deps import _DEV_USER
        assert _DEV_USER.is_owner is True

    def test_dev_user_tenant_is_bootstrap(self):
        from api.deps import _DEV_USER, BOOTSTRAP_TENANT_ID
        assert _DEV_USER.tenant_id == BOOTSTRAP_TENANT_ID


# ---------------------------------------------------------------------------
# require_admin + require_owner integration
# ---------------------------------------------------------------------------

class TestRoleGatingIntegration:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_require_admin_with_member_raises_403(self):
        from fastapi import HTTPException
        from api.deps import require_admin
        member = _make_user(role="member")
        with pytest.raises(HTTPException) as exc:
            self._run(require_admin(current_user=member))
        assert exc.value.status_code == 403

    def test_require_admin_with_admin_passes(self):
        from api.deps import require_admin
        admin = _make_user(role="admin")
        user  = self._run(require_admin(current_user=admin))
        assert user.role == "admin"

    def test_require_owner_with_admin_raises_403(self):
        from fastapi import HTTPException
        from api.deps import require_owner
        admin = _make_user(role="admin")
        with pytest.raises(HTTPException) as exc:
            self._run(require_owner(current_user=admin))
        assert exc.value.status_code == 403

    def test_require_owner_with_owner_passes(self):
        from api.deps import require_owner
        owner = _make_user(role="owner")
        user  = self._run(require_owner(current_user=owner))
        assert user.role == "owner"


# ---------------------------------------------------------------------------
# Repository settings — tenant_id parameter
# ---------------------------------------------------------------------------

class TestRepositorySettingsTenantId:
    """Verify the repository constants match the migration constants."""

    def test_bootstrap_tenant_constant_matches_migration(self):
        from db.repository import _BOOTSTRAP_TENANT
        assert _BOOTSTRAP_TENANT == "00000000-0000-0000-0000-000000000001"

    def test_deps_bootstrap_matches_repository_bootstrap(self):
        from db.repository import _BOOTSTRAP_TENANT
        from api.deps import BOOTSTRAP_TENANT_ID
        assert str(BOOTSTRAP_TENANT_ID) == _BOOTSTRAP_TENANT

    def test_settings_service_bootstrap_matches_repository(self):
        import api.settings_service as svc
        from db.repository import _BOOTSTRAP_TENANT
        assert svc._BOOTSTRAP_TENANT == _BOOTSTRAP_TENANT
