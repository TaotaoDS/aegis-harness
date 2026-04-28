"""Multimodal content ingestion pipeline — Phase 2 of the AI Second Brain.

Flow
----
1. parse_document()  — extract raw text from PDF / TXT bytes.
2. _llm_to_markdown() — LLM cleans raw text into structured Markdown.
3. _llm_extract_concepts() — LLM extracts 5-10 core concept strings as JSON.
4. persist_graph()  — writes NodeModel (document) + NodeModel (concept) × N
                      + EdgeModel (document → concept) to PostgreSQL.
5. embed_all_nodes() — calls VectorStore.embed_text() for each node and writes
                       the resulting vector(1536) into nodes.embedding.

All blocking LLM calls are wrapped in asyncio.to_thread() so the async
ingestion coroutine never blocks the event loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_HARNESS_ROOT = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------

_MARKDOWN_PROMPT = """\
You are a precise document formatter.
Convert the following raw text into clean, well-structured Markdown.
Preserve all meaningful information. Use headings, bullet points, bold, \
code blocks, and tables where appropriate.
Return ONLY the Markdown — no preamble, no explanation.

===RAW TEXT===
{text}
===END==="""

_CONCEPTS_PROMPT = """\
Analyse the following document and extract between 5 and 10 core concepts, \
keywords, or topics that best represent the content.
Return ONLY a valid JSON array of short strings (1–4 words each).
Example: ["machine learning", "neural networks", "gradient descent"]

===DOCUMENT===
{markdown}
===END==="""

# Truncation guards (characters, not tokens)
_MAX_RAW_CHARS = 15_000   # fed to markdown prompt
_MAX_MD_CHARS  = 10_000   # fed to concept prompt

# ---------------------------------------------------------------------------
# Semantic auto-link thresholds
# ---------------------------------------------------------------------------
# Cosine similarity must exceed these values for an auto-link edge to be created.
# Higher = stricter (fewer but more confident connections).
_SIM_CONCEPT_CONCEPT = 0.82   # concept ↔ concept  (e.g. "NLP" ↔ "natural language processing")
_SIM_DOC_DOC         = 0.72   # document ↔ document (broad topical similarity)
_SIM_CROSS           = 0.75   # document ↔ concept  (doc is about this concept from another doc)
_MAX_NEIGHBORS       = 5      # max outgoing similarity edges per node (prevents hairball)


# ---------------------------------------------------------------------------
# File parsing
# ---------------------------------------------------------------------------

def parse_document(file_bytes: bytes, filename: str) -> str:
    """Return plain text extracted from a PDF or TXT file."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        try:
            import pypdf  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "pypdf is required for PDF parsing. "
                "Run: pip install pypdf>=4.0.0"
            ) from exc
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(p.strip() for p in pages if p.strip())

    if suffix == ".txt":
        return file_bytes.decode("utf-8", errors="replace")

    raise ValueError(f"Unsupported file type: '{suffix}'. Supported: .pdf, .txt")


# ---------------------------------------------------------------------------
# LLM helpers (sync — always called via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _build_router():
    """Instantiate a fresh ModelRouter (cheap — just YAML parse)."""
    from .model_router import ModelRouter
    return ModelRouter(_HARNESS_ROOT / "models_config.yaml")


def _llm_to_markdown(raw_text: str) -> str:
    router = _build_router()
    preferred = router.resolve(agent="architect")
    prompt = _MARKDOWN_PROMPT.format(text=raw_text[:_MAX_RAW_CHARS])
    return router.call_with_failover(preferred, prompt)


def _llm_extract_concepts(markdown: str) -> List[str]:
    router = _build_router()
    preferred = router.resolve(agent="architect")
    prompt = _CONCEPTS_PROMPT.format(markdown=markdown[:_MAX_MD_CHARS])
    raw = router.call_with_failover(preferred, prompt)
    return _parse_concepts(raw)


def _parse_concepts(raw: str) -> List[str]:
    """Extract a JSON array from a potentially noisy LLM response."""
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    if not match:
        logger.warning("[Ingestion] LLM returned no JSON array for concepts: %r", raw[:200])
        return []
    try:
        items = json.loads(match.group(0))
        return [str(c).strip() for c in items if str(c).strip()][:10]
    except json.JSONDecodeError:
        logger.warning("[Ingestion] Failed to parse concept JSON: %r", raw[:200])
        return []


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


async def _set_progress(
    node_id: str,
    tenant_id: str,
    status: str,
    pct: int,
    error: Optional[str] = None,
) -> None:
    """Update ingest_status / progress on the document node (best-effort)."""
    try:
        from db.connection import get_session, is_db_available
        from db.repository import update_node_metadata
        if not is_db_available():
            return
        patch: Dict[str, Any] = {"ingest_status": status, "progress": pct}
        if error:
            patch["error"] = error
        async with get_session() as session:
            await update_node_metadata(session, node_id, patch)
    except Exception as exc:
        logger.debug("[Ingestion] _set_progress failed silently: %s", exc)


async def _persist_graph(
    doc_node_id: str,
    tenant_id: str,
    filename: str,
    markdown: str,
    concepts: List[str],
) -> List[str]:
    """Update doc node with final content + upsert concept nodes + edges.

    Concept nodes are deduplicated by (tenant_id, title) — if a concept
    already exists for this tenant we reuse its ID instead of creating a
    duplicate node.

    Returns a list of all node IDs written (doc first, then concepts).
    """
    from db.connection import get_session
    from db.repository import get_node_by_hash, insert_edge, upsert_node

    now = _now()
    doc_hash = _sha256(markdown)
    concept_node_ids: List[str] = []

    doc_node: Dict[str, Any] = {
        "id": doc_node_id,
        "tenant_id": tenant_id,
        "node_type": "document",
        "title": Path(filename).stem,
        "content": markdown,
        "metadata": {"filename": filename, "ingest_status": "completed", "progress": 100},
        "content_hash": doc_hash,
        "created_at": now,
        "updated_at": now,
    }

    concept_nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    async with get_session() as session:
        for concept in concepts:
            c_hash = _sha256(f"{tenant_id}:concept:{concept}")
            existing = await get_node_by_hash(session, tenant_id, c_hash)
            if existing:
                # Reuse the existing concept node — just add a new edge
                cid = existing.id
            else:
                cid = str(uuid.uuid4())
                concept_nodes.append({
                    "id": cid,
                    "tenant_id": tenant_id,
                    "node_type": "concept",
                    "title": concept,
                    "content": concept,
                    "metadata": {"source_document_id": doc_node_id},
                    "content_hash": c_hash,
                    "created_at": now,
                })
            concept_node_ids.append(cid)
            edges.append({
                "tenant_id": tenant_id,
                "source_node_id": doc_node_id,
                "target_node_id": cid,
                "relationship_type": "contains_concept",
                "weight": 1.0,
                "created_at": now,
            })

        await upsert_node(session, doc_node)
        for cn in concept_nodes:
            await upsert_node(session, cn)
        for e in edges:
            await insert_edge(session, e)

    return [doc_node_id] + concept_node_ids


async def _embed_nodes(
    node_ids: List[str],
    texts: List[str],
) -> None:
    """Embed each text and write back to nodes.embedding."""
    from core_orchestrator.vector_store import get_vector_store
    from db.connection import get_session
    from db.repository import update_node_embedding

    vs = get_vector_store()
    for node_id, text in zip(node_ids, texts):
        try:
            embedding = await vs.embed_text(text)
            if embedding is None:
                logger.warning("[Ingestion] embed_text returned None for node %s", node_id)
                continue
            async with get_session() as session:
                await update_node_embedding(session, node_id, embedding)
        except Exception:
            logger.exception("[Ingestion] Embedding failed for node %s", node_id)


# ---------------------------------------------------------------------------
# Semantic similarity auto-linker
# ---------------------------------------------------------------------------

def _cosine_sim(a: List[float], b: List[float]) -> float:
    """Pure-Python cosine similarity (fallback when pgvector SQL is unavailable)."""
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def auto_link_by_similarity(
    node_ids: List[str],
    tenant_id: str,
) -> int:
    """Create cross-document similarity edges for the given nodes.

    For each node in ``node_ids``:
      1.  Fetches the node's embedding.
      2.  Queries pgvector (or falls back to Python cosine) for the top-K
          most similar nodes in the same tenant.
      3.  For pairs whose similarity exceeds the per-type threshold, creates
          a directed edge (skipping duplicates and self-loops).

    Edge types created:
      - ``related_concept``    — concept ↔ concept (threshold 0.82)
      - ``semantically_related`` — doc ↔ doc or doc ↔ concept (0.72 / 0.75)

    The ``weight`` column stores the cosine similarity score so the graph
    renderer can vary edge thickness by connection strength.

    Returns the number of new edges created.
    """
    from db.connection import get_session, is_db_available
    from db.models import NodeModel as _NodeModel
    from db.repository import (
        edge_exists,
        find_similar_nodes_pgvector,
        get_all_tenant_embeddings,
        insert_edge,
    )
    from sqlalchemy import select as sa_select

    if not is_db_available():
        return 0

    created  = 0
    now      = _now()

    # ── 1. Fetch embeddings for nodes we need to link ─────────────────────────
    async with get_session() as session:
        source_rows = (await session.execute(
            sa_select(
                _NodeModel.id,
                _NodeModel.node_type,
                _NodeModel.embedding,
            ).where(
                _NodeModel.id.in_(node_ids),
                _NodeModel.tenant_id == tenant_id,
                _NodeModel.embedding.is_not(None),
            )
        )).all()

    if not source_rows:
        logger.info("[AutoLink] No embeddings found for %d node(s) — skipping", len(node_ids))
        return 0

    # ── 2. Optionally pre-load all tenant embeddings for Python fallback ──────
    # We lazily load this only when pgvector returns empty (meaning the SQL cast
    # failed — i.e. pgvector extension not active, embeddings stored as JSON).
    _all_tenant_cache: Optional[List[tuple]] = None

    async def _get_candidates(session, node_id: str, emb: List[float]) -> List[tuple]:
        """Return (cand_id, cand_type, sim) list; uses pgvector first, Python fallback."""
        nonlocal _all_tenant_cache

        # Try pgvector ANN search
        candidates = await find_similar_nodes_pgvector(
            session, tenant_id, emb, exclude_id=node_id,
            limit=_MAX_NEIGHBORS * 3,
        )
        if candidates:
            return candidates

        # Fallback: load all embeddings once and compute in Python
        if _all_tenant_cache is None:
            _all_tenant_cache = await get_all_tenant_embeddings(session, tenant_id)

        scored = [
            (cid, ctype, _cosine_sim(emb, cemb))
            for cid, ctype, cemb in _all_tenant_cache
            if cid != node_id
        ]
        scored.sort(key=lambda x: x[2], reverse=True)
        return scored[: _MAX_NEIGHBORS * 3]

    # ── 3. For each source node, find neighbours and create edges ─────────────
    for src_row in source_rows:
        src_id   = src_row.id
        src_type = src_row.node_type
        emb      = src_row.embedding

        # Normalise embedding (pgvector might return a custom type)
        if not isinstance(emb, list):
            try:
                emb = list(emb)
            except Exception:
                continue

        edges_this_node = 0

        async with get_session() as session:
            candidates = await _get_candidates(session, src_id, emb)

            for cand_id, cand_type, sim in candidates:
                if edges_this_node >= _MAX_NEIGHBORS:
                    break

                # Determine threshold and relationship type
                if src_type == "concept" and cand_type == "concept":
                    threshold = _SIM_CONCEPT_CONCEPT
                    rel_type  = "related_concept"
                elif src_type == "document" and cand_type == "document":
                    threshold = _SIM_DOC_DOC
                    rel_type  = "semantically_related"
                else:
                    threshold = _SIM_CROSS
                    rel_type  = "semantically_related"

                if sim < threshold:
                    continue  # below threshold — skip

                # Skip if already connected in either direction
                if await edge_exists(session, src_id, cand_id, rel_type):
                    edges_this_node += 1  # count it as "handled"
                    continue
                if await edge_exists(session, cand_id, src_id, rel_type):
                    edges_this_node += 1
                    continue

                await insert_edge(session, {
                    "tenant_id":         tenant_id,
                    "source_node_id":    src_id,
                    "target_node_id":    cand_id,
                    "relationship_type": rel_type,
                    "weight":            round(sim, 4),
                    "metadata": {
                        "similarity":   round(sim, 4),
                        "auto_linked":  True,
                    },
                    "created_at": now,
                })
                edges_this_node += 1
                created += 1
                logger.debug(
                    "[AutoLink] %s(%s…) -[%s %.3f]-> %s(%s…)",
                    src_type, src_id[:8], rel_type, sim, cand_type, cand_id[:8],
                )

    logger.info(
        "[AutoLink] Created %d new similarity edges for %d source nodes",
        created, len(source_rows),
    )
    return created


async def relink_all_tenant_nodes(tenant_id: str) -> int:
    """Re-run auto-linking for every embedded node in the tenant.

    Useful after bulk uploads or to retroactively link existing content.
    Returns the total number of new edges created.
    """
    from db.connection import get_session, is_db_available
    from db.models import NodeModel as _NodeModel
    from sqlalchemy import select as sa_select

    if not is_db_available():
        return 0

    async with get_session() as session:
        ids = (await session.execute(
            sa_select(_NodeModel.id).where(
                _NodeModel.tenant_id == tenant_id,
                _NodeModel.embedding.is_not(None),
            )
        )).scalars().all()

    if not ids:
        return 0

    logger.info("[AutoLink] relink_all: %d nodes for tenant %s", len(ids), tenant_id[:8])
    return await auto_link_by_similarity(list(ids), tenant_id)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_ingestion(
    file_bytes: bytes,
    filename: str,
    node_id: str,
    tenant_id: str,
) -> None:
    """Full ingestion pipeline — designed to run as a FastAPI BackgroundTask.

    Stages (tracked in node.metadata):
      queued(0) → parsing(15) → extracting_content(35)
      → extracting_concepts(60) → building_graph(80)
      → embedding(90) → completed(100) | failed(-1)
    """
    logger.info("[Ingestion] Starting — file=%s node_id=%s", filename, node_id)

    # ── 0. Persist placeholder node immediately so the frontend can poll ─────
    now = _now()
    try:
        from db.connection import get_session, is_db_available
        from db.repository import upsert_node
        if is_db_available():
            async with get_session() as session:
                await upsert_node(session, {
                    "id": node_id,
                    "tenant_id": tenant_id,
                    "node_type": "document",
                    "title": Path(filename).stem,
                    "content": None,
                    "metadata": {
                        "filename": filename,
                        "ingest_status": "queued",
                        "progress": 0,
                    },
                    "content_hash": None,
                    "created_at": now,
                    "updated_at": now,
                })
    except Exception as exc:
        logger.warning("[Ingestion] Could not create placeholder node: %s", exc)

    try:
        # ── 1. Parse ──────────────────────────────────────────────────────────
        await _set_progress(node_id, tenant_id, "parsing", 15)
        raw_text = parse_document(file_bytes, filename)
        if not raw_text.strip():
            logger.warning("[Ingestion] Empty document after parse: %s", filename)
            await _set_progress(node_id, tenant_id, "failed", -1, "Empty document")
            return

        # ── 2. LLM: raw text → Markdown ──────────────────────────────────────
        # Hard upper bound (140s) so a stuck upstream call cannot hang the
        # background task forever.  Falls back to raw_text on timeout/failure.
        await _set_progress(node_id, tenant_id, "extracting_content", 35)
        logger.info("[Ingestion] Calling LLM to extract markdown (%d chars input)", len(raw_text))
        try:
            markdown = await asyncio.wait_for(
                asyncio.to_thread(_llm_to_markdown, raw_text),
                timeout=140.0,
            )
            logger.info("[Ingestion] Markdown extracted (%d chars)", len(markdown))
        except asyncio.TimeoutError:
            logger.warning("[Ingestion] LLM markdown step timed out — using raw text")
            markdown = raw_text[:_MAX_RAW_CHARS]
        except Exception as exc:
            logger.warning("[Ingestion] LLM markdown step failed (%s) — using raw text", exc)
            markdown = raw_text[:_MAX_RAW_CHARS]

        # ── 3. LLM: Markdown → concept list ──────────────────────────────────
        await _set_progress(node_id, tenant_id, "extracting_concepts", 60)
        logger.info("[Ingestion] Calling LLM to extract concepts")
        try:
            concepts = await asyncio.wait_for(
                asyncio.to_thread(_llm_extract_concepts, markdown),
                timeout=140.0,
            )
            logger.info("[Ingestion] Concepts extracted (%d): %s", len(concepts), concepts)
        except asyncio.TimeoutError:
            logger.warning("[Ingestion] LLM concept step timed out — no concepts")
            concepts = []
        except Exception as exc:
            logger.warning("[Ingestion] LLM concept step failed (%s) — no concepts", exc)
            concepts = []

        # ── 4. Persist graph ──────────────────────────────────────────────────
        await _set_progress(node_id, tenant_id, "building_graph", 80)
        all_node_ids = await _persist_graph(
            doc_node_id=node_id,
            tenant_id=tenant_id,
            filename=filename,
            markdown=markdown,
            concepts=concepts,
        )
        logger.info("[Ingestion] Graph persisted — %d nodes", len(all_node_ids))

        # ── 5. Embed all nodes ────────────────────────────────────────────────
        await _set_progress(node_id, tenant_id, "embedding", 90)
        embed_texts = [markdown] + concepts
        await _embed_nodes(all_node_ids, embed_texts)
        logger.info("[Ingestion] Embeddings written for %d nodes", len(all_node_ids))

        # ── 6. Auto-link: find semantic neighbours across the graph ───────────
        # Compare every newly-embedded node against all existing tenant nodes
        # via pgvector cosine similarity and create weighted similarity edges.
        # This step is non-fatal — a failure here does not mark the doc as failed.
        await _set_progress(node_id, tenant_id, "linking", 95)
        try:
            n_linked = await auto_link_by_similarity(all_node_ids, tenant_id)
            logger.info("[Ingestion] Auto-linked %d new similarity edges", n_linked)
        except Exception as exc:
            logger.warning("[Ingestion] Auto-link step failed (non-fatal): %s", exc)

        await _set_progress(node_id, tenant_id, "completed", 100)
        logger.info("[Ingestion] Completed — file=%s node_id=%s", filename, node_id)

    except Exception as exc:
        logger.exception("[Ingestion] Pipeline failed — file=%s node_id=%s", filename, node_id)
        await _set_progress(node_id, tenant_id, "failed", -1, str(exc))
