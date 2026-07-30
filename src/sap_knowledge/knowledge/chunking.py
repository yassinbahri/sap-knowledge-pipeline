"""Deterministic, dependency-free text chunking."""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sap_knowledge.knowledge.models import KnowledgeChunk, KnowledgeDocument


class CharacterChunker(BaseModel):
    """Split documents at whitespace with a bounded character overlap."""

    model_config = ConfigDict(frozen=True)

    max_characters: int = Field(default=1200, ge=64)
    overlap_characters: int = Field(default=120, ge=0)

    @model_validator(mode="after")
    def validate_overlap(self) -> CharacterChunker:
        if self.overlap_characters >= self.max_characters:
            raise ValueError("overlap_characters must be smaller than max_characters")
        return self

    def split(self, document: KnowledgeDocument) -> tuple[KnowledgeChunk, ...]:
        text = document.text.strip()
        if not text:
            return ()

        fragments: list[str] = []
        start = 0
        while start < len(text):
            hard_end = min(start + self.max_characters, len(text))
            end = hard_end
            if hard_end < len(text):
                whitespace = text.rfind(" ", start, hard_end + 1)
                newline = text.rfind("\n", start, hard_end + 1)
                boundary = max(whitespace, newline)
                if boundary > start:
                    end = boundary

            fragment = text[start:end].strip()
            if fragment:
                fragments.append(fragment)
            if end >= len(text):
                break

            next_start = max(0, end - self.overlap_characters)
            if next_start <= start:
                next_start = end
            elif self.overlap_characters:
                boundary = text.find(" ", next_start, end)
                if boundary != -1:
                    next_start = boundary + 1
            start = next_start

        chunks: list[KnowledgeChunk] = []
        for ordinal, fragment in enumerate(fragments):
            fingerprint = hashlib.sha256(
                f"{document.id}\0{ordinal}\0{fragment}".encode()
            ).hexdigest()[:20]
            chunks.append(
                KnowledgeChunk(
                    id=f"{document.id}:chunk:{fingerprint}",
                    document_id=document.id,
                    ordinal=ordinal,
                    text=fragment,
                    citation=document.citation,
                    metadata={**document.metadata, "chunk_ordinal": ordinal},
                )
            )
        return tuple(chunks)
