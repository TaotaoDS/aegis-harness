"""Authentication utilities.

Responsibilities
----------------
- JWT access-token creation and validation
- Refresh token creation, hashing, and rotation
- Password hashing (bcrypt) and verification

Token design
------------
Access token  — HS256 JWT, 15-minute TTL, carries sub/tid/role/email.
                Never stored in the DB; validated statlessly on every request.
Refresh token — opaque UUID issued as a JWT; the raw token is sent to the
                client, its SHA-256 hash is stored in the ``refresh_tokens``
                table so it can be revoked without storing the plaintext.

Dev mode
--------
When ``SECRET_KEY`` is absent from the environment, all token operations are
disabled.  ``decode_access_token`` raises a 401 just as it would for an
invalid token.  ``DEV_MODE`` is exported so ``api/deps.py`` can bypass auth
entirely when ``SECRET_KEY`` is unset.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException, status

# --- optional deps (not in requirements.txt yet — imported lazily) ----------
try:
    from jose import JWTError, jwt as _jwt
    _JOSE_AVAILABLE = True
except ImportError:                             # pragma: no cover
    _JOSE_AVAILABLE = False

import bcrypt as _bcrypt

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SECRET_KEY: str | None = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS   = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS",   "7"))

# When SECRET_KEY is absent the system runs without auth enforcement.
DEV_MODE: bool = not bool(SECRET_KEY)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TokenPayload:
    sub:   UUID    # user id
    tid:   UUID    # tenant id
    role:  str     # "owner" | "admin" | "member"
    email: str


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# Refresh-token hashing  (SHA-256, stored in DB; raw token sent to client)
# ---------------------------------------------------------------------------

def hash_refresh_token(raw: str) -> str:
    """Return the hex SHA-256 digest of *raw*."""
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# JWT utilities
# ---------------------------------------------------------------------------

def create_access_token(
    user_id: UUID,
    tenant_id: UUID,
    role: str,
    email: str,
) -> str:
    """Encode and return a signed JWT access token."""
    if not _JOSE_AVAILABLE:
        raise RuntimeError("python-jose[cryptography] is required for JWT creation")
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY environment variable is not set")

    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub":   str(user_id),
        "tid":   str(tenant_id),
        "role":  role,
        "email": email,
        "exp":   expire,
        "iat":   datetime.now(timezone.utc),
        "type":  "access",
    }
    return _jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: UUID) -> tuple[str, str]:
    """Return ``(raw_token, token_hash)``.

    The raw token is sent to the client; store only the hash in the DB.
    The token itself is a signed JWT so we can read ``exp`` without a DB
    round-trip during rotation.
    """
    if not _JOSE_AVAILABLE:
        raise RuntimeError("python-jose[cryptography] is required for JWT creation")
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY environment variable is not set")

    jti = str(uuid4())
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub":  str(user_id),
        "jti":  jti,
        "exp":  expire,
        "iat":  datetime.now(timezone.utc),
        "type": "refresh",
    }
    raw = _jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return raw, hash_refresh_token(raw)


def decode_access_token(token: str) -> TokenPayload:
    """Decode and validate an access token.

    Raises ``HTTPException(401)`` on any failure (expired, invalid signature,
    wrong type, missing fields).
    """
    if not _JOSE_AVAILABLE or not SECRET_KEY:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Auth not configured")

    try:
        payload = _jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Wrong token type")

    try:
        return TokenPayload(
            sub=UUID(payload["sub"]),
            tid=UUID(payload["tid"]),
            role=payload["role"],
            email=payload["email"],
        )
    except (KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Malformed token payload")


def decode_refresh_token_sub(token: str) -> UUID:
    """Decode the ``sub`` (user_id) from a refresh token without full validation.

    The DB lookup (revocation check + expiry) is the authoritative validation;
    this only extracts the user_id to know which row to query.
    Raises ``HTTPException(401)`` if the token cannot be decoded at all.
    """
    if not _JOSE_AVAILABLE or not SECRET_KEY:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Auth not configured")

    try:
        payload = _jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"verify_exp": False},   # expiry checked via DB row
        )
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Wrong token type")

    try:
        return UUID(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Malformed refresh token")
