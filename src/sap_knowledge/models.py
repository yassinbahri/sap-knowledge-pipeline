"""Canonical records emitted by data sources."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceRecord(BaseModel):
    """One current entity returned by a source."""

    model_config = ConfigDict(frozen=True)

    entity_set: str
    key: dict[str, Any]
    data: dict[str, Any]
    etag: str | None = None


class SourceDeletion(BaseModel):
    """A source entity that was deleted or left the tracked result set."""

    model_config = ConfigDict(frozen=True)

    entity_set: str
    key: dict[str, Any]
    reason: str | None = None


class SourcePage(BaseModel):
    """One page of source changes plus its opaque continuation state."""

    model_config = ConfigDict(frozen=True)

    records: tuple[SourceRecord, ...] = Field(default_factory=tuple)
    deletions: tuple[SourceDeletion, ...] = Field(default_factory=tuple)
    next_url: str | None = None
    delta_url: str | None = None
