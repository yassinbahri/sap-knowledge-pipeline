"""Opt-in live compatibility smoke test; no credentials or output files are retained."""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from sap_knowledge import FieldMapping, KnowledgeRecipe
from sap_knowledge.sources.odata import ODataClient, ODataVersion
from sap_knowledge.sync import FileCheckpointStore, JsonlEventSink, ODataKnowledgePipeline

NORTHWIND_PRODUCTS = KnowledgeRecipe(
    name="northwind-products-live",
    entity_set="Products",
    key_fields=("ProductID",),
    title_fields=("ProductName",),
    fields=(
        FieldMapping(source="ProductID", label="Product ID", required=True),
        FieldMapping(source="ProductName", label="Product name", required=True),
        FieldMapping(source="QuantityPerUnit", label="Quantity per unit"),
        FieldMapping(source="UnitPrice", label="Unit price"),
        FieldMapping(source="Discontinued", label="Discontinued"),
    ),
)

TRIPPIN_PEOPLE = KnowledgeRecipe(
    name="trippin-people-live",
    entity_set="People",
    key_fields=("UserName",),
    title_fields=("FirstName", "LastName"),
    fields=(
        FieldMapping(source="UserName", label="Username", required=True),
        FieldMapping(source="FirstName", label="First name", required=True),
        FieldMapping(source="LastName", label="Last name", required=True),
        FieldMapping(source="Gender", label="Gender"),
        FieldMapping(source="Emails", label="Emails"),
    ),
)


async def inspect_public_sap_catalog(http: httpx.AsyncClient) -> None:
    source = ODataClient(
        service_root="https://api.sap.com/odata/1.0/catalog.svc/",
        version=ODataVersion.V2,
        http=http,
    )
    metadata = await source.metadata()
    print(f"SAP catalog: OData V{metadata.version.value}, {len(metadata.entity_sets)} sets")


async def run_pipeline(
    http: httpx.AsyncClient,
    *,
    label: str,
    service_root: str,
    version: ODataVersion,
    recipe: KnowledgeRecipe,
) -> None:
    with TemporaryDirectory() as directory:
        temporary = Path(directory)
        source = ODataClient(service_root=service_root, version=version, http=http)
        metadata = await source.metadata()
        entity = metadata.entity_set(recipe.entity_set)
        available = {prop.name for prop in entity.properties}
        missing = set(recipe.select_fields) - available
        if missing:
            raise RuntimeError(f"{label} metadata is missing recipe fields: {sorted(missing)}")

        result = await ODataKnowledgePipeline(
            source=source,
            recipe=recipe,
            sink=JsonlEventSink(temporary / "events.jsonl"),
            checkpoints=FileCheckpointStore(temporary / "checkpoint.json"),
        ).run()
        print(f"{label}: {result.pages} pages, {result.upserts} documents, {result.chunks} chunks")


async def run() -> None:
    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as http:
        await inspect_public_sap_catalog(http)
        await run_pipeline(
            http,
            label="Northwind V2",
            service_root="https://services.odata.org/V2/Northwind/Northwind.svc/",
            version=ODataVersion.V2,
            recipe=NORTHWIND_PRODUCTS,
        )
        await run_pipeline(
            http,
            label="TripPin V4",
            service_root="https://services.odata.org/V4/TripPinServiceRW/",
            version=ODataVersion.V4,
            recipe=TRIPPIN_PEOPLE,
        )


if __name__ == "__main__":
    asyncio.run(run())
