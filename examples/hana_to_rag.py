"""Stream an allow-listed HANA view into citation-ready RAG chunks."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from sap_knowledge import FieldMapping, KnowledgeRecipe
from sap_knowledge.sources.hana import HanaClient, HanaDataset
from sap_knowledge.sync import HanaSnapshotKnowledgePipeline, JsonlEventSink

DATASET = HanaDataset(
    name="PRODUCT_KNOWLEDGE",
    statement=(
        'SELECT "PRODUCT_ID", "PRODUCT_NAME", "DESCRIPTION", "CATEGORY" '
        'FROM "RAG_READ"."PRODUCT_KNOWLEDGE" ORDER BY "PRODUCT_ID"'
    ),
    key_fields=("PRODUCT_ID",),
)

RECIPE = KnowledgeRecipe(
    name="hana_products",
    entity_set="PRODUCT_KNOWLEDGE",
    key_fields=("PRODUCT_ID",),
    title_fields=("PRODUCT_NAME",),
    document_type="product",
    fields=(
        FieldMapping(source="PRODUCT_NAME", label="Product", required=True),
        FieldMapping(source="DESCRIPTION", label="Description"),
        FieldMapping(source="CATEGORY", label="Category"),
    ),
)


async def synchronize() -> None:
    with HanaClient.connect(
        address=os.environ["SAP_HANA_ADDRESS"],
        port=int(os.environ.get("SAP_HANA_PORT", "443")),
        user=os.environ["SAP_HANA_USER"],
        password=os.environ["SAP_HANA_PASSWORD"],
    ) as source:
        result = await HanaSnapshotKnowledgePipeline(
            source=source,
            dataset=DATASET,
            recipe=RECIPE,
            sink=JsonlEventSink(Path("data/hana-product-events.jsonl")),
        ).run()
    print(result.model_dump_json(indent=2))


def main() -> None:
    asyncio.run(synchronize())


if __name__ == "__main__":
    main()
