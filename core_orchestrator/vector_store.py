"""Semantic vector store for solution documents.

Pluggable embedding backend
---------------------------
The provider is selected in this order (highest priority first):

1. **Environment variables**:

   =============================  =============================================
   ``EMBEDDING_PROVIDER``         ``"openai"`` or ``"ollama"``
   ``EMBEDDING_MODEL``            model / checkpoint name
   ``EMBEDDING_BASE_URL``         base URL (required for Ollama; optional for
                                  OpenAI-compatible endpoints)
   ``EMBEDDING_API_KEY_ENV``      name of the env-var that holds the API key
                                  (default: ``"OPENAI_API_KEY"``)
   =============================  =============================================

2. **models_config.yaml** ``embedding:`` section::

       embedding:
         provider: ollama
         model: nomic-embed-text
         base_url: http://localhost:11434

3. **Auto-detection** (no explicit config):

   * ``OPENAI_API_KEY`` is set in the environment → ``openai``
   * Otherwise → ``ollama`` at ``http://localhost:11434``

Provider notes
--------------
* **openai** — requires the ``openai`` package.  Works with any
  OpenAI-compatible endpoint (Azure, LM Studio, etc.) when ``base_url``
  is also set.
* **ollama** — calls ``POST <base_url>/api/embeddings`` (Ollama native API).
  Uses Python stdlib ``urllib`` only — **no extra packages required**.

Graceful degradation
--------------------
* No DB               → embed / upsert are no-ops; search returns ``[]``.
* Provider unavailable → ``embed_text`` returns ``None``; upsert skips.
* Any error           → logged at WARNING; no exception propagates.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_OPENAI_MODEL = "text-embedding-3-small"
_DEFAULT_OLLAMA_MODEL = "nomic-embed-text"
_DEFAULT_OLLAMA_URL   = "http://localhost:11434"
_MAX_CHARS            = 8_000   # truncate very long texts before embedding


# ---------------------------------------------------------------------------
# Embedding config (resolved once, then cached)
# ---------------------------------------------------------------------------

class _EmbeddingConfig:
    __slots__ = ("provider", "model", "base_url", "api_key_env")

    def __init__(
        self,
        provider: str,
        model: str,
        base_url: Optional[str],
        api_key_env: str,
    ) -> None:
        self.provider    = provider
        self.model       = model
        self.base_url    = base_url
        self.api_key_env = api_key_env

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"_EmbeddingConfig(provider={self.provider!r}, model={self.model!r}, "
            f"base_url={self.base_url!r})"
        )


_cfg_cache: Optional[_EmbeddingConfig] = None


def _resolve_config() -> _EmbeddingConfig:
    """Build the effective embedding config without using the cache."""
    provider    = os.environ.get("EMBEDDING_PROVIDER",    "").strip()
    model       = os.environ.get("EMBEDDING_MODEL",       "").strip()
    base_url    = os.environ.get("EMBEDDING_BASE_URL",    "").strip() or None
    api_key_env = os.environ.get("EMBEDDING_API_KEY_ENV", "").strip()

    # ── yaml fallback ────────────────────────────────────────────────────────
    if not provider:
        try:
            from pathlib import Path
            import yaml  # type: ignore[import]
            cfg_path = Path(__file__).parent.parent / "models_config.yaml"
            if cfg_path.exists():
                with open(cfg_path) as fh:
                    raw = yaml.safe_load(fh) or {}
                emb = raw.get("embedding") or {}
                provider    = provider    or str(emb.get("provider",    "")).strip()
                model       = model       or str(emb.get("model",       "")).strip()
                base_url    = base_url    or (str(emb.get("base_url",   "")).strip() or None)
                api_key_env = api_key_env or str(emb.get("api_key_env", "")).strip()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[VectorStore] could not read embedding section from yaml: %s", exc)

    # ── auto-detect ──────────────────────────────────────────────────────────
    if not provider:
        provider = "openai" if os.environ.get("OPENAI_API_KEY") else "ollama"

    # ── per-provider defaults ─────────────────────────────────────────────────
    if not model:
        model = _DEFAULT_OPENAI_MODEL if provider == "openai" else _DEFAULT_OLLAMA_MODEL
    if provider == "ollama" and not base_url:
        base_url = _DEFAULT_OLLAMA_URL
    if not api_key_env:
        api_key_env = "OPENAI_API_KEY"

    return _EmbeddingConfig(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
    )


def _get_config() -> _EmbeddingConfig:
    global _cfg_cache
    if _cfg_cache is None:
        _cfg_cache = _resolve_config()
    return _cfg_cache


def invalidate_embedding_config_cache() -> None:
    """Force config + singleton to be rebuilt on the next embed call.

    Call this after saving new embedding settings through the Settings UI
    (analogous to ``invalidate_model_cache`` in model_router).
    """
    global _cfg_cache, _instance
    _cfg_cache = None
    _instance  = None


# ---------------------------------------------------------------------------
# Provider back-ends
# ---------------------------------------------------------------------------

async def _embed_openai(
    text: str,
    model: str,
    api_key: str,
    base_url: Optional[str] = None,
) -> Optional[List[float]]:
    """Embed via the OpenAI (or OpenAI-compatible) Embeddings API.

    Parameters
    ----------
    text:     The text to embed (pre-truncated).
    model:    Model name, e.g. ``"text-embedding-3-small"``.
    api_key:  API key string.
    base_url: Optional base URL override for OpenAI-compatible endpoints
              (e.g. ``"http://localhost:11434/v1"`` for Ollama OpenAI compat).
    """
    try:
        from openai import AsyncOpenAI  # type: ignore[import]
        kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = AsyncOpenAI(**kwargs)
        resp   = await client.embeddings.create(model=model, input=text)
        return resp.data[0].embedding
    except ImportError:
        logger.debug("[VectorStore] openai package not installed — cannot use OpenAI backend")
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[VectorStore] OpenAI embed failed: %s", exc)
        return None


async def _embed_ollama(
    text: str,
    model: str,
    base_url: str,
) -> Optional[List[float]]:
    """Embed via the Ollama native REST API.

    Endpoint: ``POST <base_url>/api/embeddings``
    Payload:  ``{"model": "<model>", "prompt": "<text>"}``

    Uses stdlib ``urllib`` only — **no extra packages required**.  The
    blocking HTTP call is run in an executor so it does not block the event
    loop.
    """
    import asyncio
    import json
    import urllib.error
    import urllib.request

    url     = f"{base_url.rstrip('/')}/api/embeddings"
    payload = json.dumps({"model": model, "prompt": text}).encode("utf-8")
    req     = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    def _sync() -> Optional[List[float]]:
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                return data.get("embedding")
        except urllib.error.URLError as exc:
            logger.warning("[VectorStore] Ollama unreachable at %s: %s", url, exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("[VectorStore] Ollama embed failed: %s", exc)
            return None

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync)


# ---------------------------------------------------------------------------
# Cosine similarity (pure Python)
# ---------------------------------------------------------------------------

def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Return the cosine similarity between two equal-length vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot   = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# VectorStore
# ---------------------------------------------------------------------------

class VectorStore:
    """Manage embeddings for solution documents stored in PostgreSQL.

    Configuration is resolved automatically from environment variables and
    ``models_config.yaml`` (see module docstring for the full priority order).

    Parameters
    ----------
    openai_api_key:
        *Legacy / testing only.* When provided (non-None string), forces the
        ``openai`` provider with this key, bypassing all config resolution.
    embed_model:
        *Legacy / testing only.* When provided, overrides the resolved model
        name regardless of config.
    """

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        embed_model: Optional[str] = None,
    ) -> None:
        # Legacy constructor params kept for backward compatibility with tests.
        # A non-None openai_api_key triggers the legacy OpenAI path directly.
        self._legacy_key   = openai_api_key
        self._legacy_model = embed_model

    # ── Embedding ────────────────────────────────────────────────────────

    async def embed_text(self, text: str) -> Optional[List[float]]:
        """Return an embedding vector for *text*, or ``None`` on any error.

        The provider, model, and credentials are resolved from configuration
        (see module docstring).  Input is truncated to ``_MAX_CHARS``
        characters before sending to the embedding endpoint.
        """
        truncated = text[:_MAX_CHARS]

        # ── Legacy path: explicit openai_api_key constructor arg ──────────────
        # (used by tests and callers that pre-date config-driven setup)
        if self._legacy_key is not None:
            model = self._legacy_model or _DEFAULT_OPENAI_MODEL
            return await _embed_openai(truncated, model, self._legacy_key)

        # ── Config-driven path ────────────────────────────────────────────────
        cfg = _get_config()

        if cfg.provider == "openai":
            api_key = os.environ.get(cfg.api_key_env)
            if not api_key:
                logger.debug(
                    "[VectorStore] env var '%s' not set — embeddings disabled",
                    cfg.api_key_env,
                )
                return None
            model = self._legacy_model or cfg.model
            return await _embed_openai(truncated, model, api_key, cfg.base_url)

        if cfg.provider == "ollama":
            model    = self._legacy_model or cfg.model
            base_url = cfg.base_url or _DEFAULT_OLLAMA_URL
            return await _embed_ollama(truncated, model, base_url)

        logger.warning("[VectorStore] Unknown embedding provider '%s'", cfg.provider)
        return None

    # ── Persistence ───────────────────────────────────────────────────────

    async def upsert(
        self,
        solution_id: str,
        text: str,
        *,
        workspace_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Embed *text* and write / update the embedding in the DB.

        Returns ``True`` on success, ``False`` on any failure.

        The ``solutions`` table row must already exist (inserted by
        ``db.repository.upsert_solution``); this method only updates the
        ``embedding`` column.
        """
        try:
            from db.connection import get_session, is_db_available  # noqa: F401
            if not is_db_available():
                return False
        except ImportError:
            return False

        embedding = await self.embed_text(text)
        if embedding is None:
            return False

        try:
            from db.connection import get_session
            from sqlalchemy import text as sql_text

            async with get_session() as session:
                await session.execute(
                    sql_text(
                        "UPDATE solutions SET embedding = :emb WHERE id = :sid"
                    ),
                    {"emb": embedding, "sid": solution_id},
                )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[VectorStore] upsert failed for %s: %s", solution_id, exc)
            return False

    # ── Search ───────────────────────────────────────────────────────────

    async def search_similar(
        self,
        query: str,
        *,
        top_k: int = 5,
        min_score: float = 0.0,
        workspace_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return the *top_k* most similar solution documents for *query*.

        Results are dicts with keys: ``id``, ``problem``, ``solution``,
        ``score``, ``workspace_id``, ``type``.

        Returns an empty list when DB is unavailable or on any error.
        """
        query_vec = await self.embed_text(query)
        if query_vec is None:
            return []

        try:
            from db.connection import get_session, is_db_available
            if not is_db_available():
                return []

            from sqlalchemy import text as sql_text

            where_clause = "WHERE embedding IS NOT NULL"
            params: Dict[str, Any] = {}
            if workspace_id:
                where_clause += " AND workspace_id = :ws_id"
                params["ws_id"] = workspace_id

            async with get_session() as session:
                rows = (await session.execute(
                    sql_text(
                        f"SELECT id, problem, solution, type, workspace_id, embedding "
                        f"FROM solutions {where_clause}"
                    ),
                    params,
                )).fetchall()

        except Exception as exc:  # noqa: BLE001
            logger.warning("[VectorStore] search_similar DB query failed: %s", exc)
            return []

        scored: List[Dict[str, Any]] = []
        for row in rows:
            emb = row.embedding
            if not emb or not isinstance(emb, list):
                continue
            score = _cosine_similarity(query_vec, emb)
            if score < min_score:
                continue
            scored.append({
                "id":           row.id,
                "problem":      row.problem,
                "solution":     row.solution,
                "type":         row.type,
                "workspace_id": row.workspace_id,
                "score":        round(score, 4),
            })

        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[:top_k]


# ---------------------------------------------------------------------------
# Module-level singleton (lazy-initialised)
# ---------------------------------------------------------------------------

_instance: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """Return the module-level VectorStore singleton."""
    global _instance
    if _instance is None:
        _instance = VectorStore()
    return _instance
