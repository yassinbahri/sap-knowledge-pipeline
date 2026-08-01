"""Privilege-filtered SAP HANA catalog discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sap_knowledge.errors import HanaQueryError
from sap_knowledge.sources.hana.client import Connection


@dataclass(frozen=True)
class HanaObject:
    """One accessible table or view."""

    schema: str
    name: str
    kind: str


@dataclass(frozen=True)
class HanaColumn:
    """One accessible table or view column."""

    name: str
    position: int
    data_type: str
    length: int | None
    scale: int | None
    nullable: bool | None


class HanaCatalog:
    """Inspect metadata visible to the current HANA principal."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def schemas(self, *, include_system: bool = False) -> tuple[str, ...]:
        filters = ["\"HAS_PRIVILEGES\" = 'TRUE'"]
        if not include_system:
            filters.extend(
                (
                    "\"SCHEMA_NAME\" <> 'SYS'",
                    "\"SCHEMA_NAME\" NOT LIKE '_SYS_%'",
                )
            )
        rows = self._rows(
            'SELECT "SCHEMA_NAME" FROM "SYS"."SCHEMAS" '
            f'WHERE {" AND ".join(filters)} ORDER BY "SCHEMA_NAME"'
        )
        return tuple(str(row[0]) for row in rows)

    def objects(self, schema: str) -> tuple[HanaObject, ...]:
        _validate_name(schema, "schema")
        rows = self._rows(
            'SELECT "SCHEMA_NAME", "OBJECT_NAME", "OBJECT_TYPE" '
            'FROM "SYS"."OBJECTS" '
            "WHERE \"SCHEMA_NAME\" = ? AND \"OBJECT_TYPE\" IN ('TABLE', 'VIEW') "
            'ORDER BY "OBJECT_TYPE", "OBJECT_NAME"',
            (schema,),
        )
        return tuple(
            HanaObject(schema=str(row[0]), name=str(row[1]), kind=str(row[2])) for row in rows
        )

    def columns(self, schema: str, object_name: str) -> tuple[HanaColumn, ...]:
        _validate_name(schema, "schema")
        _validate_name(object_name, "object")
        rows = self._rows(
            'SELECT "COLUMN_NAME", "POSITION", "DATA_TYPE_NAME", "LENGTH", '
            '"SCALE", "IS_NULLABLE" FROM "SYS"."TABLE_COLUMNS" '
            'WHERE "SCHEMA_NAME" = ? AND "TABLE_NAME" = ? '
            "UNION ALL "
            'SELECT "COLUMN_NAME", "POSITION", "DATA_TYPE_NAME", "LENGTH", '
            '"SCALE", NULL AS "IS_NULLABLE" FROM "SYS"."VIEW_COLUMNS" '
            'WHERE "SCHEMA_NAME" = ? AND "VIEW_NAME" = ? '
            'ORDER BY "POSITION"',
            (schema, object_name, schema, object_name),
        )
        return tuple(
            HanaColumn(
                name=str(row[0]),
                position=int(row[1]),
                data_type=str(row[2]),
                length=int(row[3]) if row[3] is not None else None,
                scale=int(row[4]) if row[4] is not None else None,
                nullable=_nullable(row[5]),
            )
            for row in rows
        )

    def _rows(
        self,
        statement: str,
        parameters: tuple[Any, ...] = (),
    ) -> tuple[tuple[Any, ...], ...]:
        cursor = self.connection.cursor()
        try:
            cursor.execute(statement, parameters)
            if cursor.description is None:
                raise HanaQueryError("HANA catalog query did not return a result set")
            rows: list[tuple[Any, ...]] = []
            while batch := cursor.fetchmany(500):
                rows.extend(tuple(row) for row in batch)
            return tuple(rows)
        finally:
            cursor.close()


def _nullable(value: Any) -> bool | None:
    if value is None:
        return None
    normalized = str(value).upper()
    if normalized == "TRUE":
        return True
    if normalized == "FALSE":
        return False
    raise HanaQueryError(f"unexpected HANA nullability value: {value!r}")


def _validate_name(value: str, label: str) -> None:
    if not value or any(character in value for character in "\r\n\0"):
        raise ValueError(f"{label} name must be non-empty and single-line")
