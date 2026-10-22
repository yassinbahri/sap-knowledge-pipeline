# Synthetic Finance Recipe

This example demonstrates how to build a citation-ready finance document from **synthetic data** using an explicit field allow-list.

The field names are illustrative, not a guaranteed SAP ECC or S/4HANA schema. Users must map each field to their own authorized OData entity or approved HANA view before using real source data.

## Python example

```python
from sap_knowledge.knowledge import (
    FieldMapping,
    KnowledgeRecipe,
    KnowledgeRenderer,
    MetadataMapping,
)
from sap_knowledge.models import SourceRecord

recipe = KnowledgeRecipe(
    name="synthetic_finance_posting",
    entity_set="FinancePostings",
    key_fields=("DocumentNumber", "CompanyCode", "FiscalYear"),
    title_fields=("DocumentNumber",),
    document_type="finance_posting",
    fields=(
        FieldMapping(source="DocumentNumber", label="Document number", required=True),
        FieldMapping(source="PostingDate", label="Posting date"),
        FieldMapping(source="Amount", label="Amount"),
    ),
    metadata=(
        MetadataMapping(source="CompanyCode", key="company_code", required=True),
        MetadataMapping(source="FiscalYear", key="fiscal_year", required=True),
        MetadataMapping(source="Currency", key="currency"),
    ),
)

record = SourceRecord(
    entity_set="FinancePostings",
    key={
        "DocumentNumber": "SYN-1001",
        "CompanyCode": "1000",
        "FiscalYear": "2026",
    },
    data={
        "DocumentNumber": "SYN-1001",
        "CompanyCode": "1000",
        "FiscalYear": "2026",
        "PostingDate": "2026-10-01",
        "Amount": "1250.00",
        "Currency": "USD",
        "InternalNote": "excluded synthetic placeholder",
    },
)

document = KnowledgeRenderer().render(record, recipe)

print(document.text)
print(document.citation.model_dump())
print(document.metadata)

assert "InternalNote" not in document.model_dump_json()
```

## Field selection and citations

The recipe explicitly selects approved fields. `CompanyCode`, `FiscalYear`, and `Currency` are available as structured retrieval metadata, while the document number, posting date, and amount appear in document text.

The generated citation retains the source type, entity set, and business key. When a trustworthy source provides an ETag, it can also be retained in the citation.

In an actual integration, use `recipe.select_fields` to request only the approved properties where the source supports selection. The source system must independently enforce authorization.

## Security considerations

Never dump full finance tables into free-text documents or vector stores. Unrestricted extraction can expose bank account information, personal data, confidential notes, and other fields that users are not authorized to retrieve.

An allow-list limits what the renderer includes, but it does not replace source permissions, data minimization, access controls, or appropriate redaction of sensitive approved fields.

This example contains invented records only. No SAP credentials, proprietary table definitions, or real customer data are used.
