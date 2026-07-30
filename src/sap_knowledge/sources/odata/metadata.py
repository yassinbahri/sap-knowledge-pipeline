"""Small, read-only EDMX metadata inspector for OData V2 and V4 services."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

from lxml import etree

from sap_knowledge.errors import InvalidMetadataError
from sap_knowledge.sources.odata.payloads import ODataVersion


@dataclass(frozen=True)
class PropertyDefinition:
    """One structural property declared by an OData entity type."""

    name: str
    type: str
    nullable: bool
    max_length: str | None = None


@dataclass(frozen=True)
class EntitySetDefinition:
    """An addressable entity set and its resolved structural definition."""

    name: str
    entity_type: str
    keys: tuple[str, ...]
    properties: tuple[PropertyDefinition, ...]
    navigation_properties: tuple[str, ...]

    def property(self, name: str) -> PropertyDefinition:
        """Return a named property or raise KeyError."""

        return next(prop for prop in self.properties if prop.name == name)


@dataclass(frozen=True)
class ServiceMetadata:
    """The entity sets discovered in one EDMX service document."""

    version: ODataVersion
    entity_sets: tuple[EntitySetDefinition, ...]

    def entity_set(self, name: str) -> EntitySetDefinition:
        """Return a named entity set or raise KeyError."""

        return next(entity for entity in self.entity_sets if entity.name == name)


def _children(element: etree._Element, local_name: str) -> Iterable[etree._Element]:
    result = element.xpath(f"./*[local-name()='{local_name}']")
    return cast(list[etree._Element], result)


def _detect_version(root: etree._Element) -> ODataVersion:
    version = root.get("Version", "")
    if version.startswith("4"):
        return ODataVersion.V4
    return ODataVersion.V2


def parse_metadata(content: bytes | str) -> ServiceMetadata:
    """Parse the subset of EDMX needed for safe entity-set inspection."""

    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    try:
        raw = content.encode() if isinstance(content, str) else content
        root = etree.fromstring(raw, parser=parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise InvalidMetadataError("metadata is not valid XML") from exc

    entity_types: dict[
        str,
        tuple[tuple[str, ...], tuple[PropertyDefinition, ...], tuple[str, ...]],
    ] = {}

    for schema in root.xpath("//*[local-name()='Schema']"):
        namespace = schema.get("Namespace")
        if not namespace:
            continue
        for entity_type in _children(schema, "EntityType"):
            name = entity_type.get("Name")
            if not name:
                continue
            key_elements = entity_type.xpath(
                "./*[local-name()='Key']/*[local-name()='PropertyRef']"
            )
            keys = tuple(key.get("Name") for key in key_elements if key.get("Name") is not None)
            properties = tuple(
                PropertyDefinition(
                    name=prop.get("Name", ""),
                    type=prop.get("Type", ""),
                    nullable=prop.get("Nullable", "true").lower() != "false",
                    max_length=prop.get("MaxLength"),
                )
                for prop in _children(entity_type, "Property")
                if prop.get("Name")
            )
            navigation = tuple(
                nav.get("Name", "")
                for nav in _children(entity_type, "NavigationProperty")
                if nav.get("Name")
            )
            entity_types[f"{namespace}.{name}"] = (keys, properties, navigation)

    entity_sets: list[EntitySetDefinition] = []
    for entity_set in root.xpath("//*[local-name()='EntityContainer']/*[local-name()='EntitySet']"):
        name = entity_set.get("Name")
        entity_type = entity_set.get("EntityType")
        if not name or not entity_type:
            continue
        definition = entity_types.get(entity_type)
        if definition is None:
            raise InvalidMetadataError(
                f"entity set {name!r} references unknown type {entity_type!r}"
            )
        keys, properties, navigation = definition
        entity_sets.append(
            EntitySetDefinition(
                name=name,
                entity_type=entity_type,
                keys=keys,
                properties=properties,
                navigation_properties=navigation,
            )
        )

    if not entity_sets:
        raise InvalidMetadataError("metadata does not declare any entity sets")

    return ServiceMetadata(version=_detect_version(root), entity_sets=tuple(entity_sets))
