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
    return _elements(element, f"./*[local-name()='{local_name}']")


def _elements(element: etree._Element, expression: str) -> list[etree._Element]:
    """Narrow an XPath expression that is known to select only elements."""

    return cast(list[etree._Element], element.xpath(expression))


def _attribute(
    element: etree._Element,
    name: str,
    default: str | None = None,
) -> str | None:
    """Return an XML attribute as text with a precise static type."""

    value = element.get(name)
    return str(value) if value is not None else default


def _detect_version(root: etree._Element) -> ODataVersion:
    version = _attribute(root, "Version", "") or ""
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

    for schema in _elements(root, "//*[local-name()='Schema']"):
        namespace = _attribute(schema, "Namespace")
        if not namespace:
            continue
        for entity_type_element in _children(schema, "EntityType"):
            name = _attribute(entity_type_element, "Name")
            if not name:
                continue
            key_elements = _elements(
                entity_type_element, "./*[local-name()='Key']/*[local-name()='PropertyRef']"
            )
            keys = tuple(
                key_name
                for key in key_elements
                if (key_name := _attribute(key, "Name")) is not None
            )
            properties = tuple(
                PropertyDefinition(
                    name=_attribute(prop, "Name", "") or "",
                    type=_attribute(prop, "Type", "") or "",
                    nullable=(_attribute(prop, "Nullable", "true") or "true").lower() != "false",
                    max_length=_attribute(prop, "MaxLength"),
                )
                for prop in _children(entity_type_element, "Property")
                if _attribute(prop, "Name")
            )
            navigation = tuple(
                _attribute(nav, "Name", "") or ""
                for nav in _children(entity_type_element, "NavigationProperty")
                if _attribute(nav, "Name")
            )
            entity_types[f"{namespace}.{name}"] = (keys, properties, navigation)

    entity_sets: list[EntitySetDefinition] = []
    for entity_set in _elements(
        root,
        "//*[local-name()='EntityContainer']/*[local-name()='EntitySet']",
    ):
        name = _attribute(entity_set, "Name")
        entity_type = _attribute(entity_set, "EntityType")
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
