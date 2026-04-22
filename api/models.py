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
