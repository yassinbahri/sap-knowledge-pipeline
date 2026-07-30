"""Local ONNX text embeddings through the optional FastEmbed dependency."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sap_knowledge.errors import OptionalDependencyError, VectorIndexError


def _float_vector(vector: Any) -> list[float]:
    return [float(value) for value in vector]


class FastEmbedder:
    """Generate passage and query embeddings locally on CPU."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        *,
        cache_dir: str | None = None,
    ) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise OptionalDependencyError(
                "FastEmbed is not installed; use `pip install sap-knowledge-pipeline[fastembed]`"
            ) from exc

        kwargs: dict[str, Any] = {"model_name": model_name}
        if cache_dir is not None:
            kwargs["cache_dir"] = cache_dir
        self.model_name = model_name
        self._model = TextEmbedding(**kwargs)
        probe = list(self._model.query_embed("embedding dimension probe"))
        if len(probe) != 1:
            raise VectorIndexError("embedding model did not return one probe vector")
        self._dimension = len(probe[0])

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_id(self) -> str:
        return f"fastembed:{self.model_name}"

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [_float_vector(vector) for vector in self._model.passage_embed(list(texts))]

    def embed_query(self, text: str) -> list[float]:
        vectors = list(self._model.query_embed(text))
        if len(vectors) != 1:
            raise VectorIndexError("embedding model did not return one query vector")
        return _float_vector(vectors[0])
