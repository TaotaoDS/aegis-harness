"""InterviewManager — blocking gate for the CEO interview phase.

The CEO pipeline runs in a ThreadPoolExecutor thread. When a new question
is ready, InterviewManager.wait_for_answer() blocks the pipeline thread,
emits a ceo.question SSE event, and waits for the user to respond.

The FastAPI handler POST /jobs/{id}/answer calls submit_answer(), which
sets the threading.Event and unblocks the pipeline.

This mirrors the HITLManager pattern (threading.Event bridge across the
async/sync boundary) but is purpose-built for the interview phase:
  - One gate per question (replaced each round)
  - Returns the answer string (not a bool)
  - Times out gracefully after 1 hour → CEO proceeds with empty answer
"""

import threading
from typing import Optional


class InterviewGate:
    """One-shot blocking gate for a single question-answer exchange."""

    def __init__(self) -> None:
        self._event  = threading.Event()
        self._answer: Optional[str] = None

    def wait(self, timeout: float = 3_600.0) -> str:
        """Block the pipeline thread until submit() is called or timeout.

        Returns the submitted answer, or an empty string on timeout.
        (An empty answer tells the CEO to proceed with whatever it has.)
        """
        self._event.wait(timeout=timeout)
        return self._answer or ""

    def submit(self, answer: str) -> None:
        """Called from the async API handler to unblock the pipeline thread."""
        self._answer = answer
        self._event.set()

    @property
    def is_resolved(self) -> bool:
        return self._event.is_set()


class InterviewManager:
    """Manages the CEO interview phase for a single web-mode job.

    CLI mode drives the interview directly via input(); this class is only
    instantiated for jobs created through the FastAPI /jobs endpoint.
    """

    def __init__(self, job_id: str, bus) -> None:
        self._job_id  = job_id
        self._bus     = bus
        self._gate:   Optional[InterviewGate] = None
        self._current_question: Optional[str] = None
        self._answers_given: int = 0

    # ── Called from pipeline thread (blocking) ────────────────────────────

    def wait_for_answer(self, question: str) -> str:
        """Emit ceo.question event and block until the user submits an answer.

        Called by job_runner from the pipeline thread.  Returns the answer
        string (or "" on 1-hour timeout, letting the CEO proceed).
        """
        gate = InterviewGate()
        self._gate = gate
        self._current_question = question

        # Emit via AsyncQueueBus — call_soon_threadsafe handles the thread
        # boundary so SSE clients receive the event immediately.
        self._bus.emit("ceo.question", question=question)

        answer = gate.wait(timeout=3_600.0)
        self._answers_given += 1
        self._current_question = None
        self._gate = None
        return answer

    # ── Called from async API handler (non-blocking) ──────────────────────

    def submit_answer(self, answer: str) -> bool:
        """Submit the user's answer and unblock the pipeline thread.

        Returns True if there was a pending gate (answer accepted).
        Returns False if no question is currently pending.
        """
        gate = self._gate
        if gate is None or gate.is_resolved:
            return False
        gate.submit(answer)
        return True

    # ── Inspection ────────────────────────────────────────────────────────

    @property
    def pending_question(self) -> Optional[str]:
        """The question currently awaiting an answer, or None."""
        return self._current_question

    @property
    def answers_given(self) -> int:
        """Total number of answers submitted so far."""
        return self._answers_given
