from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import sap_knowledge.cli as cli_module
from sap_knowledge.cli import (
    _metadata_data,
    _parse_filters,
    _safe_http_error,
    _validate_recipe,
    run_cli,
)
from sap_knowledge.configuration import load_config
from sap_knowledge.models import SourcePage, SourceRecord
from sap_knowledge.recipes import BUSINESS_PARTNER
from sap_knowledge.sources.hana import HanaColumn, HanaObject
from sap_knowledge.sources.odata import ODataVersion
from sap_knowledge.sources.odata.metadata import (
    EntitySetDefinition,
    PropertyDefinition,
    ServiceMetadata,
)
from sap_knowledge.sync import FileCheckpointStore, SyncCheckpoint

BUSINESS_PARTNER_METADATA = b"""\
<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="1.0" xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx">
  <edmx:DataServices>
    <Schema Namespace="API_BUSINESS_PARTNER" xmlns="http://schemas.microsoft.com/ado/2008/09/edm">
      <EntityType Name="A_BusinessPartnerType">
        <Key><PropertyRef Name="BusinessPartner" /></Key>
        <Property Name="BusinessPartner" Type="Edm.String" Nullable="false" />
        <Property Name="BusinessPartnerFullName" Type="Edm.String" />
        <Property Name="BusinessPartnerCategory" Type="Edm.String" />
        <Property Name="BusinessPartnerGrouping" Type="Edm.String" />
        <Property Name="SearchTerm1" Type="Edm.String" />
        <Property Name="SearchTerm2" Type="Edm.String" />
      </EntityType>
      <EntityContainer Name="Container">
        <EntitySet Name="A_BusinessPartner"
                   EntityType="API_BUSINESS_PARTNER.A_BusinessPartnerType" />
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""


def write_config(path: Path) -> None:
    path.write_text(
        """
[service]
root = "https://sap.example.test/odata/"
version = "2"

[pipeline]
checkpoint_path = "checkpoint.json"
""".strip(),
        encoding="utf-8",
    )


def write_hana_config(path: Path) -> None:
    path.write_text(
        """
source = "hana"

[hana]
address = "hana.example.test"
port = 443
user_env = "TEST_HANA_USER"
password_env = "TEST_HANA_PASSWORD"
dataset_name = "A_BusinessPartner"
statement = "SELECT BusinessPartner, BusinessPartnerFullName FROM RAG_READ.BP"
key_fields = ["BusinessPartner"]
catalog_schema = "RAG_READ"
catalog_object = "BP"
parameters = ["1000"]
page_size = 100

[pipeline]
recipe = "business_partner"
events_path = "data/hana-events.jsonl"
""".strip(),
        encoding="utf-8",
    )


def business_partner_metadata() -> ServiceMetadata:
    properties = tuple(
        PropertyDefinition(name=name, type="Edm.String", nullable=True)
        for name in BUSINESS_PARTNER.select_fields
    )
    return ServiceMetadata(
        version=ODataVersion.V2,
        entity_sets=(
            EntitySetDefinition(
                name="A_BusinessPartner",
                entity_type="API_BUSINESS_PARTNER.A_BusinessPartnerType",
                keys=("BusinessPartner",),
                properties=properties,
                navigation_properties=("to_BusinessPartnerAddress",),
            ),
        ),
    )


def test_checkpoint_command_redacts_cursors_by_default(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "sap-knowledge.toml"
    write_config(config_path)
    config = load_config(config_path)
    FileCheckpointStore(config.pipeline.checkpoint_path).save(
        SyncCheckpoint(
            pipeline_id="safe-id",
            cursor="https://sap.example.test/odata/?$skiptoken=secret",
            delta_url="https://sap.example.test/odata/?$deltatoken=secret",
        )
    )

    assert run_cli(("--config", str(config_path), "checkpoint")) == 0

    output = capsys.readouterr().out
    assert "secret" not in output
    assert output.count("<present; redacted>") == 2


def test_checkpoint_command_reveals_cursors_only_when_requested(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "sap-knowledge.toml"
    write_config(config_path)
    config = load_config(config_path)
    FileCheckpointStore(config.pipeline.checkpoint_path).save(
        SyncCheckpoint(pipeline_id="safe-id", cursor="https://example.test/?token=visible")
    )

    assert run_cli(("--config", str(config_path), "checkpoint", "--reveal-cursors")) == 0
    output = capsys.readouterr().out
    assert "token=visible" in output


def test_metadata_validation_and_json_shape() -> None:
    metadata = business_partner_metadata()

    _validate_recipe(metadata, BUSINESS_PARTNER)
    data = _metadata_data(metadata, "A_BusinessPartner")

    assert data["version"] == "2"
    assert data["entity_sets"][0]["keys"] == ["BusinessPartner"]
    assert json.dumps(data)


def test_validate_odata_reads_only_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "sap-knowledge.toml"
    write_config(config_path)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path.endswith("/$metadata")
        return httpx.Response(200, content=BUSINESS_PARTNER_METADATA)

    real_async_client = httpx.AsyncClient

    def mock_client(**kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cli_module.httpx, "AsyncClient", mock_client)

    assert run_cli(("--config", str(config_path), "validate", "--json")) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["valid"] is True
    assert data["source"] == "odata"
    assert data["metadata_checked"] is True
    assert [request.url.path for request in requests] == ["/odata/$metadata"]


def test_validate_odata_fails_for_missing_recipe_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "sap-knowledge.toml"
    write_config(config_path)
    incomplete_metadata = BUSINESS_PARTNER_METADATA.replace(
        b'<Property Name="BusinessPartnerFullName" Type="Edm.String" />', b""
    )
    real_async_client = httpx.AsyncClient

    def mock_client(**kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(200, content=incomplete_metadata)
        )
        return real_async_client(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cli_module.httpx, "AsyncClient", mock_client)

    assert run_cli(("--config", str(config_path), "validate")) == 1
    assert "missing recipe properties" in capsys.readouterr().err


def test_metadata_filters_group_repeated_keys_and_reject_invalid_values() -> None:
    assert _parse_filters(
        ("sap_company_code=1000", "security_roles=FINANCE", "security_roles=AUDIT")
    ) == {
        "sap_company_code": "1000",
        "security_roles": ("FINANCE", "AUDIT"),
    }
    with pytest.raises(cli_module.RecipeValidationError, match="KEY=VALUE"):
        _parse_filters(("security_roles=",))


def test_http_diagnostics_remove_credentials_query_and_response_body() -> None:
    request = httpx.Request(
        "GET", "https://user:password@sap.example.test/odata/?$skiptoken=secret"
    )
    response = httpx.Response(503, text="sensitive provider response", request=request)
    error = httpx.HTTPStatusError("unsafe original message", request=request, response=response)

    message = _safe_http_error(error)

    assert message == "HTTP 503 for GET https://sap.example.test/odata/"
    assert "password" not in message
    assert "skiptoken" not in message
    assert "sensitive" not in message


def test_sync_command_runs_config_to_jsonl_and_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "sap-knowledge.toml"
    write_config(config_path)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/$metadata"):
            return httpx.Response(200, content=BUSINESS_PARTNER_METADATA)
        return httpx.Response(
            200,
            json={
                "d": {
                    "results": [
                        {
                            "BusinessPartner": "1000001",
                            "BusinessPartnerFullName": "Northwind Components",
                            "BusinessPartnerCategory": "2",
                        }
                    ]
                }
            },
        )

    real_async_client = httpx.AsyncClient

    def mock_client(**kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cli_module.httpx, "AsyncClient", mock_client)

    assert run_cli(("--config", str(config_path), "sync")) == 0

    result = json.loads(capsys.readouterr().out)
    events = [
        json.loads(line)
        for line in (tmp_path / "data" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    checkpoint = FileCheckpointStore(tmp_path / "checkpoint.json").load()

    assert result["upserts"] == 1
    assert events[0]["operation"] == "upsert"
    assert "Northwind Components" in events[0]["chunks"][0]["text"]
    assert checkpoint is not None and checkpoint.complete is True
    assert requests[0].url.path.endswith("/$metadata")
    assert requests[1].url.params["$select"].startswith("BusinessPartner,")


def test_hana_sync_command_runs_config_to_jsonl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "hana.toml"
    write_hana_config(config_path)
    monkeypatch.setenv("TEST_HANA_USER", "RAG_READ")
    monkeypatch.setenv("TEST_HANA_PASSWORD", "secret")
    connections: list[object] = []

    class FakeHanaClient:
        def __init__(self) -> None:
            self.closed = False

        @classmethod
        def connect(cls, **kwargs: object) -> FakeHanaClient:
            assert kwargs["address"] == "hana.example.test"
            assert kwargs["user"] == "RAG_READ"
            assert kwargs["password"] == "secret"
            connection = cls()
            connections.append(connection)
            return connection

        def pages(self, dataset: object, *, page_size: int) -> list[SourcePage]:
            assert page_size == 100
            return [
                SourcePage(
                    records=(
                        SourceRecord(
                            source_type="hana",
                            entity_set="A_BusinessPartner",
                            key={"BusinessPartner": "1000001"},
                            data={
                                "BusinessPartner": "1000001",
                                "BusinessPartnerFullName": "Northwind Components",
                                "BusinessPartnerCategory": "2",
                            },
                        ),
                    )
                )
            ]

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(cli_module, "HanaClient", FakeHanaClient)

    assert run_cli(("--config", str(config_path), "sync")) == 0

    result = json.loads(capsys.readouterr().out)
    events = [
        json.loads(line)
        for line in (tmp_path / "data" / "hana-events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert result["upserts"] == 1
    assert events[0]["citation"]["source_type"] == "hana"
    assert events[0]["citation"]["entity_set"] == "A_BusinessPartner"
    assert connections and connections[0].closed is True


def test_validate_hana_uses_catalog_without_executing_business_select(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "hana.toml"
    write_hana_config(config_path)
    monkeypatch.setenv("TEST_HANA_USER", "RAG_READ")
    monkeypatch.setenv("TEST_HANA_PASSWORD", "secret")
    clients: list[object] = []

    class FakeCatalog:
        def columns(self, schema: str, object_name: str) -> tuple[HanaColumn, ...]:
            assert (schema, object_name) == ("RAG_READ", "BP")
            return tuple(
                HanaColumn(
                    name=name,
                    position=position,
                    data_type="NVARCHAR",
                    length=100,
                    scale=None,
                    nullable=True,
                )
                for position, name in enumerate(BUSINESS_PARTNER.select_fields, start=1)
            )

    class FakeHanaClient:
        def __init__(self) -> None:
            self.closed = False

        @classmethod
        def connect(cls, **kwargs: object) -> FakeHanaClient:
            assert kwargs["password"] == "secret"
            client = cls()
            clients.append(client)
            return client

        def catalog(self) -> FakeCatalog:
            return FakeCatalog()

        def pages(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("validate must not execute the business SELECT")

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(cli_module, "HanaClient", FakeHanaClient)

    assert run_cli(("--config", str(config_path), "validate", "--json")) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["metadata_checked"] is True
    assert data["catalog_schema"] == "RAG_READ"
    assert clients and clients[0].closed is True


def test_validate_hana_reports_skipped_catalog_check_without_lineage(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "hana.toml"
    write_hana_config(config_path)
    configured = config_path.read_text(encoding="utf-8")
    configured = configured.replace('catalog_schema = "RAG_READ"\n', "")
    configured = configured.replace('catalog_object = "BP"\n', "")
    config_path.write_text(configured, encoding="utf-8")

    assert run_cli(("--config", str(config_path), "validate", "--json")) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["valid"] is True
    assert data["metadata_checked"] is False
    assert "not configured" in data["metadata_note"]


def test_validate_hana_fails_when_catalog_key_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "hana.toml"
    write_hana_config(config_path)
    monkeypatch.setenv("TEST_HANA_USER", "RAG_READ")
    monkeypatch.setenv("TEST_HANA_PASSWORD", "secret")

    class FakeCatalog:
        def columns(self, schema: str, object_name: str) -> tuple[HanaColumn, ...]:
            return ()

    class FakeHanaClient:
        @classmethod
        def connect(cls, **kwargs: object) -> FakeHanaClient:
            return cls()

        def catalog(self) -> FakeCatalog:
            return FakeCatalog()

        def close(self) -> None:
            pass

    monkeypatch.setattr(cli_module, "HanaClient", FakeHanaClient)

    assert run_cli(("--config", str(config_path), "validate")) == 1
    error = capsys.readouterr().err
    assert "missing recipe key columns: BusinessPartner" in error
    assert "secret" not in error


def test_validate_hana_redacts_unexpected_catalog_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "hana.toml"
    write_hana_config(config_path)
    monkeypatch.setenv("TEST_HANA_USER", "RAG_READ")
    monkeypatch.setenv("TEST_HANA_PASSWORD", "secret-password")

    class FakeCatalog:
        def columns(self, schema: str, object_name: str) -> tuple[HanaColumn, ...]:
            raise RuntimeError("driver leaked secret-password and SELECT parameters")

    class FakeHanaClient:
        @classmethod
        def connect(cls, **kwargs: object) -> FakeHanaClient:
            return cls()

        def catalog(self) -> FakeCatalog:
            return FakeCatalog()

        def close(self) -> None:
            pass

    monkeypatch.setattr(cli_module, "HanaClient", FakeHanaClient)

    assert run_cli(("--config", str(config_path), "validate")) == 1
    error = capsys.readouterr().err
    assert "HANA metadata validation failed" in error
    assert "secret-password" not in error
    assert "SELECT" not in error


def test_hana_sync_rejects_force_full_flag(tmp_path: Path) -> None:
    config_path = tmp_path / "hana.toml"
    write_hana_config(config_path)

    assert run_cli(("--config", str(config_path), "sync", "--force-full")) == 1


def test_hana_inspect_lists_schemas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "hana.toml"
    write_hana_config(config_path)
    monkeypatch.setenv("TEST_HANA_USER", "RAG_READ")
    monkeypatch.setenv("TEST_HANA_PASSWORD", "secret")

    class FakeCatalog:
        def schemas(self, *, include_system: bool = False) -> tuple[str, ...]:
            assert include_system is False
            return ("RAG_READ",)

    class FakeHanaClient:
        @classmethod
        def connect(cls, **kwargs: object) -> FakeHanaClient:
            assert kwargs["password"] == "secret"
            return cls()

        def catalog(self) -> FakeCatalog:
            return FakeCatalog()

        def close(self) -> None:
            pass

    monkeypatch.setattr(cli_module, "HanaClient", FakeHanaClient)

    assert run_cli(("--config", str(config_path), "inspect")) == 0

    output = capsys.readouterr().out
    assert "HANA catalog" in output
    assert "RAG_READ" in output
    assert "secret" not in output


def test_hana_inspect_object_columns_as_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "hana.toml"
    write_hana_config(config_path)
    monkeypatch.setenv("TEST_HANA_USER", "RAG_READ")
    monkeypatch.setenv("TEST_HANA_PASSWORD", "secret")

    class FakeCatalog:
        def columns(self, schema: str, object_name: str) -> tuple[HanaColumn, ...]:
            assert schema == "RAG_READ"
            assert object_name == "BP"
            return (
                HanaColumn(
                    name="BusinessPartner",
                    position=1,
                    data_type="NVARCHAR",
                    length=10,
                    scale=None,
                    nullable=False,
                ),
            )

    class FakeHanaClient:
        @classmethod
        def connect(cls, **kwargs: object) -> FakeHanaClient:
            return cls()

        def catalog(self) -> FakeCatalog:
            return FakeCatalog()

        def close(self) -> None:
            pass

    monkeypatch.setattr(cli_module, "HanaClient", FakeHanaClient)

    assert (
        run_cli(
            (
                "--config",
                str(config_path),
                "inspect",
                "--schema",
                "RAG_READ",
                "--object",
                "BP",
                "--json",
            )
        )
        == 0
    )

    data = json.loads(capsys.readouterr().out)
    assert data["source"] == "hana"
    assert data["schema"] == "RAG_READ"
    assert data["object"] == "BP"
    assert data["columns"][0]["name"] == "BusinessPartner"


def test_hana_inspect_rejects_object_without_schema(tmp_path: Path) -> None:
    config_path = tmp_path / "hana.toml"
    write_hana_config(config_path)

    assert run_cli(("--config", str(config_path), "inspect", "--object", "BP")) == 1


def test_hana_inspect_lists_schema_objects_as_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "hana.toml"
    write_hana_config(config_path)
    monkeypatch.setenv("TEST_HANA_USER", "RAG_READ")
    monkeypatch.setenv("TEST_HANA_PASSWORD", "secret")

    class FakeCatalog:
        def objects(self, schema: str) -> tuple[HanaObject, ...]:
            assert schema == "RAG_READ"
            return (HanaObject(schema="RAG_READ", name="BP", kind="VIEW"),)

    class FakeHanaClient:
        @classmethod
        def connect(cls, **kwargs: object) -> FakeHanaClient:
            return cls()

        def catalog(self) -> FakeCatalog:
            return FakeCatalog()

        def close(self) -> None:
            pass

    monkeypatch.setattr(cli_module, "HanaClient", FakeHanaClient)

    assert run_cli(("--config", str(config_path), "inspect", "--schema", "RAG_READ", "--json")) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["objects"] == [{"schema": "RAG_READ", "name": "BP", "kind": "VIEW"}]
