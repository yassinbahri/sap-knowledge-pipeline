"""Asynchronous read-only OData client with safe continuation handling."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any
from urllib.parse import quote

import httpx

from sap_knowledge.errors import InvalidODataPayloadError, RepeatedContinuationError
from sap_knowledge.models import SourcePage
from sap_knowledge.sources.odata.metadata import ServiceMetadata, parse_metadata
from sap_knowledge.sources.odata.payloads import ODataVersion, parse_page
from sap_knowledge.sources.odata.urls import ContinuationPolicy


class ODataClient:
    """Read entity pages and metadata without hiding server continuation state."""

    def __init__(
        self,
        *,
        service_root: str,
        version: ODataVersion,
        http: httpx.AsyncClient,
        allowed_origins: frozenset[tuple[str, str]] = frozenset(),
        allow_http: bool = False,
    ) -> None:
        self.service_root = service_root.rstrip("/") + "/"
        self.version = version
        self.http = http
        self.policy = ContinuationPolicy(
            self.service_root,
            allowed_origins=allowed_origins,
            allow_http=allow_http,
        )

    @property
    def request_headers(self) -> dict[str, str]:
        """Headers shared by ordinary JSON requests."""

        headers = {"Accept": "application/json"}
        if self.version is ODataVersion.V4:
            headers["OData-Version"] = "4.0"
        else:
            headers["MaxDataServiceVersion"] = "2.0"
        return headers

    async def metadata(self) -> ServiceMetadata:
        """Retrieve and inspect the service EDMX document."""

        response = await self.http.get(self.service_root + "$metadata")
        response.raise_for_status()
        metadata = parse_metadata(response.content)
        if metadata.version is not self.version:
            configured = self.version.value
            declared = metadata.version.value
            raise InvalidODataPayloadError(
                f"configured OData V{configured}, metadata declares V{declared}"
            )
        return metadata

    def entity_url(
        self,
        entity_set: str,
        *,
        select: Sequence[str] = (),
        filter: str | None = None,
        top: int | None = None,
    ) -> str:
        """Construct the initial entity-set URL; continuations are never reconstructed."""

        if not entity_set or any(character in entity_set for character in "/?#"):
            raise ValueError("entity_set must be a single non-empty path segment")
        if top is not None and top <= 0:
            raise ValueError("top must be positive")

        parameters: list[tuple[str, str]] = []
        if select:
            parameters.append(("$select", ",".join(select)))
        if filter:
            parameters.append(("$filter", filter))
        if top is not None:
            parameters.append(("$top", str(top)))

        safe_value_characters = "$(), ':-"
        query = "&".join(
            f"{quote(name, safe='$')}={quote(value, safe=safe_value_characters)}"
            for name, value in parameters
        )
        url = self.service_root + quote(entity_set, safe="")
        return f"{url}?{query}" if query else url

    async def _page(self, url: str, *, entity_set: str, key_fields: Sequence[str]) -> SourcePage:
        response = await self.http.get(url, headers=self.request_headers)
        response.raise_for_status()
        try:
            payload: Mapping[str, Any] = response.json()
        except ValueError as exc:
            raise InvalidODataPayloadError("OData response is not valid JSON") from exc

        page = parse_page(
            payload,
            version=self.version,
            entity_set=entity_set,
            key_fields=key_fields,
        )
        return page.model_copy(
            update={
                "next_url": self.policy.resolve(page.next_url) if page.next_url else None,
                "delta_url": self.policy.resolve(page.delta_url) if page.delta_url else None,
            }
        )

    async def pages(
        self,
        entity_set: str,
        *,
        key_fields: Sequence[str],
        select: Sequence[str] = (),
        filter: str | None = None,
        top: int | None = None,
        cursor: str | None = None,
    ) -> AsyncIterator[SourcePage]:
        """Yield every server-driven page, starting from a query or saved cursor."""

        url: str | None = (
            self.policy.resolve(cursor)
            if cursor
            else self.entity_url(
                entity_set,
                select=select,
                filter=filter,
                top=top,
            )
        )
        seen: set[str] = set()

        while url:
            if url in seen:
                raise RepeatedContinuationError("OData service repeated a continuation URL")
            seen.add(url)
            page = await self._page(url, entity_set=entity_set, key_fields=key_fields)
            yield page
            url = page.next_url
