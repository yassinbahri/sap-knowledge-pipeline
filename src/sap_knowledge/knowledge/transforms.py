"""Serializable field transformation declarations for knowledge recipes."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class _Transform(BaseModel):
    """Shared validation for an explicitly selected recipe field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str = Field(min_length=1)


class MaskTransform(_Transform):
    """Replace the concealed portion of a value with a mask character."""

    kind: Literal["mask"] = "mask"
    visible_prefix: int = Field(default=0, ge=0)
    visible_suffix: int = Field(default=0, ge=0)
    mask_character: str = Field(default="*", min_length=1, max_length=1)


class HashTransform(_Transform):
    """Replace a value with its deterministic SHA-256 digest."""

    kind: Literal["sha256"] = "sha256"
    prefix: str = "sha256:"


class DateTransform(_Transform):
    """Normalize an ISO-compatible date or datetime."""

    kind: Literal["date"] = "date"
    output: Literal["date", "datetime"] = "date"


class ValueMapTransform(_Transform):
    """Replace known values with an explicit JSON-compatible mapping."""

    kind: Literal["map"] = "map"
    values: dict[str, JsonValue] = Field(min_length=1)
    on_missing: Literal["error", "redact"] = "error"
    redacted_value: JsonValue = "<redacted>"


class CustomTransform(_Transform):
    """Reference a trusted application-provided transformation hook."""

    kind: Literal["custom"] = "custom"
    name: str = Field(min_length=1, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    options: dict[str, JsonValue] = Field(default_factory=dict)


FieldTransform = Annotated[
    MaskTransform | HashTransform | DateTransform | ValueMapTransform | CustomTransform,
    Field(discriminator="kind"),
]
