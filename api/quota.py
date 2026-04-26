"""Tenant-level token quota management.

QuotaManager provides two operations:

  check_and_raise(tenant_id, estimated_tokens)
      Reads the tenant's daily budget and current usage.  Raises
      ``QuotaBudgetExceeded`` (HTTP 429) if adding *estimated_tokens*
      would exceed the budget.  No-op when:
        - the DB is unavailable (file-only mode)
        - the tenant row is not found
        - ``token_budget_daily`` is NULL (unlimited plan)

  record_usage(tenant_id, tokens)
      Atomically increments ``token_usage_daily`` for the tenant.
      Also resets the counter when the calendar day has advanced
      since ``last_usage_reset``.  No-op when DB unavailable.

Both methods are designed to degrade gracefully — a DB outage never
blocks the pipeline.

Daily reset strategy
--------------------
The counter is reset lazily: the first ``record_usage`` call after
midnight (UTC) resets ``token_usage_daily`` to 0 and updates
``last_usage_reset`` before incrementing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


class QuotaBudgetExceeded(HTTPException):
    """Raised when a tenant has consumed their daily token budget."""

    def __init__(self, tenant_id: str) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Daily token budget exceeded for tenant {tenant_id}. "
                "Try again tomorrow or upgrade your plan."
            ),
        )


def _today_utc() -> str:
    """Return today's date as an ISO date string (UTC)."""
    return datetime.now(timezone.utc).date().isoformat()


class QuotaManager:
    """Tenant quota check and usage recording.

    All methods are async and safe to call without a DB connection.
    """

    @staticmethod
    async def check_and_raise(tenant_id: str, estimated_tokens: int = 0) -> None:
        """Raise QuotaBudgetExceeded if the tenant is over their daily limit.

        Parameters
        ----------
        tenant_id:
            UUID string of the tenant.
        estimated_tokens:
            Conservative estimate of tokens about to be consumed.
            Pass 0 to only check whether the current usage is already
            over budget (useful as a lightweight pre-flight check).
        """
        try:
            from db.connection import get_session, is_db_available
            if not is_db_available():
                return

            import sqlalchemy as sa
            from db.models import TenantModel

            async with get_session() as session:
                result = await session.execute(
                    sa.select(
                        TenantModel.token_usage_daily,
                        TenantModel.token_budget_daily,
                    ).where(TenantModel.id == tenant_id)
                )
                row = result.first()

            if row is None:
                return  # tenant not found — skip quota check

            usage, budget = row.token_usage_daily, row.token_budget_daily
            if budget is None:
                return  # NULL = unlimited

            if (usage or 0) + estimated_tokens > budget:
                raise QuotaBudgetExceeded(tenant_id)

        except QuotaBudgetExceeded:
            raise
        except Exception as exc:   # noqa: BLE001
            logger.debug("QuotaManager.check_and_raise failed (non-blocking): %s", exc)

    @staticmethod
    async def record_usage(tenant_id: str, tokens: int) -> None:
        """Increment the tenant's daily token usage counter.

        Resets the counter if the calendar day has advanced since the
        last recorded reset.

        Parameters
        ----------
        tenant_id:
            UUID string of the tenant.
        tokens:
            Number of tokens to add.
        """
        if tokens <= 0:
            return

        try:
            from db.connection import get_session, is_db_available
            if not is_db_available():
                return

            import sqlalchemy as sa
            from db.models import TenantModel

            today = _today_utc()

            async with get_session() as session:
                # Read current state
                result = await session.execute(
                    sa.select(
                        TenantModel.token_usage_daily,
                        TenantModel.last_usage_reset,
                    ).where(TenantModel.id == tenant_id)
                )
                row = result.first()
                if row is None:
                    return

                last_reset = row.last_usage_reset
                new_usage: int

                if last_reset != today:
                    # New day — reset counter
                    new_usage = tokens
                else:
                    new_usage = (row.token_usage_daily or 0) + tokens

                await session.execute(
                    sa.update(TenantModel)
                    .where(TenantModel.id == tenant_id)
                    .values(
                        token_usage_daily=new_usage,
                        last_usage_reset=today,
                    )
                )

        except Exception as exc:   # noqa: BLE001
            logger.debug("QuotaManager.record_usage failed (non-blocking): %s", exc)
