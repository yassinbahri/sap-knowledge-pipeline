from __future__ import annotations

import pytest

from sap_knowledge.errors import MissingEntityKeyError
from sap_knowledge.sources.odata import ODataVersion, parse_page


def test_parse_v4_page_with_upsert_deletion_and_links() -> None:
    page = parse_page(
        {
            "value": [
                {"ID": "100", "Text": "Pump failed", "@odata.etag": 'W/"1"'},
                {"ID": "101", "@removed": {"reason": "deleted"}},
            ],
            "@odata.nextLink": "Notifications?$skiptoken=next",
            "@odata.deltaLink": "Notifications?$deltatoken=delta",
        },
        version=ODataVersion.V4,
        entity_set="Notifications",
        key_fields=("ID",),
    )

    assert page.records[0].key == {"ID": "100"}
    assert page.records[0].data == {"ID": "100", "Text": "Pump failed"}
    assert page.records[0].etag == 'W/"1"'
    assert page.deletions[0].key == {"ID": "101"}
    assert page.deletions[0].reason == "deleted"
    assert page.next_url == "Notifications?$skiptoken=next"
    assert page.delta_url == "Notifications?$deltatoken=delta"


def test_parse_v2_page() -> None:
    page = parse_page(
        {
            "d": {
                "results": [
                    {
                        "__metadata": {"etag": 'W/"2"', "type": "SAP.Notification"},
                        "ID": "200",
                        "Text": "Valve replaced",
                    }
                ],
                "__next": "Notifications?$skiptoken=second",
            }
        },
        version=ODataVersion.V2,
        entity_set="Notifications",
        key_fields=("ID",),
    )

    assert page.records[0].data == {"ID": "200", "Text": "Valve replaced"}
    assert page.records[0].etag == 'W/"2"'
    assert page.next_url == "Notifications?$skiptoken=second"


def test_parse_v2_direct_collection_envelope() -> None:
    page = parse_page(
        {
            "d": [
                {
                    "__metadata": {"type": "Northwind.Product"},
                    "ProductID": 1,
                    "ProductName": "Chai",
                }
            ]
        },
        version=ODataVersion.V2,
        entity_set="Products",
        key_fields=("ProductID",),
    )

    assert page.records[0].key == {"ProductID": 1}
    assert page.records[0].data["ProductName"] == "Chai"


def test_missing_configured_key_is_rejected() -> None:
    with pytest.raises(MissingEntityKeyError, match="ID"):
        parse_page(
            {"value": [{"Text": "Missing key"}]},
            version=ODataVersion.V4,
            entity_set="Notifications",
            key_fields=("ID",),
        )
