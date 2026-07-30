"""Provider-neutral knowledge and provenance models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Citation(BaseModel):
    """Structured provenance needed to trace generated knowledge to SAP."""

    model_config = ConfigDict(frozen=True)

    source_type: str = "odata"
    entity_set: str
    key: dict[str, Any]
    source_url: str | None = None
    etag: str | None = None


class KnowledgeDocument(BaseModel):
    """One allow-listed, human-readable representation of a source entity."""

    model_config = ConfigDict(frozen=True)

    id: str
    recipe: str
    title: str
    text: str
    citation: Citation
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeChunk(BaseModel):
    """A deterministic document fragment ready for embedding or export."""

    model_config = ConfigDict(frozen=True)

    id: str
    document_id: str
    ordinal: int = Field(ge=0)
    text: str
    citation: Citation
    metadata: dict[str, Any] = Field(default_factory=dict)
