"""Embedding provider protocol."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class TextEmbedder(Protocol):
    """Create compatible vectors for passages and retrieval queries."""

    @property
    def dimension(self) -> int: ...

    @property
    def model_id(self) -> str: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...
