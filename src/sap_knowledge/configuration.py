"""Strict TOML configuration for the command-line interface."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from sap_knowledge.errors import ConfigurationError
from sap_knowledge.knowledge import CharacterChunker
from sap_knowledge.knowledge.recipes import KnowledgeRecipe
from sap_knowledge.recipes import BUILTIN_RECIPES
from sap_knowledge.sources.odata import ODataVersion


class ServiceSettings(BaseModel):
    """OData connection settings without credential values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    root: str = Field(min_length=1)
    version: ODataVersion
    username_env: str | None = None
    password_env: str | None = None
    bearer_token_env: str | None = None
    api_key_env: str | None = None
    api_key_header: str = "APIKey"
    timeout_seconds: float = Field(default=30, gt=0, le=300)

    @model_validator(mode="after")
    def validate_authentication(self) -> Self:
        parsed = urlsplit(self.root)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise ValueError("service.root must be an absolute HTTPS URL")
        if parsed.username or parsed.password:
            raise ValueError("service.root must not contain credentials")

        basic_values = (self.username_env, self.password_env)
        if any(basic_values) and not all(basic_values):
            raise ValueError("username_env and password_env must be configured together")
        configured_schemes = sum(
            (bool(self.username_env), bool(self.bearer_token_env), bool(self.api_key_env))
        )
        if configured_schemes > 1:
            raise ValueError("configure only one of Basic, bearer-token, or API-key authentication")
        if any(character in self.api_key_header for character in "\r\n:"):
            raise ValueError("api_key_header is not a valid HTTP header name")
        return self

    def authentication(self) -> httpx.Auth | None:
        if not self.username_env:
            return None
        username = _required_environment(self.username_env)
        password = _required_environment(self.password_env or "")
        return httpx.BasicAuth(username, password)

    def headers(self) -> dict[str, str]:
        if self.bearer_token_env:
            return {"Authorization": f"Bearer {_required_environment(self.bearer_token_env)}"}
        if self.api_key_env:
            return {self.api_key_header: _required_environment(self.api_key_env)}
        return {}


class PipelineSettings(BaseModel):
    """Recipe, chunking, output, and state settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recipe: str = "business_partner"
    events_path: Path = Path("data/events.jsonl")
    checkpoint_path: Path = Path("state/checkpoint.json")
    max_characters: int = Field(default=1200, ge=64)
    overlap_characters: int = Field(default=120, ge=0)

    @model_validator(mode="after")
    def validate_chunking(self) -> Self:
        if self.overlap_characters >= self.max_characters:
            raise ValueError("overlap_characters must be smaller than max_characters")
        return self

    def resolved(self, base_directory: Path) -> PipelineSettings:
        events = _resolve_path(base_directory, self.events_path)
        checkpoint = _resolve_path(base_directory, self.checkpoint_path)
        return self.model_copy(update={"events_path": events, "checkpoint_path": checkpoint})

    def knowledge_recipe(self) -> KnowledgeRecipe:
        try:
            return BUILTIN_RECIPES[self.recipe]
        except KeyError as exc:
            choices = ", ".join(sorted(BUILTIN_RECIPES))
            raise ConfigurationError(
                f"unknown built-in recipe {self.recipe!r}; choose one of: {choices}"
            ) from exc

    def chunker(self) -> CharacterChunker:
        return CharacterChunker(
            max_characters=self.max_characters,
            overlap_characters=self.overlap_characters,
        )


class AppConfig(BaseModel):
    """Complete CLI configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    service: ServiceSettings
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigurationError(f"required environment variable {name!r} is not set")
    return value


def _resolve_path(base_directory: Path, path: Path) -> Path:
    return path if path.is_absolute() else (base_directory / path).resolve()


def load_config(path: str | Path) -> AppConfig:
    """Load strict TOML and resolve output paths relative to that file."""

    config_path = Path(path).resolve()
    try:
        with config_path.open("rb") as file:
            raw = tomllib.load(file)
        config = AppConfig.model_validate(raw)
    except OSError as exc:
        raise ConfigurationError(f"cannot read configuration {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"invalid configuration {config_path}: {exc}") from exc
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_input=False)
        )
        raise ConfigurationError(f"invalid configuration {config_path}: {details}") from exc

    return config.model_copy(update={"pipeline": config.pipeline.resolved(config_path.parent)})
