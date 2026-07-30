# SAP Knowledge Pipeline

Turn selected SAP OData business objects into secure, citation-ready knowledge
for retrieval-augmented generation (RAG).

> [!IMPORTANT]
> This project is an early technical foundation. It is not affiliated with or
> endorsed by SAP. It does not grant access to SAP systems or reproduce SAP's
> authorization model.

## How it fits together

```mermaid
flowchart LR
    SAP["SAP OData V2 or V4"] --> SOURCE["Secure source client"]
    SOURCE --> RECORD["Canonical source records"]
    RECORD --> RECIPE["Explicit field allow-list"]
    RECIPE --> DOC["Citation-ready documents"]
    DOC --> CHUNK["Deterministic chunks"]
    CHUNK --> TARGET["Your embedder or vector store"]
```

The package stops before the final target on purpose. Its output is portable,
so an application can choose OpenAI, a local embedding model, pgvector,
Qdrant, SAP HANA Cloud, or another store without changing SAP extraction.

The optional Qdrant integration now provides the first end-to-end local target.

## Current milestone

The first milestone provides the protocol layer required by the later knowledge
pipeline:

- OData V2 and V4 JSON page parsing.
- Server-driven pagination using opaque continuation links.
- Continuation-host validation to prevent credential leakage and SSRF.
- V4 changed and deleted entity handling.
- EDMX metadata inspection for entity sets, keys, properties, and navigation
  properties.
- An async HTTP client that can be tested without a live SAP system.
- Declarative recipes that allow-list fields before they enter RAG.
- Deterministic knowledge documents, citations, and character-aware chunks.
- A conservative SAP Business Partner starter recipe.

Embedding providers, durable checkpoints, and vector-store adapters will be
added after the source and transformation contracts are stable.

## Development setup

```console
python -m venv .venv
```

```console
# Windows PowerShell
.venv\Scripts\Activate.ps1
python -m pip install --group dev -e .

# macOS or Linux
source .venv/bin/activate
python -m pip install --group dev -e .
```

Then run the complete local quality suite:

```console
ruff check .
ruff format --check .
mypy src
pytest
```

## Minimal source example

```python
import asyncio

import httpx

from sap_knowledge.sources.odata import ODataClient, ODataVersion


async def main() -> None:
    async with httpx.AsyncClient() as http:
        client = ODataClient(
            service_root="https://services.odata.org/V4/TripPinServiceRW/",
            version=ODataVersion.V4,
            http=http,
        )

        metadata = await client.metadata()
        people = metadata.entity_set("People")

        async for page in client.pages("People", key_fields=people.keys):
            for record in page.records:
                print(record.key, record.data)


asyncio.run(main())
```

The same client can consume a configured SAP OData service. Credentials should
be supplied through an `httpx.AsyncClient` authentication configuration and
must never be committed to the repository.

## SAP Business Partner to RAG chunks

Recipes are security boundaries as well as rendering instructions. Only the
properties listed by the recipe enter the document text or metadata; an
unexpected field in the OData response is ignored.

```python
import asyncio
import os

import httpx

from sap_knowledge import CharacterChunker, KnowledgeRenderer
from sap_knowledge.recipes import BUSINESS_PARTNER
from sap_knowledge.sources.odata import ODataClient, ODataVersion


async def main() -> None:
    async with httpx.AsyncClient(
        auth=(os.environ["SAP_USER"], os.environ["SAP_PASSWORD"]),
        timeout=30,
    ) as http:
        source = ODataClient(
            service_root=os.environ["SAP_ODATA_SERVICE_ROOT"],
            version=ODataVersion.V2,
            http=http,
        )
        renderer = KnowledgeRenderer()
        chunker = CharacterChunker(max_characters=1200, overlap_characters=120)

        async for page in source.pages(
            BUSINESS_PARTNER.entity_set,
            key_fields=BUSINESS_PARTNER.key_fields,
            select=BUSINESS_PARTNER.select_fields,
        ):
            for record in page.records:
                document = renderer.render(record, BUSINESS_PARTNER)
                for chunk in chunker.split(document):
                    # Send chunk.text and chunk.metadata to your chosen target.
                    print(chunk.model_dump_json())


asyncio.run(main())
```

Every chunk includes:

- A stable chunk and document ID.
- The rendered, embedding-ready text.
- The OData entity set and complete business key.
- The source ETag when supplied by SAP.
- The recipe and document type.

Stable IDs let a later sink upsert changed chunks without duplicating them.
The structured citation lets a RAG application show where an answer came from.

## Command-line usage

Copy the supplied configuration template and edit the service URL:

```console
cp sap-knowledge.example.toml sap-knowledge.toml
```

On Windows PowerShell:

```powershell
Copy-Item sap-knowledge.example.toml sap-knowledge.toml
$env:SAP_USER = "your-technical-user"
$env:SAP_PASSWORD = "your-password"
```

The TOML file contains environment-variable **names**, never passwords or
tokens:

```toml
[service]
root = "https://your-sap-host.example/sap/opu/odata/sap/API_BUSINESS_PARTNER/"
version = "2"
username_env = "SAP_USER"
password_env = "SAP_PASSWORD"

[pipeline]
recipe = "business_partner"
events_path = "data/business-partner-events.jsonl"
checkpoint_path = "state/business-partner.json"
max_characters = 1200
overlap_characters = 120
```

SAP Business Accelerator Hub sandboxes use an API key instead of Basic
authentication. Copy `sap-business-partner-sandbox.example.toml`, obtain your
personal key from SAP, and set it only in the process environment:

```powershell
$env:SAP_API_KEY = "your-personal-sandbox-key"
sap-knowledge --config sap-business-partner-sandbox.example.toml inspect
sap-knowledge --config sap-business-partner-sandbox.example.toml sync
```

The corresponding configuration uses:

```toml
api_key_env = "SAP_API_KEY"
api_key_header = "APIKey"
```

Inspect the service before extracting data:

```console
sap-knowledge --config sap-knowledge.toml inspect
sap-knowledge --config sap-knowledge.toml inspect --entity-set A_BusinessPartner --json
```

Run or resume synchronization:

```console
sap-knowledge --config sap-knowledge.toml sync
```

The CLI validates the built-in recipe against live EDMX metadata before it
requests business data. It fails early when an entity set, key, or selected
property is unavailable.

Inspect checkpoint status without revealing its URLs:

```console
sap-knowledge --config sap-knowledge.toml checkpoint
```

`--reveal-cursors` is available for careful local debugging. Avoid copying its
output into logs or issue reports. You can also run the CLI as
`python -m sap_knowledge`.

## Local vector search and RAG context

Install the optional local embedding and Qdrant dependencies:

```console
python -m pip install "sap-knowledge-pipeline[fastembed]"
```

For a source checkout:

```console
python -m pip install -e ".[fastembed]"
```

The sandbox example config includes a persistent local Qdrant index and the
small English BGE embedding model:

```toml
[vector]
path = "data/qdrant-business-partners"
collection = "sap_business_partners"
model = "BAAI/bge-small-en-v1.5"
model_cache_path = "state/embedding-models"
batch_size = 128
```

After `sync` has produced the JSONL events, embed and index them:

```console
sap-knowledge --config sap-business-partner-sandbox.example.toml index
```

Run semantic retrieval:

```console
sap-knowledge --config sap-business-partner-sandbox.example.toml search \
  "industrial manufacturing and engineering company" --limit 3
```

Results contain the score, source text, document and chunk IDs, and the
original SAP entity set and business key. To create a grounded prompt that can
be sent to any chat model:

```console
sap-knowledge --config sap-business-partner-sandbox.example.toml prompt \
  "Which business partners manufacture industrial components?" --limit 5
```

The prompt requires numbered citations, tells the model to use only retrieved
sources, and treats SAP text as untrusted data rather than instructions. Prompt
construction does not call an LLM or send SAP data to a third party.

The collection records its embedding model and vector dimension. Search and
index operations fail explicitly if configuration changes, preventing vectors
from incompatible embedding spaces from being mixed silently.

Qdrant local mode is intended for development and smaller indexes. The adapter
uses the same Qdrant collection operations needed for a server or cloud target,
but remote connection configuration and production hardening are future work.

## Live compatibility smoke test

The regular test suite is fully offline. An opt-in example checks real public
services without retaining their data:

```console
python examples/live_odata_smoke.py
```

It inspects the public SAP Business Accelerator Hub catalog metadata, then runs
the complete temporary JSONL/checkpoint pipeline against the OData reference
Northwind V2 and TripPin V4 services. Network availability and those external
services are outside this project's control, so this is deliberately not part
of CI.

## Durable synchronization to JSONL

`ODataKnowledgePipeline` combines extraction, rendering, chunking, deletion
events, and checkpoints. JSONL is the first portable sink: it is easy to
inspect, replay, import into another system, or use as the input to a custom
embedding worker.

```python
from pathlib import Path

from sap_knowledge.sync import (
    FileCheckpointStore,
    JsonlEventSink,
    ODataKnowledgePipeline,
)

pipeline = ODataKnowledgePipeline(
    source=source,
    recipe=BUSINESS_PARTNER,
    sink=JsonlEventSink(Path("data/business-partner-events.jsonl")),
    checkpoints=FileCheckpointStore(Path("state/business-partner.json")),
)

result = await pipeline.run()
print(result.model_dump())
```

The first run reads the complete entity set. The checkpoint records each next
link only after that page's events have been flushed to disk. A later call:

- Resumes an interrupted pagination cursor.
- Uses the saved delta link when the OData service provides one.
- Emits `delete` events for V4 removed entities.
- Returns immediately when a snapshot is complete and has no delta link.

Pass `force_full=True` to intentionally start a new complete snapshot:

```python
await pipeline.run(force_full=True)
```

Upserts contain the complete chunk set for a document. A downstream adapter
should replace all chunks with the same `document_id`; deletes should remove
all of them.

> [!NOTE]
> Synchronization is intentionally **at least once**. If event output succeeds
> but checkpoint persistence fails, the page is replayed. Consumers must upsert
> by stable IDs. Use only one writer per JSONL/checkpoint pair.

> [!WARNING]
> OData continuation and delta URLs may contain opaque access state. Protect the
> checkpoint directory like a credential, never commit it, and do not expose it
> in logs.

Use a separate checkpoint file for every sink. Recipe and chunker settings are
fingerprinted; changing either one requires `force_full=True`, which prevents a
new transformation configuration from being applied only to later changes.

### Defining a custom recipe

```python
from sap_knowledge import FieldMapping, KnowledgeRecipe

MATERIAL = KnowledgeRecipe(
    name="material",
    entity_set="A_Product",
    key_fields=("Product",),
    title_fields=("ProductName", "Product"),
    document_type="sap_material",
    fields=(
        FieldMapping(source="ProductName", label="Product name"),
        FieldMapping(source="Product", label="Product ID", required=True),
        FieldMapping(source="ProductType", label="Product type"),
        FieldMapping(source="BaseUnit", label="Base unit"),
    ),
)
```

Pass `MATERIAL.select_fields` to `ODataClient.pages()`. This requests only the
keys and allowed properties and provides a second guard in case the service
returns additional data.

> [!CAUTION]
> Field allow-listing does not replace SAP authorization. Use a least-privilege
> technical user, validate which business data may leave SAP, and apply tenant
> or user-level authorization again when retrieving chunks.

## Contributing

Contributions are welcome, including small fixtures and documentation fixes.
Read [CONTRIBUTING.md](CONTRIBUTING.md) for setup, testing, pull-request, and
SAP test-data safety guidance.
