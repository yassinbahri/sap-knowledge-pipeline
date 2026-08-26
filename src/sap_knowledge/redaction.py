"""Small helpers for keeping sensitive provider details out of errors."""

from __future__ import annotations

from collections.abc import Iterable

SENSITIVE_PLACEHOLDER = "<redacted>"


def redacted_values(values: Iterable[object]) -> tuple[str, ...]:
    """Return fixed placeholders for sensitive values.

    The number of placeholders is intentionally preserved because parameter
    count is useful for debugging prepared-statement failures.
    """

    return tuple(SENSITIVE_PLACEHOLDER for _value in values)
