"""Knowledge graph document upload and query endpoints.

POST /knowledge/upload
    Accepts a PDF or TXT file (multipart/form-data).
    Returns 202 immediately with {node_id, filename, status: "processing"}.
    A FastAPI BackgroundTask runs the full ingestion pipeline:
      parse → LLM-markdown → LLM-concepts → graph persist → embed.

GET /knowledge/nodes
    List nodes belonging to the current tenant (paginated).

GET /knowledge/nodes/{node_id}
    Fetch a single node by ID.
"""

import asyncio
import json
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile

from ..deps import CurrentUser, require_active
from ..models import (
    EdgeOut,
    GraphOut,
    KnowledgeChatReply,
    KnowledgeChatRequest,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSearchHit,
    NodeOut,
    UploadOut,
    WebSearchRequest,
    WebSearchResponse,
    WebSearchHit,
    WebSaveRequest,
    WebSaveResponse,
)
from ..rate_limit import limiter

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

_SUPPORTED_SUFFIXES = {".pdf", ".txt"}
_MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MB guard

# Chinese-aware search tokeniser — compiled once at import time
_ZH_STOP_WORDS = re.compile(
    r"(什么|是|有|哪些|哪个|的|了|吗|呢|如何|怎么|为什么|这个|那个|这些|那些"
    r"|请问|告诉我|介绍|讲解|解释|我想知道|帮我)"
)


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@router.post("/upload", response_model=UploadOut, status_code=202)
@limiter.limit("20/minute")
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    workspace_id: str = Form("default"),
    current_user: CurrentUser = Depends(require_active),
):
    """Upload a PDF or TXT file for knowledge graph ingestion.

    Returns 202 immediately.  The document is parsed, summarised, and
    embedded in the background — poll GET /knowledge/nodes/{node_id} to
    check when ``ingest_status`` flips to ``"completed"``.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{suffix}'. Supported: {sorted(_SUPPORTED_SUFFIXES)}",
        )

    file_bytes = await file.read()
    if len(file_bytes) > _MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(file_bytes):,} bytes). Maximum is {_MAX_FILE_BYTES:,} bytes.",
        )
    if not file_bytes:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    node_id = str(uuid.uuid4())
    tenant_id = str(current_user.tenant_id)

    from core_orchestrator.knowledge_ingestion import run_ingestion
    background_tasks.add_task(
        run_ingestion,
        file_bytes=file_bytes,
        filename=file.filename or "upload",
        node_id=node_id,
        tenant_id=tenant_id,
    )

    return UploadOut(
        node_id=node_id,
        filename=file.filename or "upload",
        status="processing",
        message="File accepted. Ingestion running in background.",
    )


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

@router.get("/nodes", response_model=list[NodeOut])
async def list_nodes(
    node_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    current_user: CurrentUser = Depends(require_active),
):
    """List knowledge graph nodes for the current tenant."""
    from db.connection import get_session, is_db_available
    from db.models import NodeModel
    from sqlalchemy import select

    if not is_db_available():
        raise HTTPException(503, detail="Database not available.")

    tenant_id = str(current_user.tenant_id)
    async with get_session() as session:
        q = select(NodeModel).where(NodeModel.tenant_id == tenant_id)
        if node_type:
            q = q.where(NodeModel.node_type == node_type)
        q = q.order_by(NodeModel.created_at.desc()).limit(min(limit, 200)).offset(offset)
        rows = (await session.execute(q)).scalars().all()

    return [_node_to_out(r) for r in rows]


@router.get("/nodes/{node_id}", response_model=NodeOut)
async def get_node(
    node_id: str,
    current_user: CurrentUser = Depends(require_active),
):
    """Fetch a single knowledge graph node by ID."""
    from db.connection import get_session, is_db_available
    from db.models import NodeModel
    from sqlalchemy import select

    if not is_db_available():
        raise HTTPException(503, detail="Database not available.")

    tenant_id = str(current_user.tenant_id)
    async with get_session() as session:
        row = (await session.execute(
            select(NodeModel).where(
                NodeModel.id == node_id,
                NodeModel.tenant_id == tenant_id,
            )
        )).scalar_one_or_none()

    if row is None:
        raise HTTPException(404, detail="Node not found.")
    return _node_to_out(row)


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_node(
    node_id: str,
    current_user: CurrentUser = Depends(require_active),
):
    """Delete a knowledge graph node and all its incident edges (in/out).

    Tenant-scoped — a user can only delete nodes belonging to their tenant.
    Returns 204 No Content on success, 404 if the node doesn't exist.
    """
    from db.connection import get_session, is_db_available
    from db.models import EdgeModel, NodeModel
    from sqlalchemy import delete, or_, select

    if not is_db_available():
        raise HTTPException(503, detail="Database not available.")

    tenant_id = str(current_user.tenant_id)
    async with get_session() as session:
        # 1. Verify node exists & belongs to this tenant
        row = (await session.execute(
            select(NodeModel.id).where(
                NodeModel.id == node_id,
                NodeModel.tenant_id == tenant_id,
            )
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(404, detail="Node not found.")

        # 2. Delete edges where this node is source OR target (also tenant-scoped)
        await session.execute(
            delete(EdgeModel).where(
                EdgeModel.tenant_id == tenant_id,
                or_(
                    EdgeModel.source_node_id == node_id,
                    EdgeModel.target_node_id == node_id,
                ),
            )
        )

        # 3. Delete the node itself
        await session.execute(
            delete(NodeModel).where(
                NodeModel.id == node_id,
                NodeModel.tenant_id == tenant_id,
            )
        )
        await session.commit()
    return None


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Graph (nodes + edges for visualisation)
# ---------------------------------------------------------------------------

@router.get("/graph", response_model=GraphOut)
async def get_graph(current_user: CurrentUser = Depends(require_active)):
    """Return all nodes and edges for the current tenant — used by the force-graph."""
    from db.connection import get_session, is_db_available
    from db.models import EdgeModel, NodeModel
    from sqlalchemy import select

    if not is_db_available():
        raise HTTPException(503, detail="Database not available.")

    tenant_id = str(current_user.tenant_id)
    async with get_session() as session:
        nodes = (await session.execute(
            select(NodeModel).where(NodeModel.tenant_id == tenant_id)
        )).scalars().all()

        edges = (await session.execute(
            select(EdgeModel).where(EdgeModel.tenant_id == tenant_id)
        )).scalars().all()

    return GraphOut(
        nodes=[_node_to_out(n) for n in nodes],
        links=[
            EdgeOut(
                id=e.id,
                tenant_id=e.tenant_id,
                source=e.source_node_id,
                target=e.target_node_id,
                relationship_type=e.relationship_type,
                weight=float(e.weight),
            )
            for e in edges
        ],
    )


# ---------------------------------------------------------------------------
# Knowledge-graph–grounded chat
# ---------------------------------------------------------------------------

_CHAT_SYSTEM = """\
You are a precise knowledge assistant. Answer the user's question using ONLY the \
context below. If the answer cannot be found in the context, say so clearly.
Respond in the same language as the user's question.

=== KNOWLEDGE CONTEXT ===
{context}
=== END CONTEXT ==="""

_MAX_CONTEXT_CHARS = 12_000


def _build_context(nodes_content: list[tuple[str, str]]) -> str:
    """Format (title, content) pairs into a compact context block."""
    parts = []
    total = 0
    for title, content in nodes_content:
        snippet = f"[{title}]\n{content or title}"
        if total + len(snippet) > _MAX_CONTEXT_CHARS:
            break
        parts.append(snippet)
        total += len(snippet)
    return "\n\n---\n\n".join(parts) if parts else "(no context selected)"


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search_nodes(
    req: KnowledgeSearchRequest,
    current_user: CurrentUser = Depends(require_active),
):
    """Keyword search across node titles and content for the current tenant.

    Works for both Latin and Chinese text.  For Chinese queries the tokeniser
    strips common question/function words and generates character n-grams so
    that "什么是机器学习" correctly matches a node titled "机器学习".

    Nodes are re-ranked by token-hit count (title=2 pts, content=1 pt).
    Returns up to ``req.limit`` hits ordered by relevance score descending.
    """
    from db.connection import get_session, is_db_available
    from db.models import NodeModel
    from sqlalchemy import or_, select

    if not is_db_available():
        return KnowledgeSearchResponse(hits=[])

    tenant_id = str(current_user.tenant_id)
    query = req.query.strip()
    if not query:
        return KnowledgeSearchResponse(hits=[])

    # Chinese-aware tokenisation:
    # 1. Remove question/function words (什么/是/如何…) → clean noun phrase(s).
    # 2. Split on whitespace/punctuation to get phrase tokens.
    # 3. Generate CJK trigrams + bigrams so embedded terms like "机器学习"
    #    are matched even when buried inside a longer query string.
    cleaned = _ZH_STOP_WORDS.sub(" ", query)

    # Whitespace/punctuation split
    phrase_tokens = [t for t in re.split(r"[\s，,。.!！?？、：:；;]+", cleaned) if len(t) >= 2]

    # Character trigrams from cleaned query (captures embedded terms)
    cjk_chars = re.sub(r"[^一-鿿㐀-䶿]", "", cleaned)
    trigrams = [cjk_chars[i:i+3] for i in range(len(cjk_chars) - 2)] if len(cjk_chars) >= 3 else []
    bigrams  = [cjk_chars[i:i+2] for i in range(len(cjk_chars) - 1)] if len(cjk_chars) >= 2 else []

    # Merge: phrase tokens first (higher recall), then n-grams, then original
    seen: set[str] = set()
    tokens: list[str] = []
    for tok in phrase_tokens + trigrams + bigrams + [query]:
        if len(tok) >= 2 and tok not in seen:
            seen.add(tok)
            tokens.append(tok)
    if not tokens:
        tokens = [query]

    async with get_session() as session:
        # Build OR filter: any token matches title OR content
        filters = []
        for tok in tokens:
            filters.append(NodeModel.title.ilike(f"%{tok}%"))
            filters.append(NodeModel.content.ilike(f"%{tok}%"))

        rows = (await session.execute(
            select(NodeModel)
            .where(NodeModel.tenant_id == tenant_id, or_(*filters))
            .limit(min(req.limit * 4, 80))   # fetch extra for re-ranking
        )).scalars().all()

    # Re-rank by token hit count (title matches count double)
    def _score(node: NodeModel) -> int:
        title_low = (node.title or "").lower()
        content_low = (node.content or "").lower()
        return sum(
            (2 if tok.lower() in title_low else 0) +
            (1 if tok.lower() in content_low else 0)
            for tok in tokens
        )

    ranked = sorted(rows, key=_score, reverse=True)[: req.limit]

    hits = [
        KnowledgeSearchHit(
            node_id=n.id,
            title=n.title,
            node_type=n.node_type,
            snippet=(n.content or "")[:120].replace("\n", " "),
        )
        for n in ranked
    ]
    return KnowledgeSearchResponse(hits=hits)


def _call_llm_sync(prompt: str) -> str:
    from pathlib import Path as _Path
    from core_orchestrator.model_router import ModelRouter
    _root = _Path(__file__).parent.parent.parent
    router = ModelRouter(_root / "models_config.yaml")
    preferred = router.resolve(agent="architect")
    return router.call_with_failover(preferred, prompt)


@router.post("/chat", response_model=KnowledgeChatReply)
async def knowledge_chat(
    req: KnowledgeChatRequest,
    current_user: CurrentUser = Depends(require_active),
):
    """Direct LLM Q&A grounded in selected knowledge-graph nodes.

    Accepts conversation history so multi-turn exchanges work correctly.
    All blocking LLM work runs in a thread (asyncio.to_thread) to avoid
    stalling the event loop.
    """
    from db.connection import get_session, is_db_available
    from db.models import NodeModel
    from sqlalchemy import select

    # ── 1. Fetch context from selected nodes ──────────────────────────────
    context_text = "(no context — select nodes in the graph)"
    if req.context_node_ids and is_db_available():
        tenant_id = str(current_user.tenant_id)
        async with get_session() as session:
            rows = (await session.execute(
                select(NodeModel).where(
                    NodeModel.id.in_(req.context_node_ids),
                    NodeModel.tenant_id == tenant_id,
                )
            )).scalars().all()
        context_text = _build_context([(r.title, r.content or "") for r in rows])

    # ── 2. Build full prompt (system + history + current message) ─────────
    system_block = _CHAT_SYSTEM.format(context=context_text)
    history_block = ""
    for turn in req.history[-6:]:   # keep last 6 turns to stay within token budget
        label = "User" if turn.role == "user" else "Assistant"
        history_block += f"\n{label}: {turn.content}"

    full_prompt = (
        f"{system_block}\n\n"
        f"{history_block}\n"
        f"User: {req.message}\n"
        f"Assistant:"
    )

    # ── 3. Call LLM in thread (sync call, non-blocking) ───────────────────
    try:
        reply = await asyncio.to_thread(_call_llm_sync, full_prompt)
    except Exception as exc:
        raise HTTPException(502, detail=f"LLM call failed: {exc}") from exc

    return KnowledgeChatReply(reply=reply.strip())


def _node_to_out(row) -> NodeOut:
    return NodeOut(
        id=row.id,
        tenant_id=row.tenant_id,
        node_type=row.node_type,
        title=row.title,
        content=row.content,
        node_metadata=row.node_metadata or {},
        content_hash=row.content_hash,
        created_at=row.created_at,
        updated_at=row.updated_at,
        has_embedding=row.embedding is not None,
    )


# ---------------------------------------------------------------------------
# Web search & save (turn external pages into graph nodes)
# ---------------------------------------------------------------------------

@router.post("/web_search", response_model=WebSearchResponse)
@limiter.limit("20/minute")
async def web_search(
    request: Request,
    req: WebSearchRequest,
    current_user: CurrentUser = Depends(require_active),
):
    """Search the open web (Bing/Sogou via Playwright) and return top hits.

    Hits are NOT persisted — call ``/web_save`` per result the user wants
    saved into the knowledge graph.  Runs the (blocking, browser-driven)
    ``search_web`` in a thread so the event loop stays responsive.
    """
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(422, detail="query is empty")

    limit = max(1, min(req.limit, 10))

    import logging
    log = logging.getLogger(__name__)

    def _do_search() -> list[dict]:
        from core_orchestrator.web_browser import search_web
        raw = search_web(query, engine=req.engine, num_results=limit)
        data = json.loads(raw)
        return data.get("results", [])

    try:
        results = await asyncio.wait_for(asyncio.to_thread(_do_search), timeout=60.0)
    except asyncio.TimeoutError as exc:
        raise HTTPException(504, detail="Web search timed out (60s)") from exc
    except Exception as exc:
        log.exception("[web_search] failed for query=%r", query)
        # retryable=False means a structural/config error → 400 Bad Request
        from core_orchestrator.web_browser import WebBrowserError
        if isinstance(exc, WebBrowserError) and not exc.retryable:
            raise HTTPException(400, detail=str(exc)) from exc
        raise HTTPException(502, detail=f"Web search failed: {type(exc).__name__}: {exc}") from exc

    hits = [
        WebSearchHit(
            title=(r.get("title") or "")[:300],
            url=r.get("url") or "",
            snippet=(r.get("snippet") or r.get("description") or "")[:500],
        )
        for r in results
        if r.get("url")
    ]
    return WebSearchResponse(hits=hits)


@router.post("/web_save", response_model=WebSaveResponse, status_code=201)
@limiter.limit("30/minute")
async def web_save(
    request: Request,
    req: WebSaveRequest,
    current_user: CurrentUser = Depends(require_active),
):
    """Convert one web search result into a `web` node in the knowledge graph.

    Stores ``title`` + ``snippet`` immediately (fast).  The original URL is
    saved in ``node_metadata.url`` so the frontend can deep-link back.

    Deduplicates by SHA-256(tenant_id + url) — calling this with the same URL
    twice returns the existing node rather than creating a duplicate.
    """
    from db.connection import get_session, is_db_available
    from db.models import NodeModel
    from db.repository import upsert_node, get_node_by_hash
    from datetime import datetime, timezone
    import hashlib
    import uuid

    if not is_db_available():
        raise HTTPException(503, detail="Database not available.")

    url = (req.url or "").strip()
    title = (req.title or "").strip() or url
    if not url.startswith(("http://", "https://")):
        raise HTTPException(422, detail="url must be absolute (http:// or https://)")

    tenant_id = str(current_user.tenant_id)
    content_hash = hashlib.sha256(f"{tenant_id}:web:{url}".encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()

    async with get_session() as session:
        existing = await get_node_by_hash(session, tenant_id, content_hash)
        if existing:
            return WebSaveResponse(node_id=existing.id, title=existing.title, url=url)

        node_id = str(uuid.uuid4())
        await upsert_node(session, {
            "id": node_id,
            "tenant_id": tenant_id,
            "node_type": "web",
            "title": title[:500],
            "content": req.snippet or "",
            "metadata": {
                "url": url,
                "source": "web_search",
                "query": req.query or "",
            },
            "content_hash": content_hash,
            "created_at": now,
            "updated_at": now,
        })

    return WebSaveResponse(node_id=node_id, title=title, url=url)
