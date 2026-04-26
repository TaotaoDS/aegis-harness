"""Context compression for mid-task model switches.

When the Architect's LLM fails mid-task and a different model takes over,
the new model needs a concise briefing — not the full conversation history
(which wastes tokens and may not even be available).

compress_task_progress() builds a compact hand-off note:
  - What the task goal is (truncated)
  - Which files have already been written
  - What went wrong with the previous model
  - A clear instruction to continue, not restart
"""

from __future__ import annotations

import textwrap
from typing import List


_GOAL_MAX   = 600   # chars for the task goal excerpt
_ERROR_MAX  = 350   # chars for the error summary
_FILES_MAX  = 15    # max files listed before truncating


def compress_task_progress(
    task_content: str,
    completed_files: List[str],
    error_summary: str,
    attempt: int,
    failed_model: str = "",
) -> str:
    """Return a compact briefing (<= ~1 200 chars) for resuming a failed task.

    Parameters
    ----------
    task_content:    Full text of the task file (will be truncated).
    completed_files: Files already written to the workspace.
    error_summary:   What went wrong (exception message or feedback text).
    attempt:         Which attempt number this continuation represents.
    failed_model:    Name of the model that failed (informational only).
    """
    goal_excerpt = textwrap.shorten(task_content.strip(), width=_GOAL_MAX, placeholder=" …")
    error_excerpt = textwrap.shorten(error_summary.strip(), width=_ERROR_MAX, placeholder=" …")

    parts: List[str] = [
        f"[TASK RESUME — attempt {attempt}]",
        f"Previous model: {failed_model}" if failed_model else "",
        "",
        "## Task Goal",
        goal_excerpt,
        "",
    ]

    if completed_files:
        listed = completed_files[:_FILES_MAX]
        extra  = len(completed_files) - _FILES_MAX
        parts += ["## Already Written (do NOT rewrite these)"]
        parts += [f"  - {f}" for f in listed]
        if extra > 0:
            parts.append(f"  … and {extra} more file(s)")
        parts.append("")

    if error_excerpt:
        parts += [
            "## Why Previous Attempt Failed",
            error_excerpt,
            "",
        ]

    parts += [
        "## Instructions",
        "Continue from where the previous attempt left off.",
        "- Write only the files that are MISSING or INCOMPLETE.",
        "- Do NOT modify already-written files unless they contain errors.",
        "- Call write_file() for every new or corrected file.",
    ]

    return "\n".join(p for p in parts if p is not None)
