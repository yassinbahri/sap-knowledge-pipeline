"""Offline checks for citation integrity and retrieval-scope leakage."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sap_knowledge.vector.models import SearchHit


@dataclass(frozen=True)
class RetrievalEvaluation:
    """Result of evaluating one set of citation-ready retrieval hits."""

    checked: int
    missing_citations: tuple[str, ...]
    scope_leaks: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return whether every hit retained provenance and stayed in scope."""

        return not self.missing_citations and not self.scope_leaks


def evaluate_retrieval(
    hits: Sequence[SearchHit],
    *,
    allowed_scopes: Mapping[str, Collection[Any]],
) -> RetrievalEvaluation:
    """Evaluate synthetic or real hits against trusted metadata scopes.

    Scalar metadata must be one of the allowed values. Collection-valued
    metadata, such as security roles, must contain at least one allowed value.
    Missing scope metadata fails closed and is reported as a leak.
    """

    normalized_scopes = {key: set(values) for key, values in allowed_scopes.items()}
    if any(not key.strip() for key in normalized_scopes):
        raise ValueError("scope keys must be non-empty strings")
    if any(not values for values in normalized_scopes.values()):
        raise ValueError("each scope must allow at least one value")

    missing_citations: list[str] = []
    scope_leaks: list[str] = []
    for hit in hits:
        if (
            not hit.document_id.strip()
            or not hit.citation.entity_set.strip()
            or not hit.citation.key
        ):
            missing_citations.append(hit.chunk_id)

        for key, allowed in normalized_scopes.items():
            actual = hit.metadata.get(key)
            if isinstance(actual, (list, tuple, set, frozenset)):
                in_scope = bool(set(actual) & allowed)
            else:
                in_scope = actual in allowed
            if not in_scope:
                scope_leaks.append(f"{hit.chunk_id}:{key}")

    return RetrievalEvaluation(
        checked=len(hits),
        missing_citations=tuple(missing_citations),
        scope_leaks=tuple(scope_leaks),
    )
