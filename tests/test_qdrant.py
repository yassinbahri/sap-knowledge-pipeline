from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest
from qdrant_client import QdrantClient

from sap_knowledge.errors import VectorIndexError
from sap_knowledge.integrations.qdrant import QdrantKnowledgeIndex
from sap_knowledge.knowledge import Citation, KnowledgeChunk
from sap_knowledge.sync import DeleteEvent, UpsertEvent


class KeywordEmbedder:
    @property
    def dimension(self) -> int:
        return 3

    @property
    def model_id(self) -> str:
        return "test:keywords-v1"

    def _vector(self, text: str) -> list[float]:
        lowered = text.lower()
        return [
            float("pump" in lowered),
            float("supplier" in lowered),
            float("customer" in lowered),
        ]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class IncompatibleKeywordEmbedder(KeywordEmbedder):
    @property
    def model_id(self) -> str:
        return "test:different-model"


def chunk(document_id: str, ordinal: int, text: str, suffix: str) -> KnowledgeChunk:
    citation = Citation(entity_set="A_BusinessPartner", key={"BusinessPartner": document_id})
    return KnowledgeChunk(
        id=f"{document_id}:chunk:{suffix}",
        document_id=document_id,
        ordinal=ordinal,
        text=text,
        citation=citation,
        metadata={"recipe": "business-partner"},
    )


def test_qdrant_upsert_search_replace_and_delete() -> None:
    client = QdrantClient(":memory:")
    index = QdrantKnowledgeIndex(
        client=client,
        collection_name="business_partners",
        embedder=KeywordEmbedder(),
        batch_size=2,
    )
    pump_document = "A_BusinessPartner:pump"
    supplier_document = "A_BusinessPartner:supplier"
    pump_citation = Citation(
        entity_set="A_BusinessPartner",
        key={"BusinessPartner": "PUMP"},
    )
    supplier_citation = Citation(
        entity_set="A_BusinessPartner",
        key={"BusinessPartner": "SUPPLIER"},
    )

    asyncio.run(
        index.write(
            (
                UpsertEvent(
                    document_id=pump_document,
                    chunks=(
                        chunk(pump_document, 0, "Industrial pump manufacturer", "old-0"),
                        chunk(pump_document, 1, "Pump replacement parts", "old-1"),
                    ),
                    citation=pump_citation,
                ),
                UpsertEvent(
                    document_id=supplier_document,
                    chunks=(chunk(supplier_document, 0, "Office supplier", "supplier-0"),),
                    citation=supplier_citation,
                ),
            )
        )
    )

    hits = index.search("Who manufactures pumps?", limit=2)

    assert hits[0].document_id == pump_document
    assert hits[0].citation.key == {"BusinessPartner": pump_document}
    assert client.count("business_partners", exact=True).count == 3

    asyncio.run(
        index.write(
            (
                UpsertEvent(
                    document_id=pump_document,
                    chunks=(chunk(pump_document, 0, "Industrial pump specialist", "new-0"),),
                    citation=pump_citation,
                ),
            )
        )
    )

    assert client.count("business_partners", exact=True).count == 2
    assert index.search("pump", limit=1)[0].text == "Industrial pump specialist"

    asyncio.run(
        index.write(
            (
                DeleteEvent(
                    document_id=pump_document,
                    citation=pump_citation,
                    reason="deleted",
                ),
            )
        )
    )

    assert client.count("business_partners", exact=True).count == 1
    assert index.search("supplier", limit=1)[0].document_id == supplier_document

    incompatible = QdrantKnowledgeIndex(
        client=client,
        collection_name="business_partners",
        embedder=IncompatibleKeywordEmbedder(),
    )
    with pytest.raises(VectorIndexError, match="embedding model"):
        incompatible.search("supplier")
    index.close()
