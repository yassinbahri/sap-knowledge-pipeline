"""OData V2 and V4 JSON page parsing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from sap_knowledge.errors import InvalidODataPayloadError, MissingEntityKeyError
from sap_knowledge.models import SourceDeletion, SourcePage, SourceRecord


class ODataVersion(StrEnum):
    """OData protocol generations supported by the source client."""

    V2 = "2"
    V4 = "4"


def _mapping(value: object, *, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidODataPayloadError(f"{location} must be a JSON object")
    return value


def _records(value: object, *, location: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise InvalidODataPayloadError(f"{location} must be a JSON array")
    return value


def _key(record: Mapping[str, Any], key_fields: Sequence[str]) -> dict[str, Any]:
    missing = [field for field in key_fields if field not in record]
    if missing:
        raise MissingEntityKeyError(f"record is missing key fields: {', '.join(missing)}")
    return {field: record[field] for field in key_fields}


def _parse_v2(payload: Mapping[str, Any], entity_set: str, key_fields: Sequence[str]) -> SourcePage:
    raw_envelope = payload.get("d")
    raw_records: Sequence[object]
    if isinstance(raw_envelope, list):
        raw_records = raw_envelope
        next_url = None
        delta_url = None
    else:
        envelope = _mapping(raw_envelope, location="d")
        raw_records = _records(envelope.get("results"), location="d.results")
        next_url = envelope.get("__next")
        delta_url = envelope.get("__delta")
    records: list[SourceRecord] = []

    for item in raw_records:
        raw = dict(_mapping(item, location="d.results[]"))
        metadata = raw.pop("__metadata", {})
        metadata_mapping = _mapping(metadata, location="__metadata")
        records.append(
            SourceRecord(
                entity_set=entity_set,
                key=_key(raw, key_fields),
                data=raw,
                etag=metadata_mapping.get("etag"),
            )
        )

    return SourcePage(
        records=tuple(records),
        next_url=next_url,
        delta_url=delta_url,
    )


def _parse_v4(payload: Mapping[str, Any], entity_set: str, key_fields: Sequence[str]) -> SourcePage:
    raw_records = _records(payload.get("value"), location="value")
    records: list[SourceRecord] = []
    deletions: list[SourceDeletion] = []

    for item in raw_records:
        raw = dict(_mapping(item, location="value[]"))
        removed = raw.pop("@removed", None)
        if removed is not None:
            removed_mapping = _mapping(removed, location="@removed")
            deletions.append(
                SourceDeletion(
                    entity_set=entity_set,
                    key=_key(raw, key_fields),
                    reason=removed_mapping.get("reason"),
                )
            )
            continue

        etag = raw.pop("@odata.etag", None)
        records.append(
            SourceRecord(
                entity_set=entity_set,
                key=_key(raw, key_fields),
                data=raw,
                etag=etag,
            )
        )

    return SourcePage(
        records=tuple(records),
        deletions=tuple(deletions),
        next_url=payload.get("@odata.nextLink") or payload.get("odata.nextLink"),
        delta_url=payload.get("@odata.deltaLink") or payload.get("odata.deltaLink"),
    )


def parse_page(
    payload: Mapping[str, Any],
    *,
    version: ODataVersion,
    entity_set: str,
    key_fields: Sequence[str],
) -> SourcePage:
    """Parse one JSON collection or delta page into canonical source records."""

    if not key_fields:
        raise ValueError("at least one key field is required")
    if version is ODataVersion.V2:
        return _parse_v2(payload, entity_set, key_fields)
    return _parse_v4(payload, entity_set, key_fields)
