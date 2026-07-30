from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest

from sap_knowledge.errors import CheckpointError
from sap_knowledge.knowledge import FieldMapping, KnowledgeRecipe
from sap_knowledge.sources.odata import ODataClient, ODataVersion
from sap_knowledge.sync import (
    FileCheckpointStore,
    JsonlEventSink,
    ODataKnowledgePipeline,
    SyncCheckpoint,
    SyncEvent,
    SyncResult,
)


def notification_recipe() -> KnowledgeRecipe:
    return KnowledgeRecipe(
        name="notifications",
        entity_set="Notifications",
        key_fields=("ID",),
        title_fields=("Text",),
        fields=(
            FieldMapping(source="ID", label="Notification ID", required=True),
            FieldMapping(source="Text", label="Text", required=True),
        ),
    )


def test_checkpoint_round_trip_and_invalid_file(tmp_path: Path) -> None:
    store = FileCheckpointStore(tmp_path / "state" / "checkpoint.json")
    checkpoint = SyncCheckpoint(
        pipeline_id="pipeline",
        cursor="https://sap.example.test/next",
    )

    store.save(checkpoint)

    assert store.load() == checkpoint
    store.path.write_text("not json", encoding="utf-8")
    with pytest.raises(CheckpointError, match="cannot read checkpoint"):
        store.load()


def test_pipeline_writes_pages_then_resumes_from_delta(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        query = request.url.query.decode()
        if "$deltatoken=old" in query:
            return httpx.Response(
                200,
                json={
                    "value": [{"ID": "1", "@removed": {"reason": "deleted"}}],
                    "@odata.deltaLink": "Notifications?$deltatoken=new",
                },
            )
        if "$skiptoken=page2" in query:
            return httpx.Response(
                200,
                json={
                    "value": [{"ID": "2", "Text": "Second notification"}],
                    "@odata.deltaLink": "Notifications?$deltatoken=old",
                },
            )
        return httpx.Response(
            200,
            json={
                "value": [{"ID": "1", "Text": "First notification"}],
                "@odata.nextLink": "Notifications?$skiptoken=page2",
            },
        )

    async def scenario() -> tuple[object, object]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            pipeline = ODataKnowledgePipeline(
                source=ODataClient(
                    service_root="https://sap.example.test/odata/",
                    version=ODataVersion.V4,
                    http=http,
                ),
                recipe=notification_recipe(),
                sink=JsonlEventSink(tmp_path / "events.jsonl"),
                checkpoints=FileCheckpointStore(tmp_path / "checkpoint.json"),
            )
            initial = await pipeline.run()
            incremental = await pipeline.run()
            return initial, incremental

    initial, incremental = asyncio.run(scenario())
    lines = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    checkpoint = FileCheckpointStore(tmp_path / "checkpoint.json").load()

    assert initial.pages == 2
    assert initial.upserts == 2
    assert initial.chunks == 2
    assert incremental.pages == 1
    assert incremental.deletions == 1
    assert [line["operation"] for line in lines] == ["upsert", "upsert", "delete"]
    assert lines[0]["chunks"][0]["citation"]["key"] == {"ID": "1"}
    assert checkpoint is not None
    assert checkpoint.complete is True
    assert checkpoint.delta_url == "https://sap.example.test/odata/Notifications?$deltatoken=new"
    assert "$deltatoken=old" in requests[-1].url.query.decode()


def test_sink_failure_does_not_advance_checkpoint(tmp_path: Path) -> None:
    class FailingSink:
        async def write(self, events: Sequence[SyncEvent]) -> None:
            raise RuntimeError("storage unavailable")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": [{"ID": "1", "Text": "Failure test"}]})

    checkpoint_store = FileCheckpointStore(tmp_path / "checkpoint.json")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            pipeline = ODataKnowledgePipeline(
                source=ODataClient(
                    service_root="https://sap.example.test/odata/",
                    version=ODataVersion.V4,
                    http=http,
                ),
                recipe=notification_recipe(),
                sink=FailingSink(),
                checkpoints=checkpoint_store,
            )
            await pipeline.run()

    with pytest.raises(RuntimeError, match="storage unavailable"):
        asyncio.run(scenario())
    assert checkpoint_store.load() is None


def test_pipeline_resumes_at_last_durable_page(tmp_path: Path) -> None:
    requested_queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.query.decode()
        requested_queries.append(query)
        if "$skiptoken=page2" in query:
            return httpx.Response(
                200,
                json={"value": [{"ID": "2", "Text": "Second"}]},
            )
        return httpx.Response(
            200,
            json={
                "value": [{"ID": "1", "Text": "First"}],
                "@odata.nextLink": "Notifications?$skiptoken=page2",
            },
        )

    class FailOnSecondWrite:
        def __init__(self) -> None:
            self.calls = 0

        async def write(self, events: Sequence[SyncEvent]) -> None:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("second page failed")

    checkpoint_store = FileCheckpointStore(tmp_path / "checkpoint.json")

    async def scenario() -> SyncResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            source = ODataClient(
                service_root="https://sap.example.test/odata/",
                version=ODataVersion.V4,
                http=http,
            )
            failed_pipeline = ODataKnowledgePipeline(
                source=source,
                recipe=notification_recipe(),
                sink=FailOnSecondWrite(),
                checkpoints=checkpoint_store,
            )
            with pytest.raises(RuntimeError, match="second page failed"):
                await failed_pipeline.run()

            resumed_pipeline = ODataKnowledgePipeline(
                source=source,
                recipe=notification_recipe(),
                sink=JsonlEventSink(tmp_path / "resumed.jsonl"),
                checkpoints=checkpoint_store,
            )
            return await resumed_pipeline.run()

    result = asyncio.run(scenario())
    checkpoint = checkpoint_store.load()

    assert result.pages == 1
    assert result.upserts == 1
    assert requested_queries == [
        "$select=ID,Text",
        "$skiptoken=page2",
        "$skiptoken=page2",
    ]
    assert checkpoint is not None
    assert checkpoint.complete is True


def test_completed_snapshot_without_delta_is_not_reloaded(tmp_path: Path) -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"value": []})

    async def scenario() -> tuple[object, object]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            pipeline = ODataKnowledgePipeline(
                source=ODataClient(
                    service_root="https://sap.example.test/odata/",
                    version=ODataVersion.V4,
                    http=http,
                ),
                recipe=notification_recipe(),
                sink=JsonlEventSink(tmp_path / "events.jsonl"),
                checkpoints=FileCheckpointStore(tmp_path / "checkpoint.json"),
            )
            first = await pipeline.run()
            second = await pipeline.run()
            return first, second

    first, second = asyncio.run(scenario())

    assert first.pages == 1
    assert second.already_complete is True
    assert requests == 1


def test_checkpoint_cannot_be_reused_by_different_configuration(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ) as http:
            source = ODataClient(
                service_root="https://sap.example.test/odata/",
                version=ODataVersion.V4,
                http=http,
            )
            store = FileCheckpointStore(tmp_path / "checkpoint.json")
            store.save(SyncCheckpoint(pipeline_id="not-this-pipeline"))
            pipeline = ODataKnowledgePipeline(
                source=source,
                recipe=notification_recipe(),
                sink=JsonlEventSink(tmp_path / "events.jsonl"),
                checkpoints=store,
            )
            await pipeline.run()

    with pytest.raises(CheckpointError, match="different pipeline"):
        asyncio.run(scenario())
