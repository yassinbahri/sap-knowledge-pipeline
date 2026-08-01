"""Snapshot synchronization from SAP HANA into portable knowledge events."""

from __future__ import annotations

from sap_knowledge.knowledge import CharacterChunker, KnowledgeRenderer
from sap_knowledge.knowledge.recipes import KnowledgeRecipe
from sap_knowledge.sources.hana import HanaClient, HanaDataset
from sap_knowledge.sync.models import SyncResult, UpsertEvent
from sap_knowledge.sync.sinks import SyncEventSink


class HanaSnapshotKnowledgePipeline:
    """Render one explicit HANA dataset as deterministic upsert events."""

    def __init__(
        self,
        *,
        source: HanaClient,
        dataset: HanaDataset,
        recipe: KnowledgeRecipe,
        sink: SyncEventSink,
        page_size: int = 500,
        renderer: KnowledgeRenderer | None = None,
        chunker: CharacterChunker | None = None,
    ) -> None:
        if dataset.name != recipe.entity_set:
            raise ValueError("HANA dataset name must match the recipe entity_set")
        if dataset.key_fields != recipe.key_fields:
            raise ValueError("HANA dataset key_fields must match the recipe key_fields")
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        self.source = source
        self.dataset = dataset
        self.recipe = recipe
        self.sink = sink
        self.page_size = page_size
        self.renderer = renderer or KnowledgeRenderer()
        self.chunker = chunker or CharacterChunker()

    async def run(self) -> SyncResult:
        """Write a complete HANA snapshot as idempotent upsert events."""

        pages = upserts = chunks = 0
        for page in self.source.pages(self.dataset, page_size=self.page_size):
            events: list[UpsertEvent] = []
            for record in page.records:
                document = self.renderer.render(record, self.recipe)
                document_chunks = self.chunker.split(document)
                if document_chunks:
                    events.append(
                        UpsertEvent(
                            document_id=document.id,
                            chunks=document_chunks,
                            citation=document.citation,
                        )
                    )
            await self.sink.write(events)
            pages += 1
            upserts += len(events)
            chunks += sum(len(event.chunks) for event in events)
        return SyncResult(pages=pages, upserts=upserts, chunks=chunks)
