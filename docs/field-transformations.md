# Field transformations and redaction

Knowledge recipes can transform explicitly selected SAP fields before a value
reaches document text, retrieval metadata, citations, chunks, or document IDs.
This is useful when an approved field still needs masking, pseudonymization,
normalization, or classification before it enters a RAG system.

Transformations are opt-in. A recipe rejects a transformation that references
a field not declared in `key_fields`, `fields`, or `metadata`. Each field can
have only one transformation.

## Built-in transformations

All built-in declarations are frozen Pydantic models. They validate when the
recipe is created and round-trip through JSON.

```python
from sap_knowledge import (
    DateTransform,
    HashTransform,
    MaskTransform,
    ValueMapTransform,
)

transforms = (
    MaskTransform(
        field="BankAccount",
        visible_prefix=2,
        visible_suffix=4,
    ),
    HashTransform(field="BusinessPartner"),
    DateTransform(field="ChangedAt", output="date"),
    ValueMapTransform(
        field="RiskClass",
        values={"A": "low", "B": "medium", "C": "high"},
        on_missing="redact",
    ),
)
```

The available operations are:

- `MaskTransform`: keeps an optional prefix and suffix and masks the remaining
  characters. The result still reveals the original value's length.
- `HashTransform`: returns a deterministic SHA-256 digest. This supports stable
  identifiers but is pseudonymization, not anonymization. Low-entropy values
  remain vulnerable to dictionary attacks.
- `DateTransform`: parses ISO-compatible dates and datetimes and emits a stable
  date or datetime representation. Aware datetimes are normalized to UTC.
- `ValueMapTransform`: replaces values from an explicit mapping. Unknown values
  either stop rendering or become the configured redaction value; they are
  never retained implicitly.

Attach the declarations to a recipe:

```python
from sap_knowledge import KnowledgeRecipe

recipe = KnowledgeRecipe(
    name="secured_business_partner",
    entity_set="A_BusinessPartner",
    key_fields=("BusinessPartner",),
    title_fields=("BusinessPartnerFullName",),
    fields=(...),
    metadata=(...),
    transforms=transforms,
)
```

## Where transformed values are used

`KnowledgeRenderer` applies every transformation once and reuses the result in
all downstream representations:

- title and embedded document text;
- retrieval metadata;
- citation business keys;
- deterministic document and chunk identifiers.

When a recipe transforms any field, the renderer omits `citation.source_url`.
SAP URLs can contain business values in their path or query string, and the
generic renderer cannot safely determine which URL fragments need redaction.

The original `SourceRecord` remains unchanged in memory. Do not log or persist
source records before rendering if they contain sensitive data.

## Trusted custom hooks

Applications can register a custom callable and reference it by a serializable
name:

```python
from collections.abc import Mapping
from typing import Any

from sap_knowledge import CustomTransform, KnowledgeRenderer


def normalize_cost_center(
    value: Any,
    *,
    field: str,
    options: Mapping[str, Any],
) -> str:
    width = int(options.get("width", 10))
    return str(value).strip().zfill(width)


renderer = KnowledgeRenderer(transformers={"company.normalize_cost_center": normalize_cost_center})

transform = CustomTransform(
    field="CostCenter",
    name="company.normalize_cost_center",
    options={"width": 10},
)
```

Custom hooks receive the unredacted source value and therefore run inside the
application's trust boundary. Review them like credential-handling code: do not
log arguments, include values in exceptions, call untrusted services, or retain
values outside the invocation. Hooks must be deterministic and return a
JSON-compatible value. Package-facing errors hide the source value, but the
package cannot prevent a hook itself from leaking data through side effects.

## Operational guidance

- Prefer `ValueMapTransform` when the allowed output vocabulary is known.
- Do not treat unsalted SHA-256 as anonymization for company codes, personnel
  numbers, or other enumerable values.
- Test the serialized `KnowledgeDocument`, not only its visible `text`, when
  asserting that a source value was removed.
- Changing a transformation can change document IDs when it applies to a key.
  Plan a target reindex or deletion reconciliation before deploying that change.
