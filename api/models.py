"""Pydantic models for the API layer."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class JobCreate(BaseModel):
    type: str = "build"          # "build" | "update"
    workspace_id: str = "default"
    requirement: str


class AnswerRequest(BaseModel):
    answer: str


class ApprovalRequest(BaseModel):
    approved: bool
    note: str = ""


class JobOut(BaseModel):
    id: str
    type: str
    workspace_id: str
    requirement: str
    status: str                  # pending|running|waiting_approval|completed|failed|rejected
    created_at: str
    event_count: int = 0
    pending_approval: Optional[Dict[str, Any]] = None
    pending_question: Optional[str] = None   # CEO interview: current unanswered question


# ---------------------------------------------------------------------------
# v2.0.0 — Knowledge Graph models
# ---------------------------------------------------------------------------

class UploadOut(BaseModel):
    node_id: str
    filename: str
    status: str       # "processing"
    message: str = ""


class NodeOut(BaseModel):
    id: str
    tenant_id: str
    node_type: str
    title: str
    content: Optional[str] = None
    node_metadata: Dict[str, Any] = {}
    content_hash: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None
    has_embedding: bool = False


class EdgeOut(BaseModel):
    id: int
    tenant_id: str
    source: str           # source_node_id (renamed for ForceGraph2D "links" convention)
    target: str           # target_node_id
    relationship_type: str
    weight: float = 1.0


class GraphOut(BaseModel):
    nodes: List[NodeOut]
    links: List[EdgeOut]  # ForceGraph2D expects "links", not "edges"


class KnowledgeChatMessage(BaseModel):
    role: str    # "user" | "assistant"
    content: str


class KnowledgeChatRequest(BaseModel):
    message: str
    context_node_ids: List[str] = []
    history: List[KnowledgeChatMessage] = []


class KnowledgeChatReply(BaseModel):
    reply: str


class KnowledgeSearchRequest(BaseModel):
    query: str
    limit: int = 5


class KnowledgeSearchHit(BaseModel):
    node_id: str
    title: str
    node_type: str
    snippet: str   # first 120 chars of content


class KnowledgeSearchResponse(BaseModel):
    hits: List[KnowledgeSearchHit]
