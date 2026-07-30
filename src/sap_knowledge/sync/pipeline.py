"""High-level, resumable OData-to-knowledge synchronization."""

from __future__ import annotations

import asyncio
import hashlib

from sap_knowledge.errors import CheckpointError
from sap_knowledge.knowledge import CharacterChunker, KnowledgeRenderer, document_id_for
from sap_knowledge.knowledge.models import Citation
from sap_knowledge.knowledge.recipes import KnowledgeRecipe
from sap_knowledge.models import SourceDeletion, SourceRecord
from sap_knowledge.sources.odata import ODataClient
from sap_knowledge.sync.checkpoints import FileCheckpointStore
from sap_knowledge.sync.models import (
    DeleteEvent,
    SyncCheckpoint,
    SyncEvent,
    SyncResult,
    UpsertEvent,
)
from sap_knowledge.sync.sinks import SyncEventSink


class ODataKnowledgePipeline:
    """Write source pages as durable, resumable knowledge change events."""

    def __init__(
        self,
        *,
        source: ODataClient,
        recipe: KnowledgeRecipe,
        sink: SyncEventSink,
        checkpoints: FileCheckpointStore,
        renderer: KnowledgeRenderer | None = None,
        chunker: CharacterChunker | None = None,
    ) -> None:
        self.source = source
        self.recipe = recipe
        self.sink = sink
        self.checkpoints = checkpoints
        self.renderer = renderer or KnowledgeRenderer()
        self.chunker = chunker or CharacterChunker()

    @property
    def pipeline_id(self) -> str:
        configuration = "\0".join(
            (
                self.source.service_root,
                self.source.version.value,
                self.recipe.model_dump_json(),
                self.chunker.model_dump_json(),
            )
        )
        return hashlib.sha256(configuration.encode()).hexdigest()

    def _events(
        self,
        records: tuple[SourceRecord, ...],
        deletions: tuple[SourceDeletion, ...],
    ) -> list[SyncEvent]:
        events: list[SyncEvent] = []
        for record in records:
            document = self.renderer.render(record, self.recipe)
            chunks = self.chunker.split(document)
            if chunks:
                events.append(
                    UpsertEvent(
                        document_id=document.id,
                        chunks=chunks,
                        citation=document.citation,
                    )
                )

        for deletion in deletions:
            events.append(
                DeleteEvent(
                    document_id=document_id_for(deletion.entity_set, deletion.key),
                    citation=Citation(
                        entity_set=deletion.entity_set,
                        key=deletion.key,
                    ),
                    reason=deletion.reason,
                )
            )
        return events

    async def run(self, *, force_full: bool = False) -> SyncResult:
        """Resume safely, or start from the entity set when no checkpoint exists."""

        checkpoint = None if force_full else await asyncio.to_thread(self.checkpoints.load)
        if checkpoint and checkpoint.pipeline_id != self.pipeline_id:
            raise CheckpointError("checkpoint belongs to a different pipeline configuration")

        if checkpoint and checkpoint.cursor:
            cursor = checkpoint.cursor
        elif checkpoint and checkpoint.complete and checkpoint.delta_url:
            cursor = checkpoint.delta_url
        elif checkpoint and checkpoint.complete:
            return SyncResult(already_complete=True, checkpoint=checkpoint)
        else:
            cursor = None

        pages = upserts = chunks = deletions = 0
        latest = checkpoint
        async for page in self.source.pages(
            self.recipe.entity_set,
            key_fields=self.recipe.key_fields,
            select=self.recipe.select_fields,
            cursor=cursor,
        ):
            events = self._events(page.records, page.deletions)
            await self.sink.write(events)

            page_upserts = [event for event in events if isinstance(event, UpsertEvent)]
            page_deletions = [event for event in events if isinstance(event, DeleteEvent)]
            pages += 1
            upserts += len(page_upserts)
            chunks += sum(len(event.chunks) for event in page_upserts)
            deletions += len(page_deletions)

            latest = SyncCheckpoint(
                pipeline_id=self.pipeline_id,
                cursor=page.next_url,
                delta_url=page.delta_url or (latest.delta_url if latest else None),
                complete=page.next_url is None,
            )
            await asyncio.to_thread(self.checkpoints.save, latest)

        return SyncResult(
            pages=pages,
            upserts=upserts,
            chunks=chunks,
            deletions=deletions,
            checkpoint=latest,
        )
