"""Conservative knowledge recipe for SAP Business Partner master data."""

from sap_knowledge.knowledge.recipes import FieldMapping, KnowledgeRecipe

BUSINESS_PARTNER = KnowledgeRecipe(
    name="sap-business-partner",
    entity_set="A_BusinessPartner",
    key_fields=("BusinessPartner",),
    title_fields=("BusinessPartnerFullName", "BusinessPartner"),
    document_type="sap_business_partner",
    fields=(
        FieldMapping(source="BusinessPartnerFullName", label="Business partner name"),
        FieldMapping(source="BusinessPartner", label="Business partner ID", required=True),
        FieldMapping(source="BusinessPartnerCategory", label="Category"),
        FieldMapping(source="BusinessPartnerGrouping", label="Grouping"),
        FieldMapping(source="SearchTerm1", label="Search term"),
        FieldMapping(source="SearchTerm2", label="Additional search term"),
    ),
)
