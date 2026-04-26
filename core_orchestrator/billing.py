"""FinOps billing engine — intercepts LLM usage and enforces credit limits.

Architecture
------------
The billing system uses a thread-local side-channel so that the LLM connector
layer can emit usage records without any changes to method signatures.

Flow per job:
  1. job_runner loads the tenant's credit_balance and installs a BillingContext
     into thread-local storage before starting the pipeline.
  2. After each successful LLM API call, the connector calls record_usage(),
     which appends a LLMUsage record to the active context.
  3. ModelRouter calls check_credit() before each API call; raises
     InsufficientCreditError (→ HTTP 402) if the balance is exhausted.
  4. After the pipeline completes, job_runner calls flush_context() which
     schedules an async DB write to persist billing events and deduct the
     tenant's credit_balance.

Public API
----------
LLMUsage              — token/model data captured from one API response
BillingContext        — per-job accumulator set on the thread-local
InsufficientCreditError — raised by check_credit() when balance = 0
get_billing_context() / set_billing_context() — thread-local accessors
record_usage(model_id, prompt_tokens, completion_tokens) — called by connectors
check_credit()        — called by ModelRouter before each LLM call
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class LLMUsage:
    """Token consumption captured from one LLM API response."""
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class InsufficientCreditError(Exception):
    """Raised when a tenant's credit balance is exhausted.

    The job runner maps this to HTTP 402 Payment Required and stops the
    pipeline, preventing any further LLM calls from being made.
    """


# ---------------------------------------------------------------------------
# Per-job billing accumulator
# ---------------------------------------------------------------------------

class BillingContext:
    """Accumulates LLM usage for one pipeline run.

    Lifecycle: created by job_runner → installed in thread-local → connectors
    append usage records → job_runner flushes to DB after pipeline.

    Parameters
    ----------
    tenant_id      : Tenant owning this job.
    job_id         : Job identifier (for billing event audit trail).
    credit_balance : Tenant's current credit balance in USD.
                     None means unlimited (no enforcement).
    """

    def __init__(
        self,
        tenant_id: str,
        job_id: Optional[str] = None,
        credit_balance: Optional[float] = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.job_id = job_id
        self.credit_balance = credit_balance   # None → unlimited
        self.records: List[LLMUsage] = []

    def record(self, usage: LLMUsage) -> None:
        """Append one usage record (called from connector layer)."""
        self.records.append(usage)
        logger.debug(
            "[billing] %s %d+%d tokens (tenant=%s job=%s)",
            usage.model_id, usage.prompt_tokens, usage.completion_tokens,
            self.tenant_id, self.job_id,
        )

    def is_credit_available(self) -> bool:
        """Return False only when a finite balance has been fully exhausted."""
        if self.credit_balance is None:
            return True  # unlimited
        return self.credit_balance > 0.0

    @property
    def total_prompt_tokens(self) -> int:
        return sum(r.prompt_tokens for r in self.records)

    @property
    def total_completion_tokens(self) -> int:
        return sum(r.completion_tokens for r in self.records)


# ---------------------------------------------------------------------------
# Thread-local storage
# ---------------------------------------------------------------------------

_local = threading.local()


def get_billing_context() -> Optional[BillingContext]:
    """Return the active BillingContext for this thread, or None."""
    return getattr(_local, "context", None)


def set_billing_context(ctx: Optional[BillingContext]) -> None:
    """Install (or clear) the billing context for this thread."""
    _local.context = ctx


# ---------------------------------------------------------------------------
# Connector-facing helpers
# ---------------------------------------------------------------------------

def record_usage(model_id: str, prompt_tokens: int, completion_tokens: int) -> None:
    """Record LLM token usage in the active billing context.

    No-op when no context is installed (e.g. in tests or CLI use).
    Called once per LLM API response, from inside the connector.
    """
    ctx = get_billing_context()
    if ctx is None:
        return
    ctx.record(LLMUsage(
        model_id=model_id,
        prompt_tokens=max(0, prompt_tokens),
        completion_tokens=max(0, completion_tokens),
    ))


# ---------------------------------------------------------------------------
# ModelRouter-facing helper
# ---------------------------------------------------------------------------

def check_credit() -> None:
    """Raise InsufficientCreditError if the tenant balance is exhausted.

    No-op when no billing context is installed. Called by ModelRouter
    immediately before dispatching each LLM API request.
    """
    ctx = get_billing_context()
    if ctx is None:
        return
    if not ctx.is_credit_available():
        raise InsufficientCreditError(
            f"Tenant '{ctx.tenant_id}' credit balance exhausted. "
            "Please top up to continue. (HTTP 402)"
        )
