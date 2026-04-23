"""SQLAlchemy ORM models.

Tables
------
jobs         — job metadata + status
events       — SSE event log (append-only)
checkpoints  — pipeline phase checkpoints (upsert)
solutions    — workspace-scoped lessons (SolutionStore backing)
settings     — global key/JSONB settings store
"""

from sqlalchemy import Column, Integer, String, Text, JSON
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class JobModel(Base):
    __tablename__ = "jobs"

    id           = Column(String(8),   primary_key=True)
    type         = Column(String(50),  nullable=False)
    workspace_id = Column(String(255), nullable=False)
    requirement  = Column(Text,        nullable=False)
    status       = Column(String(50),  nullable=False, default="pending")
    created_at   = Column(String(50),  nullable=False)
    updated_at   = Column(String(50))
    meta         = Column(JSON,        default=dict)


class EventModel(Base):
    __tablename__ = "events"

    id        = Column(Integer,      primary_key=True, autoincrement=True)
    job_id    = Column(String(8),    nullable=False, index=True)
    seq       = Column(Integer,      nullable=False)
    type      = Column(String(100),  nullable=False)
    label     = Column(Text)
    data      = Column(JSON,         default=dict)
    timestamp = Column(String(50),   nullable=False)


class CheckpointModel(Base):
    __tablename__ = "checkpoints"

    job_id               = Column(String(8),  primary_key=True)
    phase                = Column(String(50), nullable=False)
    completed_tasks      = Column(JSON,       default=list)   # List[str]
    current_task_index   = Column(Integer,    default=0)
    data                 = Column(JSON,       default=dict)   # arbitrary phase data
    updated_at           = Column(String(50), nullable=False)


class SolutionModel(Base):
    __tablename__ = "solutions"

    id           = Column(String(8),   primary_key=True)
    workspace_id = Column(String(255), nullable=False, index=True)
    type         = Column(String(50))
    problem      = Column(Text,        nullable=False)
    solution     = Column(Text,        nullable=False)
    context      = Column(Text)
    tags         = Column(JSON,        default=list)
    job_id       = Column(String(50))
    timestamp    = Column(String(50))
    # Embedding stored as a JSON array of 1536 floats (text-embedding-3-small).
    # Added in Week 4 (M1 pgvector phase) via migration 002_add_embedding_column.
    embedding    = Column(JSON,        nullable=True)


class SettingModel(Base):
    __tablename__ = "settings"

    key        = Column(String(255), primary_key=True)
    value      = Column(JSON,        nullable=False)
    updated_at = Column(String(50),  nullable=False)
