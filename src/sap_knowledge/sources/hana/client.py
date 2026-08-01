"""Read-only SAP HANA query source."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, Self

from sap_knowledge.errors import HanaQueryError, OptionalDependencyError
from sap_knowledge.models import SourcePage, SourceRecord

if TYPE_CHECKING:
    from sap_knowledge.sources.hana.catalog import HanaCatalog


class Cursor(Protocol):
    """Small DB-API cursor surface used by the HANA source."""

    description: Sequence[Sequence[Any]] | None

    def execute(self, operation: str, parameters: Sequence[Any] = ()) -> Any: ...

    def fetchmany(self, size: int) -> Sequence[Sequence[Any]]: ...

    def close(self) -> Any: ...


class Connection(Protocol):
    """Small DB-API connection surface used by the HANA source."""

    def cursor(self) -> Cursor: ...

    def close(self) -> Any: ...


@dataclass(frozen=True)
class HanaDataset:
    """An explicit SELECT and the business-key contract for its result rows."""

    name: str
    statement: str
    key_fields: tuple[str, ...]
    parameters: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or any(character in self.name for character in "\r\n"):
            raise ValueError("dataset name must be non-empty and single-line")
        if not self.key_fields or any(not field for field in self.key_fields):
            raise ValueError("key_fields must contain at least one non-empty column name")
        if len(self.key_fields) != len(set(self.key_fields)):
            raise ValueError("key_fields must be unique")

        statement = self.statement.strip()
        if not statement:
            raise ValueError("statement must not be empty")
        if re.match(r"SELECT\b", statement, flags=re.IGNORECASE) is None:
            raise ValueError("HANA datasets must use an explicit SELECT statement")
        if ";" in statement:
            raise ValueError("statement must contain exactly one SQL statement without a semicolon")
        if "--" in statement or "/*" in statement or "*/" in statement:
            raise ValueError("SQL comments are not allowed in a HANA dataset statement")


class HanaClient:
    """Stream explicit HANA SELECT results as provider-neutral source pages."""

    def __init__(self, connection: Connection, *, owns_connection: bool = False) -> None:
        self.connection = connection
        self.owns_connection = owns_connection
        self._closed = False

    @classmethod
    def connect(
        cls,
        *,
        address: str,
        port: int,
        user: str,
        password: str,
        connect_timeout_ms: int = 15_000,
    ) -> HanaClient:
        """Open a certificate-validated encrypted connection using optional hdbcli."""

        try:
            from hdbcli import dbapi
        except ImportError as exc:
            raise OptionalDependencyError(
                "SAP HANA support is not installed; use `pip install sap-knowledge-pipeline[hana]`"
            ) from exc

        connection = dbapi.connect(
            address=address,
            port=port,
            user=user,
            password=password,
            encrypt=True,
            sslValidateCertificate=True,
            connecttimeout=connect_timeout_ms,
        )
        return cls(connection, owns_connection=True)

    def __enter__(self) -> Self:
        if self._closed:
            raise RuntimeError("HANA client is closed")
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed and self.owns_connection:
            self.connection.close()
        self._closed = True

    def catalog(self) -> HanaCatalog:
        """Return privilege-filtered metadata discovery for this connection."""

        if self._closed:
            raise RuntimeError("HANA client is closed")
        from sap_knowledge.sources.hana.catalog import HanaCatalog

        return HanaCatalog(self.connection)

    def pages(self, dataset: HanaDataset, *, page_size: int = 500) -> Iterator[SourcePage]:
        """Execute one SELECT and fetch its rows in bounded in-memory pages."""

        if self._closed:
            raise RuntimeError("HANA client is closed")
        if page_size <= 0:
            raise ValueError("page_size must be positive")

        cursor = self.connection.cursor()
        try:
            cursor.execute(dataset.statement, dataset.parameters)
            columns = _column_names(cursor.description)
            missing_keys = set(dataset.key_fields) - set(columns)
            if missing_keys:
                missing = ", ".join(sorted(missing_keys))
                raise HanaQueryError(f"HANA result is missing key columns: {missing}")

            while rows := cursor.fetchmany(page_size):
                records = tuple(_record(dataset, columns, row) for row in rows)
                yield SourcePage(records=records)
        finally:
            cursor.close()


def _column_names(description: Sequence[Sequence[Any]] | None) -> tuple[str, ...]:
    if not description:
        raise HanaQueryError("HANA SELECT did not return a result-set description")
    columns = tuple(str(column[0]) for column in description)
    duplicates = sorted({column for column in columns if columns.count(column) > 1})
    if duplicates:
        names = ", ".join(duplicates)
        raise HanaQueryError(f"HANA result contains duplicate column names: {names}")
    return columns


def _record(
    dataset: HanaDataset,
    columns: tuple[str, ...],
    values: Sequence[Any],
) -> SourceRecord:
    if len(values) != len(columns):
        raise HanaQueryError("HANA row length does not match its result-set description")
    data: Mapping[str, Any] = dict(zip(columns, values, strict=True))
    key = {field: data[field] for field in dataset.key_fields}
    empty_keys = [field for field, value in key.items() if value is None]
    if empty_keys:
        names = ", ".join(empty_keys)
        raise HanaQueryError(f"HANA result has null business-key columns: {names}")
    return SourceRecord(
        source_type="hana",
        entity_set=dataset.name,
        key=key,
        data=dict(data),
    )
