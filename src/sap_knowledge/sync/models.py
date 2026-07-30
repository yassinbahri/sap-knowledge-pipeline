"""Portable synchronization events and state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from sap_knowledge.knowledge.models import Citation, KnowledgeChunk


class UpsertEvent(BaseModel):
    """Replace all indexed chunks belonging to one current source entity."""

    model_config = ConfigDict(frozen=True)

    operation: Literal["upsert"] = "upsert"
    document_id: str
    chunks: tuple[KnowledgeChunk, ...] = Field(min_length=1)
    citation: Citation


class DeleteEvent(BaseModel):
    """Remove all indexed chunks belonging to one deleted source entity."""

    model_config = ConfigDict(frozen=True)

    operation: Literal["delete"] = "delete"
    document_id: str
    citation: Citation
    reason: str | None = None


SyncEvent: TypeAlias = UpsertEvent | DeleteEvent


class SyncCheckpoint(BaseModel):
    """The next safe server cursor for one uniquely configured pipeline."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    pipeline_id: str
    cursor: str | None = None
    delta_url: str | None = None
    complete: bool = False
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SyncResult(BaseModel):
    """Counts and final state from one pipeline invocation."""

    model_config = ConfigDict(frozen=True)

    pages: int = 0
    upserts: int = 0
    chunks: int = 0
    deletions: int = 0
    already_complete: bool = False
    checkpoint: SyncCheckpoint | None = None
