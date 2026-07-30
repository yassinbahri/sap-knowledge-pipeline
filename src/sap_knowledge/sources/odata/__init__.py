"""Read-only OData source support."""

from sap_knowledge.sources.odata.client import ODataClient
from sap_knowledge.sources.odata.metadata import (
    EntitySetDefinition,
    PropertyDefinition,
    ServiceMetadata,
    parse_metadata,
)
from sap_knowledge.sources.odata.payloads import ODataVersion, parse_page
from sap_knowledge.sources.odata.urls import ContinuationPolicy

__all__ = [
    "ContinuationPolicy",
    "EntitySetDefinition",
    "ODataClient",
    "ODataVersion",
    "PropertyDefinition",
    "ServiceMetadata",
    "parse_metadata",
    "parse_page",
]
