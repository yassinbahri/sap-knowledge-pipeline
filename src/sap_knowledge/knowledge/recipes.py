"""Declarative field allow-lists for knowledge generation."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FieldMapping(BaseModel):
    """Map one flat OData property to a human-readable document field."""

    model_config = ConfigDict(frozen=True)

    source: str = Field(min_length=1)
    label: str = Field(min_length=1)
    required: bool = False
    include_empty: bool = False


class KnowledgeRecipe(BaseModel):
    """Describe which source data may become retrievable knowledge."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    entity_set: str = Field(min_length=1)
    key_fields: tuple[str, ...] = Field(min_length=1)
    title_fields: tuple[str, ...] = Field(min_length=1)
    fields: tuple[FieldMapping, ...] = Field(min_length=1)
    document_type: str = Field(default="sap_entity", min_length=1)

    @model_validator(mode="after")
    def validate_field_references(self) -> KnowledgeRecipe:
        sources = [field.source for field in self.fields]
        if len(sources) != len(set(sources)):
            raise ValueError("recipe field sources must be unique")

        missing_titles = set(self.title_fields) - set(sources)
        if missing_titles:
            missing = ", ".join(sorted(missing_titles))
            raise ValueError(f"title fields must be declared in fields: {missing}")
        return self

    @property
    def select_fields(self) -> tuple[str, ...]:
        """Return the minimal stable OData selection required by this recipe."""

        selected = dict.fromkeys((*self.key_fields, *(field.source for field in self.fields)))
        return tuple(selected)
