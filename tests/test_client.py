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


def test_client_retries_transport_throttling_and_transient_server_errors() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("temporary connection failure", request=request)
        if attempts == 2:
            return httpx.Response(429, headers={"Retry-After": "0"})
        if attempts == 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"value": []})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ODataClient(
                service_root="https://sap.example.test/odata/",
                version=ODataVersion.V4,
                http=http,
                max_retries=3,
                retry_backoff_seconds=0,
            )
            pages = [page async for page in client.pages("Products", key_fields=("ID",))]
        assert len(pages) == 1

    asyncio.run(scenario())
    assert attempts == 4


def test_client_does_not_retry_non_transient_statuses() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, request=request)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ODataClient(
                service_root="https://sap.example.test/odata/",
                version=ODataVersion.V4,
                http=http,
                retry_backoff_seconds=0,
            )
            with pytest.raises(httpx.HTTPStatusError):
                await anext(client.pages("Products", key_fields=("ID",)))

    asyncio.run(scenario())
    assert attempts == 1
