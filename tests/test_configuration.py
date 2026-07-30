from __future__ import annotations

from pathlib import Path

import pytest

from sap_knowledge.configuration import load_config
from sap_knowledge.errors import ConfigurationError


def test_load_config_resolves_paths_relative_to_config(tmp_path: Path) -> None:
    path = tmp_path / "configuration" / "sap-knowledge.toml"
    path.parent.mkdir()
    path.write_text(
        """
[service]
root = "https://sap.example.test/odata/"
version = "4"

[pipeline]
recipe = "business_partner"
events_path = "data/events.jsonl"
checkpoint_path = "state/checkpoint.json"
max_characters = 800
overlap_characters = 80

[vector]
path = "data/qdrant"
model_cache_path = "state/models"
""".strip(),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.service.version.value == "4"
    assert config.pipeline.events_path == path.parent / "data" / "events.jsonl"
    assert config.pipeline.checkpoint_path == path.parent / "state" / "checkpoint.json"
    assert config.pipeline.chunker().max_characters == 800
    assert config.vector is not None
    assert config.vector.path == path.parent / "data" / "qdrant"
    assert config.vector.model_cache_path == path.parent / "state" / "models"


@pytest.mark.parametrize(
    "invalid_line, message",
    [
        ('password = "never-store-this"', "Extra inputs are not permitted"),
        ('root = "http://sap.example.test/odata/"', "absolute HTTPS"),
    ],
)
def test_config_rejects_plaintext_secret_and_insecure_root(
    tmp_path: Path,
    invalid_line: str,
    message: str,
) -> None:
    path = tmp_path / "sap-knowledge.toml"
    root_line = (
        invalid_line
        if invalid_line.startswith("root")
        else 'root = "https://sap.example.test/odata/"'
    )
    extra_line = "" if invalid_line.startswith("root") else invalid_line
    path.write_text(
        f"""
[service]
{root_line}
version = "4"
{extra_line}
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match=message) as captured:
        load_config(path)
    assert "never-store-this" not in str(captured.value)


def test_config_rejects_invalid_chunk_overlap(tmp_path: Path) -> None:
    path = tmp_path / "sap-knowledge.toml"
    path.write_text(
        """
[service]
root = "https://sap.example.test/odata/"
version = "4"

[pipeline]
max_characters = 100
overlap_characters = 100
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="overlap_characters"):
        load_config(path)


def test_environment_credentials_are_resolved_only_when_used(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "sap-knowledge.toml"
    path.write_text(
        """
[service]
root = "https://sap.example.test/odata/"
version = "4"
username_env = "TEST_SAP_USER"
password_env = "TEST_SAP_PASSWORD"
""".strip(),
        encoding="utf-8",
    )
    config = load_config(path)

    monkeypatch.delenv("TEST_SAP_USER", raising=False)
    monkeypatch.delenv("TEST_SAP_PASSWORD", raising=False)
    with pytest.raises(ConfigurationError, match="TEST_SAP_USER"):
        config.service.authentication()

    monkeypatch.setenv("TEST_SAP_USER", "user")
    monkeypatch.setenv("TEST_SAP_PASSWORD", "secret")
    assert config.service.authentication() is not None


def test_api_key_is_loaded_into_named_header(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "sap-knowledge.toml"
    path.write_text(
        """
[service]
root = "https://sandbox.api.sap.com/s4hanacloud/"
version = "2"
api_key_env = "TEST_SAP_API_KEY"
api_key_header = "APIKey"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_SAP_API_KEY", "secret-api-key")

    config = load_config(path)

    assert config.service.authentication() is None
    assert config.service.headers() == {"APIKey": "secret-api-key"}
