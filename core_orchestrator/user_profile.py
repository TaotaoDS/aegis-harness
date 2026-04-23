"""User profile model for context-aware CEO communication.

The UserProfile is loaded once per job (from the settings store) and
injected into CEOAgent so that the interview adapts to the user's
background, technical level, and preferred language.

TechLevel tiers
---------------
TECHNICAL       — Engineer / developer; standard interview prompt, full
                  technical vocabulary allowed.
SEMI_TECHNICAL  — Product manager, designer, data analyst; light jargon
                  OK, acronyms should be spelled out on first use.
NON_TECHNICAL   — Business stakeholder, entrepreneur, end-user; plain
                  language only, options-driven questions, no jargon.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class TechLevel(str, Enum):
    TECHNICAL       = "technical"
    SEMI_TECHNICAL  = "semi_technical"
    NON_TECHNICAL   = "non_technical"


@dataclass
class UserProfile:
    """Represents the person submitting requirements to the CEO Agent."""

    name:            str       = "User"
    role:            str       = ""          # e.g. "Product Manager", "CTO"
    technical_level: TechLevel = TechLevel.TECHNICAL
    language:        str       = "auto"      # "auto" = detect from message
    notes:           str       = ""          # free-form background notes

    # ---------------------------------------------------------------------------
    # Convenience predicates
    # ---------------------------------------------------------------------------

    @property
    def is_technical(self) -> bool:
        return self.technical_level == TechLevel.TECHNICAL

    @property
    def is_semi_technical(self) -> bool:
        return self.technical_level == TechLevel.SEMI_TECHNICAL

    @property
    def is_non_technical(self) -> bool:
        return self.technical_level == TechLevel.NON_TECHNICAL

    @property
    def display_name(self) -> str:
        """The name CEO should use to address this user."""
        return self.name or "there"

    # ---------------------------------------------------------------------------
    # Serialisation
    # ---------------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name":            self.name,
            "role":            self.role,
            "technical_level": self.technical_level.value,
            "language":        self.language,
            "notes":           self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserProfile":
        """Construct from a plain dict (e.g. loaded from JSON / DB settings).

        Unknown keys are ignored; missing keys use defaults.
        """
        raw_level = data.get("technical_level", TechLevel.TECHNICAL.value)
        try:
            level = TechLevel(raw_level)
        except ValueError:
            level = TechLevel.TECHNICAL

        return cls(
            name            = str(data.get("name", "User") or "User"),
            role            = str(data.get("role", "") or ""),
            technical_level = level,
            language        = str(data.get("language", "auto") or "auto"),
            notes           = str(data.get("notes", "") or ""),
        )

    # ---------------------------------------------------------------------------
    # CEO prompt helpers
    # ---------------------------------------------------------------------------

    def user_context_block(self) -> str:
        """Return a compact context paragraph for injection into CEO prompts."""
        parts = [f"User: {self.name}"]
        if self.role:
            parts[0] += f" ({self.role})"
        if self.technical_level != TechLevel.TECHNICAL:
            parts.append(f"Technical level: {self.technical_level.value.replace('_', ' ')}")
        if self.notes:
            parts.append(f"Background: {self.notes}")
        return "\n".join(parts)

    def interview_style_instructions(self) -> str:
        """Return style instructions to append to the interview system prompt."""
        if self.is_non_technical:
            return _NON_TECH_STYLE
        if self.is_semi_technical:
            return _SEMI_TECH_STYLE
        return ""   # technical users: no extra instructions


# ---------------------------------------------------------------------------
# Style instruction snippets (injected into interview prompts)
# ---------------------------------------------------------------------------

_NON_TECH_STYLE = """\

=== COMMUNICATION STYLE (NON-TECHNICAL USER) ===
The user is NOT a developer or engineer.  Strictly follow these rules:
1. FORBIDDEN words/phrases: API, REST, GraphQL, endpoint, backend, frontend,
   database, schema, framework, deployment, stack, container, cloud, server,
   microservice, SDK, CLI, regex, async, cache, token, webhook, middleware.
2. Replace jargon with plain-English analogies:
   - "database" → "a place where we save information"
   - "API"      → "the connection between two apps"
   - "deploy"   → "make it live / publish it"
3. Ask ONE short, concrete question per round.
4. When helpful, include 2–4 labelled options (A, B, C…) the user can pick.
5. Use encouraging, friendly language — never make the user feel "dumb".
6. Maximum question length: 2 sentences.
=== END STYLE RULES ===
"""

_SEMI_TECH_STYLE = """\

=== COMMUNICATION STYLE (SEMI-TECHNICAL USER) ===
The user has a non-engineering background (e.g. product, design, data).
1. Technical terms are OK but spell out acronyms on first use.
2. Avoid deep infrastructure details (deployment config, CI/CD, IaC).
3. Keep questions concise; skip implementation minutiae.
=== END STYLE RULES ===
"""


# ---------------------------------------------------------------------------
# Default profile singleton (used when no profile is configured)
# ---------------------------------------------------------------------------

DEFAULT_PROFILE = UserProfile()
