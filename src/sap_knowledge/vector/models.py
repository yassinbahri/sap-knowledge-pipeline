"""Vector retrieval result models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sap_knowledge.knowledge.models import Citation


class SearchHit(BaseModel):
    """One scored knowledge chunk returned by a vector index."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    document_id: str
    text: str
    score: float
    citation: Citation
    metadata: dict[str, Any] = Field(default_factory=dict)
