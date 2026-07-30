"""Qdrant sink and semantic retrieval adapter."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from typing import Any

from sap_knowledge.errors import OptionalDependencyError, VectorIndexError
from sap_knowledge.knowledge.models import Citation
from sap_knowledge.sync.models import DeleteEvent, SyncEvent, UpsertEvent
from sap_knowledge.vector import SearchHit, TextEmbedder


def _qdrant() -> tuple[Any, Any]:
    try:
        from qdrant_client import QdrantClient, models
    except ImportError as exc:
        raise OptionalDependencyError(
            "Qdrant is not installed; use `pip install sap-knowledge-pipeline[qdrant]`"
        ) from exc
    return QdrantClient, models


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"sap-knowledge:{chunk_id}"))


class QdrantKnowledgeIndex:
    """Consume sync events and query their chunks in Qdrant."""

    def __init__(
        self,
        *,
        client: Any,
        collection_name: str,
        embedder: TextEmbedder,
        batch_size: int = 128,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self.client = client
        self.collection_name = collection_name
        self.embedder = embedder
        self.batch_size = batch_size

    @classmethod
    def local(
        cls,
        *,
        path: str,
        collection_name: str,
        embedder: TextEmbedder,
        batch_size: int = 128,
    ) -> QdrantKnowledgeIndex:
        QdrantClient, _ = _qdrant()
        return cls(
            client=QdrantClient(path=path),
            collection_name=collection_name,
            embedder=embedder,
            batch_size=batch_size,
        )

    def _ensure_collection(self) -> None:
        _, models = _qdrant()
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.embedder.dimension,
                    distance=models.Distance.COSINE,
                ),
                metadata={
                    "sap_knowledge_embedding_model": self.embedder.model_id,
                    "sap_knowledge_vector_dimension": self.embedder.dimension,
                },
            )
            return

        configuration = self.client.get_collection(self.collection_name).config
        vectors = configuration.params.vectors
        actual_dimension = getattr(vectors, "size", None)
        if actual_dimension != self.embedder.dimension:
            raise VectorIndexError(
                f"collection vector size {actual_dimension!r} does not match "
                f"embedder dimension {self.embedder.dimension}"
            )
        metadata = configuration.metadata or {}
        actual_model = metadata.get("sap_knowledge_embedding_model")
        if actual_model != self.embedder.model_id:
            raise VectorIndexError(
                f"collection embedding model {actual_model!r} does not match "
                f"{self.embedder.model_id!r}"
            )

    def _document_filter(self, document_ids: Sequence[str]) -> Any:
        _, models = _qdrant()
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchAny(any=list(document_ids)),
                )
            ]
        )

    def _existing_ids(self, document_ids: Sequence[str]) -> set[str]:
        found: set[str] = set()
        offset: Any = None
        while True:
            records, offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=self._document_filter(document_ids),
                limit=256,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            found.update(str(record.id) for record in records)
            if offset is None:
                return found

    def _write_upserts(self, events: Sequence[UpsertEvent]) -> None:
        _, models = _qdrant()
        for start in range(0, len(events), self.batch_size):
            event_batch = events[start : start + self.batch_size]
            chunks = [chunk for event in event_batch for chunk in event.chunks]
            vectors = self.embedder.embed_documents([chunk.text for chunk in chunks])
            if len(vectors) != len(chunks):
                raise VectorIndexError("embedder returned the wrong number of document vectors")
            if any(len(vector) != self.embedder.dimension for vector in vectors):
                raise VectorIndexError("embedder returned a vector with the wrong dimension")

            document_ids = [event.document_id for event in event_batch]
            existing = self._existing_ids(document_ids)
            point_ids = [_point_id(chunk.id) for chunk in chunks]
            points = []
            for chunk, vector, point_id in zip(chunks, vectors, point_ids, strict=True):
                dumped = chunk.model_dump(mode="json")
                payload = {
                    **dumped["metadata"],
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "ordinal": chunk.ordinal,
                    "text": chunk.text,
                    "citation": dumped["citation"],
                }
                points.append(models.PointStruct(id=point_id, vector=vector, payload=payload))

            self.client.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=True,
            )
            stale = existing - set(point_ids)
            if stale:
                self.client.delete(
                    collection_name=self.collection_name,
                    points_selector=models.PointIdsList(points=sorted(stale)),
                    wait=True,
                )

    def _write_deletions(self, events: Sequence[DeleteEvent]) -> None:
        if not events:
            return
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=self._document_filter([event.document_id for event in events]),
            wait=True,
        )

    def _write_sync(self, events: Sequence[SyncEvent]) -> None:
        self._ensure_collection()
        upserts = [event for event in events if isinstance(event, UpsertEvent)]
        deletions = [event for event in events if isinstance(event, DeleteEvent)]
        self._write_upserts(upserts)
        self._write_deletions(deletions)

    async def write(self, events: Sequence[SyncEvent]) -> None:
        """Apply complete-document upserts and deletions without blocking the event loop."""

        await asyncio.to_thread(self._write_sync, events)

    def search(self, query: str, *, limit: int = 5) -> tuple[SearchHit, ...]:
        """Embed a question and return the closest citation-ready chunks."""

        if limit <= 0:
            raise ValueError("limit must be positive")
        self._ensure_collection()
        vector = self.embedder.embed_query(query)
        if len(vector) != self.embedder.dimension:
            raise VectorIndexError("embedder returned a query vector with the wrong dimension")
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=vector,
            with_payload=True,
            limit=limit,
        )
        hits: list[SearchHit] = []
        for point in response.points:
            payload = point.payload or {}
            reserved = {"chunk_id", "document_id", "ordinal", "text", "citation"}
            hits.append(
                SearchHit(
                    chunk_id=str(payload["chunk_id"]),
                    document_id=str(payload["document_id"]),
                    text=str(payload["text"]),
                    score=point.score,
                    citation=Citation.model_validate(payload["citation"]),
                    metadata={key: value for key, value in payload.items() if key not in reserved},
                )
            )
        return tuple(hits)

    def close(self) -> None:
        self.client.close()
