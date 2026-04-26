"""Tests for GuardrailsLayer API components: QuotaManager, DEV_MODE, rate limiting."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4


# ===========================================================================
# QuotaManager
# ===========================================================================

class TestQuotaManagerNoDb:
    """When DB is unavailable, QuotaManager is always a no-op."""

    @pytest.mark.asyncio
    async def test_check_and_raise_no_op_without_db(self):
        with patch("db.connection.is_db_available", return_value=False):
            from api.quota import QuotaManager
            # Should not raise
            await QuotaManager.check_and_raise("tenant-1", estimated_tokens=9_999_999)

    @pytest.mark.asyncio
    async def test_record_usage_no_op_without_db(self):
        with patch("db.connection.is_db_available", return_value=False):
            from api.quota import QuotaManager
            await QuotaManager.record_usage("tenant-1", tokens=1000)


class TestQuotaManagerWithDb:
    """QuotaManager behaviour when DB is available."""

    def _mock_db(self, usage: int, budget):
        """Build the minimal mock chain for get_session + execute."""
        row = MagicMock()
        row.token_usage_daily = usage
        row.token_budget_daily = budget
        row.last_usage_reset = "2026-01-01"  # old date → will trigger reset

        result_mock = MagicMock()
        result_mock.first.return_value = row

        session_mock = AsyncMock()
        session_mock.execute = AsyncMock(return_value=result_mock)
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=False)

        return session_mock

    @pytest.mark.asyncio
    async def test_check_allows_when_under_budget(self):
        session = self._mock_db(usage=1000, budget=5000)
        with (
            patch("db.connection.is_db_available", return_value=True),
            patch("db.connection.get_session", return_value=session),
        ):
            from api.quota import QuotaManager
            await QuotaManager.check_and_raise("tenant-1", estimated_tokens=100)

    @pytest.mark.asyncio
    async def test_check_raises_when_over_budget(self):
        session = self._mock_db(usage=4900, budget=5000)
        with (
            patch("db.connection.is_db_available", return_value=True),
            patch("db.connection.get_session", return_value=session),
        ):
            from api.quota import QuotaManager, QuotaBudgetExceeded
            with pytest.raises(QuotaBudgetExceeded) as exc_info:
                await QuotaManager.check_and_raise("tenant-1", estimated_tokens=200)
            assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_check_allows_when_budget_is_none(self):
        session = self._mock_db(usage=999_999, budget=None)  # unlimited
        with (
            patch("db.connection.is_db_available", return_value=True),
            patch("db.connection.get_session", return_value=session),
        ):
            from api.quota import QuotaManager
            await QuotaManager.check_and_raise("tenant-1", estimated_tokens=999_999)

    @pytest.mark.asyncio
    async def test_check_no_op_when_tenant_not_found(self):
        result_mock = MagicMock()
        result_mock.first.return_value = None  # tenant not found

        session_mock = AsyncMock()
        session_mock.execute = AsyncMock(return_value=result_mock)
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("db.connection.is_db_available", return_value=True),
            patch("db.connection.get_session", return_value=session_mock),
        ):
            from api.quota import QuotaManager
            await QuotaManager.check_and_raise("nonexistent-tenant", estimated_tokens=100)

    @pytest.mark.asyncio
    async def test_record_usage_no_op_for_zero_tokens(self):
        with patch("db.connection.is_db_available") as mock_avail:
            from api.quota import QuotaManager
            await QuotaManager.record_usage("tenant-1", tokens=0)
            mock_avail.assert_not_called()  # short-circuits before DB check

    @pytest.mark.asyncio
    async def test_check_gracefully_handles_db_exception(self):
        with (
            patch("db.connection.is_db_available", return_value=True),
            patch("db.connection.get_session", side_effect=RuntimeError("db down")),
        ):
            from api.quota import QuotaManager
            # Should NOT raise — DB errors are non-blocking
            await QuotaManager.check_and_raise("tenant-1", estimated_tokens=100)


# ===========================================================================
# DEV_MODE — healthz endpoint and startup warning
# ===========================================================================

class TestDevModeHealthz:
    def _make_app(self):
        from fastapi.testclient import TestClient
        from api.main import app
        return TestClient(app)

    def test_healthz_no_dev_mode_flag_when_secret_key_set(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "super-secret-key-for-tests-only-1234")
        # Re-import to pick up the env var (DEV_MODE is module-level)
        import importlib
        import api.auth as auth_mod
        importlib.reload(auth_mod)
        import api.main as main_mod
        importlib.reload(main_mod)

        from fastapi.testclient import TestClient
        client = TestClient(main_mod.app)
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert "dev_mode" not in resp.json()

        # Restore
        monkeypatch.delenv("SECRET_KEY", raising=False)
        importlib.reload(auth_mod)
        importlib.reload(main_mod)

    def test_healthz_shows_dev_mode_when_no_secret_key(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        import importlib
        import api.auth as auth_mod
        importlib.reload(auth_mod)
        import api.main as main_mod
        importlib.reload(main_mod)

        from fastapi.testclient import TestClient
        client = TestClient(main_mod.app)
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("dev_mode") is True

    def test_healthz_returns_status_ok(self):
        from fastapi.testclient import TestClient
        from api.main import app
        client = TestClient(app)
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestDevModeStartupWarning:
    def test_warning_logged_when_dev_mode(self, monkeypatch, caplog):
        import logging
        monkeypatch.delenv("SECRET_KEY", raising=False)
        import importlib
        import api.auth as auth_mod
        importlib.reload(auth_mod)
        import api.main as main_mod
        importlib.reload(main_mod)

        from fastapi.testclient import TestClient
        with caplog.at_level(logging.WARNING, logger="api.main"):
            with TestClient(main_mod.app):
                pass  # triggers lifespan startup

        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        dev_mode_warnings = [m for m in warning_messages if "DEV_MODE" in m or "SECRET_KEY" in m]
        assert dev_mode_warnings, (
            f"Expected DEV_MODE warning in logs, got: {warning_messages}"
        )


# ===========================================================================
# Rate limiting — slowapi wired correctly
# ===========================================================================

class TestRateLimitingWired:
    def test_limiter_on_app_state(self):
        from api.main import app
        assert hasattr(app.state, "limiter"), "app.state.limiter not set"

    def test_limiter_is_slowapi_instance(self):
        from api.main import app
        from slowapi import Limiter
        assert isinstance(app.state.limiter, Limiter)

    def test_rate_limit_exceeded_handler_registered(self):
        from api.main import app
        from slowapi.errors import RateLimitExceeded
        # FastAPI stores exception handlers in exception_handlers dict
        assert RateLimitExceeded in app.exception_handlers

    def test_limiter_same_instance_in_routes(self):
        from api.main import app
        from api.rate_limit import limiter as route_limiter
        assert app.state.limiter is route_limiter


class TestRateLimitingLogin:
    """Verify /auth/login returns 429 after exceeding the limit."""

    def test_login_returns_429_after_limit(self, monkeypatch):
        """Hit /auth/login more than 10 times in a row — last requests should be 429."""
        import importlib
        monkeypatch.delenv("SECRET_KEY", raising=False)
        # Reload to ensure limiter state is fresh
        import api.rate_limit as rl_mod
        importlib.reload(rl_mod)
        import api.main as main_mod
        importlib.reload(main_mod)

        from fastapi.testclient import TestClient
        client = TestClient(main_mod.app, raise_server_exceptions=False)

        status_codes = []
        for _ in range(14):
            r = client.post(
                "/auth/login",
                json={"email": "test@example.com", "password": "password"},
            )
            status_codes.append(r.status_code)

        # First 10 should be non-429 (503 in DEV_MODE since auth is disabled),
        # then 429 for the excess requests.
        assert 429 in status_codes, (
            f"Expected at least one 429, got status codes: {status_codes}"
        )

    def test_register_returns_429_after_limit(self, monkeypatch):
        """Hit /auth/register more than 10 times — should trigger 429."""
        import importlib
        monkeypatch.delenv("SECRET_KEY", raising=False)
        import api.rate_limit as rl_mod
        importlib.reload(rl_mod)
        import api.main as main_mod
        importlib.reload(main_mod)

        from fastapi.testclient import TestClient
        client = TestClient(main_mod.app, raise_server_exceptions=False)

        status_codes = []
        for i in range(14):
            r = client.post(
                "/auth/register",
                json={
                    "email": f"user{i}@example.com",
                    "password": "password123",
                    "tenant_name": f"tenant-{i}",
                },
            )
            status_codes.append(r.status_code)

        assert 429 in status_codes, (
            f"Expected at least one 429, got: {status_codes}"
        )
