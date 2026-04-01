"""Minimal PII sanitization middleware.

Provides regex-based detection and redaction of common PII patterns,
with a composable pipeline interface.
"""

import re
from typing import Callable

Sanitizer = Callable[[str], str]

# --- Regex patterns (compiled once) ---

_EMAIL_RE = re.compile(r'(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z])')

_PHONE_RE = re.compile(
    r'(?<!\d)1[3-9]\d{9}(?!\d)'           # Chinese mobile
    r'|(?<!\d)\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)'  # US format
    r'|\+\d{1,3}[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}'  # International
)

_IDCARD_RE = re.compile(r'(?<!\d)\d{17}[\dXx](?!\d)')

_CREDITCARD_RE = re.compile(r'(?<!\d)\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{1,7}(?!\d)')


# --- Sanitizer functions ---

def sanitize_email(text: str) -> str:
    return _EMAIL_RE.sub('[EMAIL_REDACTED]', text)


def sanitize_phone(text: str) -> str:
    return _PHONE_RE.sub('[PHONE_REDACTED]', text)


def sanitize_id_card(text: str) -> str:
    return _IDCARD_RE.sub('[IDCARD_REDACTED]', text)


def sanitize_credit_card(text: str) -> str:
    return _CREDITCARD_RE.sub('[CREDITCARD_REDACTED]', text)


# --- Composition ---

def compose(*sanitizers: Sanitizer) -> Sanitizer:
    """Chain multiple sanitizers into a single pipeline."""
    def _pipeline(text: str) -> str:
        for s in sanitizers:
            text = s(text)
        return text
    return _pipeline


def default_pipeline() -> Sanitizer:
    """Standard PII pipeline with all built-in sanitizers.

    Order matters: id_card runs before credit_card to prevent
    18-digit ID numbers from partially matching credit card patterns.
    """
    return compose(
        sanitize_email,
        sanitize_phone,
        sanitize_id_card,
        sanitize_credit_card,
    )
