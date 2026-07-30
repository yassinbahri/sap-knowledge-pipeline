from __future__ import annotations

from pydantic import ValidationError

from sap_knowledge.errors import RecipeValidationError
from sap_knowledge.knowledge import (
    CharacterChunker,
    FieldMapping,
    KnowledgeRecipe,
    KnowledgeRenderer,
)
from sap_knowledge.models import SourceRecord


def recipe() -> KnowledgeRecipe:
    return KnowledgeRecipe(
        name="products",
        entity_set="Products",
        key_fields=("ID",),
        title_fields=("Name",),
        document_type="product",
        fields=(
            FieldMapping(source="Name", label="Product name", required=True),
            FieldMapping(source="Description", label="Description"),
            FieldMapping(source="Active", label="Active"),
            FieldMapping(source="Tags", label="Tags"),
        ),
    )


def test_renderer_allow_lists_fields_and_preserves_provenance() -> None:
    record = SourceRecord(
        entity_set="Products",
        key={"ID": "P-100"},
        data={
            "ID": "P-100",
            "Name": "Industrial Pump",
            "Description": "High-pressure pump",
            "Active": True,
            "Tags": ["fluid", "factory"],
            "InternalMargin": "43.2%",
        },
        etag='W/"10"',
    )

    document = KnowledgeRenderer().render(
        record,
        recipe(),
        source_url="https://sap.example.test/odata/Products('P-100')",
    )

    assert document.title == "Industrial Pump"
    assert "Product name: Industrial Pump" in document.text
    assert "Active: Yes" in document.text
    assert "Tags: fluid, factory" in document.text
    assert "InternalMargin" not in document.text
    assert document.citation.key == {"ID": "P-100"}
    assert document.citation.etag == 'W/"10"'
    assert document.metadata["document_type"] == "product"


def test_document_and_chunk_ids_are_deterministic() -> None:
    record = SourceRecord(
        entity_set="Products",
        key={"ID": "P-100"},
        data={"Name": "Pump", "Description": "useful details " * 20},
    )
    renderer = KnowledgeRenderer()
    document_one = renderer.render(record, recipe())
    document_two = renderer.render(record, recipe())
    chunker = CharacterChunker(max_characters=96, overlap_characters=16)

    chunks_one = chunker.split(document_one)
    chunks_two = chunker.split(document_two)

    assert document_one.id == document_two.id
    assert chunks_one == chunks_two
    assert len(chunks_one) > 1
    assert all(len(chunk.text) <= 96 for chunk in chunks_one)
    assert [chunk.ordinal for chunk in chunks_one] == list(range(len(chunks_one)))
    assert all(chunk.citation == document_one.citation for chunk in chunks_one)


def test_renderer_rejects_wrong_entity_and_required_data() -> None:
    renderer = KnowledgeRenderer()
    wrong_entity = SourceRecord(
        entity_set="Customers",
        key={"ID": "1"},
        data={"Name": "Example"},
    )
    missing_name = SourceRecord(
        entity_set="Products",
        key={"ID": "1"},
        data={"Description": "No title"},
    )

    try:
        renderer.render(wrong_entity, recipe())
    except RecipeValidationError as exc:
        assert "expects 'Products'" in str(exc)
    else:
        raise AssertionError("wrong entity set should be rejected")

    try:
        renderer.render(missing_name, recipe())
    except RecipeValidationError as exc:
        assert "required recipe field 'Name'" in str(exc)
    else:
        raise AssertionError("missing required field should be rejected")


def test_recipe_requires_unique_and_declared_fields() -> None:
    try:
        KnowledgeRecipe(
            name="invalid",
            entity_set="Products",
            key_fields=("ID",),
            title_fields=("Unknown",),
            fields=(FieldMapping(source="Name", label="Name"),),
        )
    except ValidationError as exc:
        assert "title fields must be declared" in str(exc)
    else:
        raise AssertionError("unknown title field should be rejected")


def test_recipe_select_fields_are_minimal_and_ordered() -> None:
    assert recipe().select_fields == ("ID", "Name", "Description", "Active", "Tags")
