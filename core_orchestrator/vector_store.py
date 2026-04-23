"""Semantic vector store for solution documents.

Generates text embeddings via the OpenAI Embeddings API
(model ``text-embedding-3-small``, 1536 dimensions) and persists them in
the ``solutions.embedding`` column (JSONB array in PostgreSQL).

Similarity search loads all stored vectors and ranks them by cosine
similarity in Python — fast enough for collections up to ~50 k entries
and requires no pgvector extension.

Graceful degradation
--------------------
* No ``DATABASE_URL``   → embed / upsert are no-ops; search returns [].
* No ``OPENAI_API_KEY`` → embed returns ``None``; upsert skips DB write.
* OpenAI API error      → logged, no exception raised.
* DB error              → logged, no exception raised.

All public methods are ``async`` so they fit naturally into the FastAPI
lifespan context.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_EMBED_MODEL = "text-embedding-3-small"
_EMBED_DIMS  = 1536
_MAX_CHARS   = 8_000   # truncate very long texts before embedding


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

    Parameters
    ----------
    openai_api_key:
        Explicit key override.  When ``None`` the key is read from the
        ``OPENAI_API_KEY`` environment variable at call time.
    embed_model:
        OpenAI embedding model name.  Default: ``text-embedding-3-small``.
    """

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        embed_model: str = _EMBED_MODEL,
    ) -> None:
        self._api_key    = openai_api_key   # None → read from env at call time
        self._model      = embed_model

    # ── Embedding ────────────────────────────────────────────────────────

    async def embed_text(self, text: str) -> Optional[List[float]]:
        """Return a 1536-dimensional embedding for *text*, or ``None`` on any error.

        Truncates input to ``_MAX_CHARS`` characters before sending.
        """
        try:
            import os
            from openai import AsyncOpenAI, APIError

            api_key = self._api_key or os.environ.get("OPENAI_API_KEY")
            if not api_key:
                return None

            client = AsyncOpenAI(api_key=api_key)
            truncated = text[:_MAX_CHARS]
            resp = await client.embeddings.create(
                model=self._model,
                input=truncated,
            )
            return resp.data[0].embedding

        except ImportError:
            logger.debug("[VectorStore] openai not installed — embeddings disabled")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("[VectorStore] embed_text failed: %s", exc)
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
            from db.connection import get_session, is_db_available
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
                        "UPDATE solutions SET embedding = :emb "
                        "WHERE id = :sid"
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
