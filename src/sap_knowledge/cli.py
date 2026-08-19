"""Command-line interface for inspecting and synchronizing SAP OData."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from sap_knowledge import __version__
from sap_knowledge.configuration import AppConfig, load_config
from sap_knowledge.errors import RecipeValidationError, SapKnowledgeError
from sap_knowledge.integrations.fastembed import FastEmbedder
from sap_knowledge.integrations.qdrant import QdrantKnowledgeIndex
from sap_knowledge.knowledge.recipes import KnowledgeRecipe
from sap_knowledge.sources.odata import ODataClient
from sap_knowledge.sources.odata.metadata import ServiceMetadata
from sap_knowledge.sync import (
    FileCheckpointStore,
    JsonlEventSink,
    ODataKnowledgePipeline,
    SyncEvent,
)
from sap_knowledge.vector import build_rag_prompt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sap-knowledge",
        description="Turn SAP OData entities into citation-ready RAG events.",
    )
    parser.add_argument(
        "--config",
        default="sap-knowledge.toml",
        help="TOML configuration path (default: sap-knowledge.toml)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="Inspect OData EDMX metadata")
    inspect.add_argument("--entity-set", help="Show one entity set instead of all sets")
    inspect.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    sync = commands.add_parser("sync", help="Run or resume knowledge synchronization")
    sync.add_argument(
        "--force-full",
        action="store_true",
        help="Ignore the current checkpoint and start a complete snapshot",
    )

    checkpoint = commands.add_parser("checkpoint", help="Show synchronization state")
    checkpoint.add_argument(
        "--reveal-cursors",
        action="store_true",
        help="Print sensitive continuation and delta URLs",
    )

    index = commands.add_parser("index", help="Embed JSONL events into local Qdrant")
    index.add_argument(
        "--events",
        type=Path,
        help="Override the configured JSONL event path",
    )

    search = commands.add_parser("search", help="Search the local vector index")
    search.add_argument("query", help="Natural-language retrieval query")
    search.add_argument("--limit", type=int, default=5, help="Maximum results (default: 5)")
    search.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Require retrieval metadata to match; repeat for multiple values or keys",
    )

    prompt = commands.add_parser("prompt", help="Build a grounded prompt from vector results")
    prompt.add_argument("query", help="Question to retrieve context for")
    prompt.add_argument("--limit", type=int, default=5, help="Maximum sources (default: 5)")
    prompt.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Require retrieval metadata to match; repeat for multiple values or keys",
    )
    return parser


def _parse_filters(values: Sequence[str]) -> dict[str, str | tuple[str, ...]]:
    parsed: dict[str, list[str]] = {}
    for item in values:
        key, separator, value = item.partition("=")
        if not separator or not key or not value:
            raise RecipeValidationError("metadata filters must use non-empty KEY=VALUE syntax")
        parsed.setdefault(key, []).append(value)
    return {
        key: entries[0] if len(entries) == 1 else tuple(entries) for key, entries in parsed.items()
    }


def _source(config: AppConfig, http: httpx.AsyncClient) -> ODataClient:
    return ODataClient(
        service_root=config.service.root,
        version=config.service.version,
        http=http,
    )


def _validate_recipe(metadata: ServiceMetadata, recipe: KnowledgeRecipe) -> None:
    try:
        entity = metadata.entity_set(recipe.entity_set)
    except StopIteration as exc:
        raise RecipeValidationError(
            f"metadata does not contain recipe entity set {recipe.entity_set!r}"
        ) from exc

    available = {field.name for field in entity.properties}
    missing = set(recipe.select_fields) - available
    if missing:
        names = ", ".join(sorted(missing))
        raise RecipeValidationError(f"metadata is missing recipe properties: {names}")
    if tuple(entity.keys) != recipe.key_fields:
        raise RecipeValidationError(
            f"metadata keys {entity.keys!r} do not match recipe keys {recipe.key_fields!r}"
        )


def _metadata_data(metadata: ServiceMetadata, entity_set: str | None) -> dict[str, Any]:
    entities = metadata.entity_sets
    if entity_set:
        try:
            entities = (metadata.entity_set(entity_set),)
        except StopIteration as exc:
            raise RecipeValidationError(f"metadata has no entity set {entity_set!r}") from exc
    return {
        "version": metadata.version.value,
        "entity_sets": [
            {
                "name": entity.name,
                "entity_type": entity.entity_type,
                "keys": list(entity.keys),
                "properties": [
                    {
                        "name": prop.name,
                        "type": prop.type,
                        "nullable": prop.nullable,
                    }
                    for prop in entity.properties
                ],
                "navigation_properties": list(entity.navigation_properties),
            }
            for entity in entities
        ],
    }


async def _inspect(config: AppConfig, *, entity_set: str | None, as_json: bool) -> None:
    async with httpx.AsyncClient(
        auth=config.service.authentication(),
        headers=config.service.headers(),
        timeout=config.service.timeout_seconds,
    ) as http:
        metadata = await _source(config, http).metadata()

    data = _metadata_data(metadata, entity_set)
    if as_json:
        print(json.dumps(data, indent=2))
        return

    print(f"OData V{data['version']} — {len(data['entity_sets'])} entity set(s)")
    for entity in data["entity_sets"]:
        keys = ", ".join(entity["keys"]) or "none"
        print(f"- {entity['name']} ({entity['entity_type']}), keys: {keys}")


async def _sync(config: AppConfig, *, force_full: bool) -> None:
    recipe = config.pipeline.knowledge_recipe()
    async with httpx.AsyncClient(
        auth=config.service.authentication(),
        headers=config.service.headers(),
        timeout=config.service.timeout_seconds,
    ) as http:
        source = _source(config, http)
        metadata = await source.metadata()
        _validate_recipe(metadata, recipe)
        pipeline = ODataKnowledgePipeline(
            source=source,
            recipe=recipe,
            sink=JsonlEventSink(config.pipeline.events_path),
            checkpoints=FileCheckpointStore(config.pipeline.checkpoint_path),
            chunker=config.pipeline.chunker(),
        )
        result = await pipeline.run(force_full=force_full)
    print(result.model_dump_json(indent=2, exclude={"checkpoint"}))


def _checkpoint(config: AppConfig, *, reveal_cursors: bool) -> None:
    state = FileCheckpointStore(config.pipeline.checkpoint_path).load()
    if state is None:
        print("No checkpoint exists.")
        return
    data = state.model_dump(mode="json")
    if not reveal_cursors:
        data["cursor"] = "<present; redacted>" if state.cursor else None
        data["delta_url"] = "<present; redacted>" if state.delta_url else None
    print(json.dumps(data, indent=2))


def _vector_index(config: AppConfig) -> QdrantKnowledgeIndex:
    if config.vector is None:
        raise RecipeValidationError("configuration does not define a [vector] section")
    embedder = FastEmbedder(
        config.vector.model,
        cache_dir=str(config.vector.model_cache_path),
    )
    return QdrantKnowledgeIndex.local(
        path=str(config.vector.path),
        collection_name=config.vector.collection,
        embedder=embedder,
        batch_size=config.vector.batch_size,
    )


async def _index(config: AppConfig, *, events_path: Path | None) -> None:
    path = events_path.resolve() if events_path else config.pipeline.events_path
    adapter: TypeAdapter[SyncEvent] = TypeAdapter(SyncEvent)
    index = _vector_index(config)
    indexed_events = indexed_upserts = indexed_deletions = 0
    batch: list[SyncEvent] = []
    try:
        with path.open("rb") as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue
                try:
                    event = adapter.validate_json(line)
                except ValidationError as exc:
                    raise RecipeValidationError(
                        f"invalid sync event at {path}:{line_number}"
                    ) from exc
                batch.append(event)
                if len(batch) >= index.batch_size:
                    await index.write(batch)
                    indexed_events += len(batch)
                    indexed_upserts += sum(event.operation == "upsert" for event in batch)
                    indexed_deletions += sum(event.operation == "delete" for event in batch)
                    batch.clear()
            if batch:
                await index.write(batch)
                indexed_events += len(batch)
                indexed_upserts += sum(event.operation == "upsert" for event in batch)
                indexed_deletions += sum(event.operation == "delete" for event in batch)
    except OSError as exc:
        raise RecipeValidationError(f"cannot read sync events {path}") from exc
    finally:
        index.close()
    print(
        json.dumps(
            {
                "events": indexed_events,
                "upserts": indexed_upserts,
                "deletions": indexed_deletions,
            },
            indent=2,
        )
    )


def _search(config: AppConfig, *, query: str, limit: int, filters: Sequence[str] = ()) -> None:
    index = _vector_index(config)
    try:
        hits = index.search(query, limit=limit, filters=_parse_filters(filters))
    finally:
        index.close()
    print(json.dumps([hit.model_dump(mode="json") for hit in hits], indent=2))


def _prompt(config: AppConfig, *, query: str, limit: int, filters: Sequence[str] = ()) -> None:
    index = _vector_index(config)
    try:
        hits = index.search(query, limit=limit, filters=_parse_filters(filters))
    finally:
        index.close()
    print(build_rag_prompt(query, hits))


def run_cli(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit status."""

    arguments = _parser().parse_args(argv)
    try:
        config = load_config(arguments.config)
        if arguments.command == "inspect":
            asyncio.run(_inspect(config, entity_set=arguments.entity_set, as_json=arguments.json))
        elif arguments.command == "sync":
            asyncio.run(_sync(config, force_full=arguments.force_full))
        elif arguments.command == "checkpoint":
            _checkpoint(config, reveal_cursors=arguments.reveal_cursors)
        elif arguments.command == "index":
            asyncio.run(_index(config, events_path=arguments.events))
        elif arguments.command == "search":
            _search(
                config,
                query=arguments.query,
                limit=arguments.limit,
                filters=arguments.filter,
            )
        else:
            _prompt(
                config,
                query=arguments.query,
                limit=arguments.limit,
                filters=arguments.filter,
            )
    except (SapKnowledgeError, httpx.HTTPError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    """Console-script entry point."""

    raise SystemExit(run_cli())
