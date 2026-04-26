"""GuardrailsLayer: prompt injection detection and content moderation.

Two components:

  PromptGuard     — detects prompt injection in user-supplied task content
                    before it is embedded in an LLM system prompt.

  ContentModerator— screens LLM-generated file content before it is
                    written to disk; catches hardcoded credentials and
                    obfuscated payloads.

Both components return a ``GuardResult`` and are disabled when the
``GUARDRAILS_ENABLED`` environment variable is set to ``"false"``.

GuardRailViolation is raised by ArchitectAgent when a check fails and
should be treated as a non-retryable task failure.
"""

import os
import re
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Runtime kill-switch (for testing / local dev)
# ---------------------------------------------------------------------------

def _guardrails_enabled() -> bool:
    return os.environ.get("GUARDRAILS_ENABLED", "true").lower().strip() != "false"


# ---------------------------------------------------------------------------
# GuardResult
# ---------------------------------------------------------------------------

class GuardResult:
    """Result of a guardrail check."""

    __slots__ = ("allowed", "reason")

    def __init__(self, allowed: bool, reason: str = "") -> None:
        self.allowed = allowed
        self.reason = reason

    def __bool__(self) -> bool:
        return self.allowed

    def __repr__(self) -> str:  # pragma: no cover
        return f"GuardResult(allowed={self.allowed}, reason={self.reason!r})"


class GuardRailViolation(Exception):
    """Raised when a guardrail blocks execution.

    Treated as a non-retryable task failure — do not pass to the LLM retry loop.
    """


# ---------------------------------------------------------------------------
# PromptGuard — injection detection patterns
# ---------------------------------------------------------------------------

_RAW_INJECTION_PATTERNS: List[Tuple[str, str]] = [
    # Classic "ignore instructions" variants
    (r"ignore\s+(all\s+)?previous\s+instructions?",     "ignore previous instructions"),
    (r"ignore\s+(all\s+)?prior\s+instructions?",         "ignore prior instructions"),
    (r"ignore\s+the\s+above\s+instructions?",            "ignore the above instructions"),
    (r"disregard\s+.*\binstructions?\b",                 "disregard instructions"),
    (r"forget\s+(all\s+|your\s+)?instructions?",         "forget instructions"),
    (r"override\s+(your\s+)?(previous\s+)?instructions?","override instructions"),
    # New-instructions directives
    (r"new\s+instructions?\s*:",                         "new instructions directive"),
    (r"your\s+new\s+(role|task|instructions?|directive)", "new role/task injection"),
    (r"updated\s+(system\s+)?instructions?\s*:",         "updated instructions directive"),
    # Role/persona hijacking
    (r"you\s+are\s+now\s+(a|an|the)\s+",                "role reassignment"),
    (r"act\s+as\s+(?:if\s+you|though\s+you|an?\s+(?:AI|bot|system|unrestric|uncensor|jailbroken|evil|malicious))",
                                                         "act-as injection"),
    (r"pretend\s+(?:to\s+be\s+(?:a|an)\s+|you\s+are\s+|you're\s+)",
                                                         "pretend-to-be injection"),
    (r"roleplay\s+as\s+",                                "roleplay injection"),
    # Jailbreak markers
    (r"\bjailbreak\b",                                   "jailbreak keyword"),
    (r"\bDAN\b",                                         "DAN jailbreak"),
    (r"do\s+anything\s+now",                             "DAN variant"),
    (r"\bGrandma\s+trick\b",                             "Grandma jailbreak variant"),
    # System prompt extraction
    (r"reveal\s+(your\s+)?(system\s+)?prompt",           "system prompt extraction"),
    (r"show\s+(me\s+)?your\s+(system\s+)?prompt",        "system prompt extraction"),
    (r"print\s+(your\s+)?(system\s+)?instructions?",     "system prompt printing"),
    (r"repeat\s+(your\s+)?(system\s+)?instructions?",    "system prompt extraction"),
    (r"what\s+(are|is)\s+your\s+(system\s+)?instructions?",
                                                         "instructions query"),
    # Template injection (XML / ChatML / Llama formats)
    (r"</?(system|instructions?|prompt)>",               "XML prompt tag injection"),
    (r"\[INST\]|\[/INST\]",                              "Llama instruction injection"),
    (r"<\|im_start\|>",                                  "ChatML injection"),
    (r"<\|im_end\|>",                                    "ChatML injection"),
    # Human/Assistant turn injection
    (r"\nHuman\s*:\s*\n",                                "Human turn injection"),
    (r"\nAssistant\s*:\s*\n",                            "Assistant turn injection"),
]

_INJECTION_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(pat, re.IGNORECASE | re.MULTILINE), desc)
    for pat, desc in _RAW_INJECTION_PATTERNS
]


class PromptGuard:
    """Detects prompt injection attempts in user-supplied task content.

    Call ``check_input(task_content)`` before embedding user content into
    a system prompt.  Returns a ``GuardResult``; if ``allowed=False`` the
    reason describes the matched pattern.

    Disabled when ``GUARDRAILS_ENABLED=false``.
    """

    @staticmethod
    def check_input(text: str) -> GuardResult:
        """Screen *text* for injection patterns.  Returns GuardResult."""
        if not _guardrails_enabled():
            return GuardResult(allowed=True)

        for pattern, desc in _INJECTION_PATTERNS:
            if pattern.search(text):
                return GuardResult(
                    allowed=False,
                    reason=f"Prompt injection detected: {desc}",
                )
        return GuardResult(allowed=True)


# ---------------------------------------------------------------------------
# ContentModerator — generated-content screening
# ---------------------------------------------------------------------------

_RAW_CONTENT_PATTERNS: List[Tuple[str, str]] = [
    # Hardcoded API keys (real-format patterns, not test placeholders)
    # OpenAI: sk-[20+ chars] or sk-proj-[20+ chars]
    (r'\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b',             "hardcoded OpenAI API key"),
    # Anthropic: sk-ant-api03-...
    (r'\bsk-ant-api0[0-9]-[A-Za-z0-9_\-]{40,}\b',        "hardcoded Anthropic API key"),
    # GitHub tokens: ghp_[30+ chars], github_pat_[50+ chars]
    (r'\bghp_[A-Za-z0-9]{30,}\b',                        "hardcoded GitHub token"),
    (r'\bgithub_pat_[A-Za-z0-9_]{50,}\b',                "hardcoded GitHub PAT"),
    # AWS access key id
    (r'\bAKIA[0-9A-Z]{16}\b',                             "hardcoded AWS access key"),
    # Obfuscated execution (base64-decode + exec)
    (r'exec\s*\(\s*base64\s*\.\s*b64decode\s*\(',         "exec(base64.decode) obfuscation"),
    (r'eval\s*\(\s*base64\s*\.\s*b64decode\s*\(',         "eval(base64.decode) obfuscation"),
    # Reverse shell patterns (common netcat/bash variants)
    (r'bash\s+-i\s+>&\s*/dev/tcp/',                       "reverse shell (bash/tcp)"),
    # nc with execute-flag (-e) and an IP address (order-independent)
    (r'\bnc\b.*?-e\b.*?\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}',
                                                          "reverse shell (netcat -e)"),
]

_CONTENT_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(pat, re.IGNORECASE), desc)
    for pat, desc in _RAW_CONTENT_PATTERNS
]


class ContentModerator:
    """Screens LLM-generated file content before it is written to disk.

    Detects hardcoded credentials and obfuscated payloads.  Designed to have
    a very low false-positive rate — only patterns that are unambiguously
    malicious or extremely unlikely to appear in legitimate generated code.

    Disabled when ``GUARDRAILS_ENABLED=false``.
    """

    @staticmethod
    def screen_output(content: str) -> GuardResult:
        """Screen *content* for dangerous patterns.  Returns GuardResult."""
        if not _guardrails_enabled():
            return GuardResult(allowed=True)

        for pattern, desc in _CONTENT_PATTERNS:
            if pattern.search(content):
                return GuardResult(
                    allowed=False,
                    reason=f"Dangerous content detected: {desc}",
                )
        return GuardResult(allowed=True)
