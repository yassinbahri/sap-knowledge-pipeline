from __future__ import annotations

import asyncio

import httpx
import pytest

from sap_knowledge.errors import InvalidODataPayloadError, RepeatedContinuationError
from sap_knowledge.sources.odata import ODataClient, ODataVersion


def test_client_follows_server_next_link_verbatim() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "value": [{"ID": "1", "Text": "First"}],
                    "@odata.nextLink": "Notifications?$skiptoken=opaque%2Bvalue",
                },
            )
        return httpx.Response(
            200,
            json={
                "value": [{"ID": "2", "Text": "Second"}],
                "@odata.deltaLink": "Notifications?$deltatoken=final",
            },
        )

    async def scenario() -> list[object]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ODataClient(
                service_root="https://sap.example.test/odata/",
                version=ODataVersion.V4,
                http=http,
            )
            return [page async for page in client.pages("Notifications", key_fields=("ID",))]

    pages = asyncio.run(scenario())

    assert len(pages) == 2
    assert requests[1].url.query == b"$skiptoken=opaque%2Bvalue"
    assert pages[1].delta_url == ("https://sap.example.test/odata/Notifications?$deltatoken=final")


def test_client_stops_repeated_continuation_loop() -> None:
    repeated = "https://sap.example.test/odata/Notifications?$skiptoken=same"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": [{"ID": "1"}], "@odata.nextLink": repeated})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ODataClient(
                service_root="https://sap.example.test/odata/",
                version=ODataVersion.V4,
                http=http,
            )
            async for _page in client.pages("Notifications", key_fields=("ID",), cursor=repeated):
                pass

    with pytest.raises(RepeatedContinuationError):
        asyncio.run(scenario())


def test_non_json_response_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ODataClient(
                service_root="https://sap.example.test/odata/",
                version=ODataVersion.V4,
                http=http,
            )
            async for _page in client.pages("Notifications", key_fields=("ID",)):
                pass

    with pytest.raises(InvalidODataPayloadError, match="not valid JSON"):
        asyncio.run(scenario())
