from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sap_knowledge.errors import RecipeValidationError
from sap_knowledge.knowledge.transformation import transform_value
from sap_knowledge.knowledge.transforms import (
    CustomTransform,
    DateTransform,
    HashTransform,
    MaskTransform,
    ValueMapTransform,
)


def test_builtin_transforms_are_deterministic() -> None:
    assert transform_value(
        "DE89370400440532013000",
        MaskTransform(field="IBAN", visible_prefix=2, visible_suffix=4),
        registry={},
    ) == "DE****************3000"
    assert transform_value(
        {"b": 2, "a": 1}, HashTransform(field="Account"), registry={}
    ) == transform_value(
        {"a": 1, "b": 2}, HashTransform(field="Account"), registry={}
    )
    assert transform_value(
        datetime(2026, 10, 6, 12, 30, tzinfo=UTC),
        DateTransform(field="ChangedAt", output="datetime"),
        registry={},
    ) == "2026-10-06T12:30:00Z"
    assert (
        transform_value(
            True,
            ValueMapTransform(field="Active", values={"true": "active"}),
            registry={},
        )
        == "active"
    )


def test_map_can_redact_unmapped_values_without_disclosing_them() -> None:
    secret = "confidential-status"
    transform = ValueMapTransform(
        field="Status",
        values={"A": "approved"},
        on_missing="redact",
    )

    assert transform_value(secret, transform, registry={}) == "<redacted>"


def test_transform_errors_do_not_include_source_values() -> None:
    secret = "private-value-7842"

    with pytest.raises(RecipeValidationError) as captured:
        transform_value(
            secret,
            ValueMapTransform(field="Status", values={"A": "approved"}),
            registry={},
        )
    assert secret not in str(captured.value)


def test_custom_transform_is_registered_and_json_compatible() -> None:
    def uppercase(value: object, *, field: str, options: object) -> str:
        assert field == "Name"
        assert options == {"suffix": "!"}
        return f"{value!s}.upper()"

    transformed = transform_value(
        "Pump",
        CustomTransform(field="Name", name="example.upper", options={"suffix": "!"}),
        registry={"example.upper": uppercase},
    )

    assert transformed == "Pump.upper()"


def test_custom_transform_failure_is_redacted() -> None:
    secret = "customer-secret"

    def unsafe(value: object, *, field: str, options: object) -> object:
        raise RuntimeError(f"failed for {value}")

    with pytest.raises(RecipeValidationError) as captured:
        transform_value(
            secret,
            CustomTransform(field="Name", name="unsafe"),
            registry={"unsafe": unsafe},
        )
    assert secret not in str(captured.value)
