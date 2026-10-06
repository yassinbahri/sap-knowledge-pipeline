"""Deterministic execution of declared field transformations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any, Protocol

from sap_knowledge.errors import RecipeValidationError
from sap_knowledge.knowledge.transforms import (
    CustomTransform,
    DateTransform,
    FieldTransform,
    HashTransform,
    MaskTransform,
    ValueMapTransform,
)


class FieldTransformer(Protocol):
    """A trusted application hook for one explicitly allowed field."""

    def __call__(
        self,
        value: Any,
        *,
        field: str,
        options: Mapping[str, Any],
    ) -> Any: ...


TransformerRegistry = Mapping[str, FieldTransformer]


def _canonical_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _mask(value: Any, transform: MaskTransform) -> str:
    text = _canonical_text(value)
    prefix = min(transform.visible_prefix, len(text))
    suffix = min(transform.visible_suffix, max(0, len(text) - prefix))
    concealed = max(0, len(text) - prefix - suffix)
    ending = text[len(text) - suffix :] if suffix else ""
    return f"{text[:prefix]}{transform.mask_character * concealed}{ending}"


def _sha256(value: Any, transform: HashTransform) -> str:
    digest = hashlib.sha256(_canonical_text(value).encode("utf-8")).hexdigest()
    return f"{transform.prefix}{digest}"


def _date(value: Any, transform: DateTransform) -> str:
    parsed: date | datetime
    if isinstance(value, datetime | date):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = date.fromisoformat(value)
            except ValueError:
                raise RecipeValidationError(
                    f"date transform received an invalid value for field {transform.field!r}"
                ) from None
    else:
        raise RecipeValidationError(
            f"date transform requires a date-compatible value for field {transform.field!r}"
        )

    if transform.output == "date":
        return parsed.date().isoformat() if isinstance(parsed, datetime) else parsed.isoformat()
    if isinstance(parsed, date) and not isinstance(parsed, datetime):
        parsed = datetime.combine(parsed, datetime.min.time())
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC)
    return parsed.isoformat().replace("+00:00", "Z")


def _mapped(value: Any, transform: ValueMapTransform) -> Any:
    key = _canonical_text(value)
    if key in transform.values:
        return transform.values[key]
    if transform.on_missing == "redact":
        return transform.redacted_value
    raise RecipeValidationError(
        f"value map has no entry for field {transform.field!r}"
    ) from None


def _custom(
    value: Any,
    transform: CustomTransform,
    registry: TransformerRegistry,
) -> Any:
    try:
        hook = registry[transform.name]
    except KeyError:
        raise RecipeValidationError(
            f"custom transform {transform.name!r} is not registered"
        ) from None
    try:
        transformed = hook(value, field=transform.field, options=transform.options)
        json.dumps(transformed, ensure_ascii=False, allow_nan=False)
    except Exception:
        raise RecipeValidationError(
            f"custom transform {transform.name!r} failed for field {transform.field!r}"
        ) from None
    return transformed


def transform_value(
    value: Any,
    transform: FieldTransform,
    *,
    registry: TransformerRegistry,
) -> Any:
    """Apply one declaration without including the source value in failures."""

    if isinstance(transform, MaskTransform):
        return _mask(value, transform)
    if isinstance(transform, HashTransform):
        return _sha256(value, transform)
    if isinstance(transform, DateTransform):
        return _date(value, transform)
    if isinstance(transform, ValueMapTransform):
        return _mapped(value, transform)
    return _custom(value, transform, registry)
