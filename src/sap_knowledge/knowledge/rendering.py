"""Deterministic source-record rendering with explicit provenance."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sap_knowledge.errors import RecipeValidationError
from sap_knowledge.knowledge.models import Citation, KnowledgeDocument
from sap_knowledge.knowledge.recipes import KnowledgeRecipe
from sap_knowledge.models import SourceRecord


def _display(value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return ", ".join(_display(item) for item in value)
    return str(value)


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def document_id_for(
    entity_set: str,
    key: Mapping[str, Any],
    *,
    source_type: str = "odata",
) -> str:
    """Build a stable, opaque document ID from an entity set and business key."""

    canonical_key = json.dumps(key, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    identity = f"{entity_set}\0{canonical_key}"
    prefix = entity_set
    if source_type != "odata":
        identity = f"{source_type}\0{identity}"
        prefix = f"{source_type}:{entity_set}"
    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return f"{prefix}:{digest}"


class KnowledgeRenderer:
    """Render only recipe-approved properties from a canonical source record."""

    def render(
        self,
        record: SourceRecord,
        recipe: KnowledgeRecipe,
        *,
        source_url: str | None = None,
    ) -> KnowledgeDocument:
        if record.entity_set != recipe.entity_set:
            raise RecipeValidationError(
                f"recipe expects {recipe.entity_set!r}, received {record.entity_set!r}"
            )

        missing_keys = [field for field in recipe.key_fields if field not in record.key]
        if missing_keys:
            missing = ", ".join(missing_keys)
            raise RecipeValidationError(f"record is missing recipe key fields: {missing}")

        rendered: dict[str, str] = {}
        lines: list[str] = []
        for field in recipe.fields:
            value = record.data.get(field.source)
            if _is_empty(value):
                if field.required:
                    raise RecipeValidationError(
                        f"required recipe field {field.source!r} is missing or empty"
                    )
                if not field.include_empty:
                    continue
            displayed = _display(value) if value is not None else ""
            rendered[field.source] = displayed
            lines.append(f"{field.label}: {displayed}")

        title_parts = [rendered[name] for name in recipe.title_fields if rendered.get(name)]
        if not title_parts:
            raise RecipeValidationError("record has no usable recipe title fields")
        title = " — ".join(title_parts)
        text = "\n".join((title, "", *lines))

        citation = Citation(
            source_type=record.source_type,
            entity_set=record.entity_set,
            key=record.key,
            source_url=source_url,
            etag=record.etag,
        )
        return KnowledgeDocument(
            id=document_id_for(
                record.entity_set,
                record.key,
                source_type=record.source_type,
            ),
            recipe=recipe.name,
            title=title,
            text=text,
            citation=citation,
            metadata={
                "document_type": recipe.document_type,
                "entity_set": record.entity_set,
                "recipe": recipe.name,
            },
        )
