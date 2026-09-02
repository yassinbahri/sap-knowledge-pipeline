from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sap_knowledge.errors import HanaQueryError
from sap_knowledge.knowledge import FieldMapping, KnowledgeRecipe
from sap_knowledge.sources.hana import HanaClient, HanaDataset
from sap_knowledge.sync import HanaSnapshotKnowledgePipeline, JsonlEventSink


class FakeCursor:
    def __init__(
        self,
        *,
        columns: tuple[str, ...] = ("ID", "NAME", "CATEGORY"),
        rows: tuple[tuple[Any, ...], ...] = (
            ("100", "Industrial Pump", "EQUIPMENT"),
            ("200", "Pressure Valve", "EQUIPMENT"),
            ("300", "Office Paper", "SUPPLIES"),
        ),
    ) -> None:
        self.description: Sequence[Sequence[Any]] | None = tuple((name,) for name in columns)
        self.rows = list(rows)
        self.executed: tuple[str, Sequence[Any]] | None = None
        self.closed = False

    def execute(self, operation: str, parameters: Sequence[Any] = ()) -> None:
        self.executed = (operation, parameters)

    def fetchmany(self, size: int) -> Sequence[Sequence[Any]]:
        batch = self.rows[:size]
        del self.rows[:size]
        return batch

    def close(self) -> None:
        self.closed = True


class FailingCursor(FakeCursor):
    def execute(self, operation: str, parameters: Sequence[Any] = ()) -> None:
        self.executed = (operation, parameters)
        raise RuntimeError(f"database rejected parameters {parameters!r}")


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.test_cursor = cursor
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.test_cursor

    def close(self) -> None:
        self.closed = True


class ScriptedConnection:
    def __init__(self, cursors: list[FakeCursor]) -> None:
        self.cursors = cursors

    def cursor(self) -> FakeCursor:
        return self.cursors.pop(0)

    def close(self) -> None:
        pass


def dataset() -> HanaDataset:
    return HanaDataset(
        name="PRODUCT_KNOWLEDGE",
        statement=(
            'SELECT "ID", "NAME", "CATEGORY" FROM "RAG_READ"."PRODUCT_KNOWLEDGE" '
            'WHERE "CATEGORY" = ? ORDER BY "ID"'
        ),
        key_fields=("ID",),
        parameters=("EQUIPMENT",),
    )


def test_hana_rows_are_emitted_as_bounded_source_pages() -> None:
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    client = HanaClient(connection)

    pages = list(client.pages(dataset(), page_size=2))

    assert [len(page.records) for page in pages] == [2, 1]
    assert pages[0].records[0].source_type == "hana"
    assert pages[0].records[0].entity_set == "PRODUCT_KNOWLEDGE"
    assert pages[0].records[0].key == {"ID": "100"}
    assert pages[0].records[0].data["NAME"] == "Industrial Pump"
    assert cursor.executed == (dataset().statement, ("EQUIPMENT",))
    assert cursor.closed
    assert not connection.closed


@pytest.mark.parametrize(
    "statement, message",
    [
        ('DELETE FROM "PRODUCTS"', "explicit SELECT"),
        ('SELECTED FROM "PRODUCTS"', "explicit SELECT"),
        ('SELECT * FROM "PRODUCTS"; DROP TABLE "PRODUCTS"', "exactly one"),
        ('SELECT * FROM "PRODUCTS" -- unsafe', "comments"),
    ],
)
def test_hana_dataset_rejects_non_select_or_ambiguous_sql(
    statement: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        HanaDataset(name="Products", statement=statement, key_fields=("ID",))


def test_hana_result_requires_unique_columns_and_business_keys() -> None:
    duplicate_columns = FakeCursor(columns=("ID", "ID"), rows=(("1", "1"),))
    with pytest.raises(HanaQueryError, match="duplicate column"):
        list(HanaClient(FakeConnection(duplicate_columns)).pages(dataset()))

    missing_key = FakeCursor(columns=("NAME",), rows=(("Pump",),))
    with pytest.raises(HanaQueryError, match="missing key columns"):
        list(HanaClient(FakeConnection(missing_key)).pages(dataset()))

    null_key = FakeCursor(columns=("ID", "NAME"), rows=((None, "Pump"),))
    with pytest.raises(HanaQueryError, match="null business-key"):
        list(HanaClient(FakeConnection(null_key)).pages(dataset()))


def test_hana_query_errors_do_not_expose_parameter_values() -> None:
    secret = "TOP-SECRET-COMPANY-CODE"
    unsafe_dataset = HanaDataset(
        name="PRODUCT_KNOWLEDGE",
        statement='SELECT "ID" FROM "RAG_READ"."PRODUCT_KNOWLEDGE" WHERE "SECRET" = ?',
        key_fields=("ID",),
        parameters=(secret,),
    )

    with pytest.raises(HanaQueryError) as captured:
        list(HanaClient(FakeConnection(FailingCursor())).pages(unsafe_dataset))

    message = str(captured.value)
    assert secret not in message
    assert "<redacted>" in message
    assert "1 parameter(s)" in message
    assert captured.value.__cause__ is None


def test_hana_connection_errors_do_not_expose_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password = "super-secret-password"

    def connect(**kwargs: object) -> object:
        raise RuntimeError(f"could not authenticate with {kwargs!r}")

    monkeypatch.setitem(
        sys.modules,
        "hdbcli",
        SimpleNamespace(dbapi=SimpleNamespace(connect=connect)),
    )

    with pytest.raises(HanaQueryError) as captured:
        HanaClient.connect(
            address="hana.example.test",
            port=443,
            user="RAG_READ",
            password=password,
        )

    message = str(captured.value)
    assert password not in message
    assert "hana.example.test:443" in message
    assert "RAG_READ" in message
    assert captured.value.__cause__ is None


def test_hana_client_closes_only_connections_it_owns() -> None:
    external_connection = FakeConnection(FakeCursor(rows=()))
    HanaClient(external_connection).close()
    assert not external_connection.closed

    owned_connection = FakeConnection(FakeCursor(rows=()))
    HanaClient(owned_connection, owns_connection=True).close()
    assert owned_connection.closed


def test_hana_catalog_discovers_privilege_filtered_metadata() -> None:
    schemas = FakeCursor(columns=("SCHEMA_NAME",), rows=(("RAG_READ",),))
    objects = FakeCursor(
        columns=("SCHEMA_NAME", "OBJECT_NAME", "OBJECT_TYPE"),
        rows=(("RAG_READ", "PRODUCT_KNOWLEDGE", "VIEW"),),
    )
    columns = FakeCursor(
        columns=(
            "COLUMN_NAME",
            "POSITION",
            "DATA_TYPE_NAME",
            "LENGTH",
            "SCALE",
            "IS_NULLABLE",
        ),
        rows=(
            ("PRODUCT_ID", 1, "NVARCHAR", 20, None, None),
            ("PRODUCT_NAME", 2, "NVARCHAR", 200, None, None),
        ),
    )
    catalog = HanaClient(ScriptedConnection([schemas, objects, columns])).catalog()

    assert catalog.schemas() == ("RAG_READ",)
    assert catalog.objects("RAG_READ")[0].kind == "VIEW"
    discovered_columns = catalog.columns("RAG_READ", "PRODUCT_KNOWLEDGE")
    assert discovered_columns[0].name == "PRODUCT_ID"
    assert discovered_columns[0].data_type == "NVARCHAR"
    assert discovered_columns[0].nullable is None
    assert objects.executed is not None
    assert objects.executed[1] == ("RAG_READ",)
    assert columns.executed is not None
    assert columns.executed[1] == (
        "RAG_READ",
        "PRODUCT_KNOWLEDGE",
        "RAG_READ",
        "PRODUCT_KNOWLEDGE",
    )


def test_hana_catalog_handles_empty_accessible_catalog() -> None:
    schemas = FakeCursor(columns=("SCHEMA_NAME",), rows=())
    objects = FakeCursor(
        columns=("SCHEMA_NAME", "OBJECT_NAME", "OBJECT_TYPE"),
        rows=(),
    )
    columns = FakeCursor(
        columns=(
            "COLUMN_NAME",
            "POSITION",
            "DATA_TYPE_NAME",
            "LENGTH",
            "SCALE",
            "IS_NULLABLE",
        ),
        rows=(),
    )
    catalog = HanaClient(ScriptedConnection([schemas, objects, columns])).catalog()

    assert catalog.schemas() == ()
    assert catalog.objects("RAG_READ") == ()
    assert catalog.columns("RAG_READ", "PRODUCT_KNOWLEDGE") == ()


def test_hana_catalog_errors_do_not_expose_driver_details() -> None:
    secret = "TOP-SECRET-CATALOG-VALUE"

    class SecretFailingCursor(FakeCursor):
        def execute(self, operation: str, parameters: Sequence[Any] = ()) -> None:
            raise RuntimeError(f"catalog provider leaked {secret}")

    catalog = HanaClient(FakeConnection(SecretFailingCursor())).catalog()

    with pytest.raises(HanaQueryError) as captured:
        catalog.schemas()

    assert str(captured.value) == "HANA catalog metadata query failed"
    assert secret not in str(captured.value)
    assert captured.value.__cause__ is None


def test_hana_catalog_queries_filter_and_order_accessible_metadata() -> None:
    schemas = FakeCursor(
        columns=("SCHEMA_NAME",),
        rows=(("RAG_READ",), ("SALES_READ",)),
    )
    objects = FakeCursor(
        columns=("SCHEMA_NAME", "OBJECT_NAME", "OBJECT_TYPE"),
        rows=(
            ("RAG_READ", "PRODUCTS", "TABLE"),
            ("RAG_READ", "PRODUCT_KNOWLEDGE", "VIEW"),
        ),
    )
    catalog = HanaClient(ScriptedConnection([schemas, objects])).catalog()

    assert catalog.schemas() == ("RAG_READ", "SALES_READ")
    assert [item.name for item in catalog.objects("RAG_READ")] == [
        "PRODUCTS",
        "PRODUCT_KNOWLEDGE",
    ]

    assert schemas.executed is not None
    schema_statement, schema_parameters = schemas.executed
    assert "\"HAS_PRIVILEGES\" = 'TRUE'" in schema_statement
    assert "\"SCHEMA_NAME\" <> 'SYS'" in schema_statement
    assert "\"SCHEMA_NAME\" NOT LIKE '_SYS_%'" in schema_statement
    assert 'ORDER BY "SCHEMA_NAME"' in schema_statement
    assert schema_parameters == ()

    assert objects.executed is not None
    object_statement, object_parameters = objects.executed
    assert '"SCHEMA_NAME" = ?' in object_statement
    assert "\"OBJECT_TYPE\" IN ('TABLE', 'VIEW')" in object_statement
    assert 'ORDER BY "OBJECT_TYPE", "OBJECT_NAME"' in object_statement
    assert object_parameters == ("RAG_READ",)


def test_hana_snapshot_pipeline_writes_portable_events(tmp_path: Path) -> None:
    source = HanaClient(FakeConnection(FakeCursor(rows=(("100", "Pump", "EQUIPMENT"),))))
    recipe = KnowledgeRecipe(
        name="products",
        entity_set="PRODUCT_KNOWLEDGE",
        key_fields=("ID",),
        title_fields=("NAME",),
        fields=(
            FieldMapping(source="NAME", label="Product", required=True),
            FieldMapping(source="CATEGORY", label="Category"),
        ),
    )
    path = tmp_path / "hana-events.jsonl"
    pipeline = HanaSnapshotKnowledgePipeline(
        source=source,
        dataset=dataset(),
        recipe=recipe,
        sink=JsonlEventSink(path),
        page_size=2,
    )

    result = asyncio.run(pipeline.run())
    event = json.loads(path.read_text(encoding="utf-8"))

    assert result.pages == 1
    assert result.upserts == 1
    assert result.chunks == 1
    assert event["operation"] == "upsert"
    assert event["document_id"].startswith("hana:PRODUCT_KNOWLEDGE:")
    assert event["citation"]["source_type"] == "hana"
