from __future__ import annotations

import asyncio

import httpx

from sap_knowledge.knowledge import CharacterChunker, KnowledgeRenderer
from sap_knowledge.recipes import BUSINESS_PARTNER
from sap_knowledge.sources.odata import ODataClient, ODataVersion


def test_odata_business_partner_to_rag_chunks() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "d": {
                    "results": [
                        {
                            "__metadata": {"etag": 'W/"20260730"'},
                            "BusinessPartner": "1000001",
                            "BusinessPartnerFullName": "Northwind Components Ltd",
                            "BusinessPartnerCategory": "2",
                            "BusinessPartnerGrouping": "BP02",
                            "SearchTerm1": "NORTHWIND",
                            "BankAccount": "must-not-enter-rag",
                        }
                    ]
                }
            },
        )

    async def scenario() -> tuple[str, tuple[str, ...]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ODataClient(
                service_root="https://sap.example.test/sap/opu/odata/sap/API_BUSINESS_PARTNER/",
                version=ODataVersion.V2,
                http=http,
            )
            documents = []
            async for page in client.pages(
                BUSINESS_PARTNER.entity_set,
                key_fields=BUSINESS_PARTNER.key_fields,
                select=BUSINESS_PARTNER.select_fields,
            ):
                documents.extend(
                    KnowledgeRenderer().render(record, BUSINESS_PARTNER) for record in page.records
                )

        document = documents[0]
        chunks = CharacterChunker().split(document)
        return document.text, tuple(chunk.text for chunk in chunks)

    text, chunks = asyncio.run(scenario())

    assert requests[0].url.params["$select"].startswith("BusinessPartner,BusinessPartnerFullName")
    assert "Northwind Components Ltd" in text
    assert "BankAccount" not in text
    assert chunks == (text,)
