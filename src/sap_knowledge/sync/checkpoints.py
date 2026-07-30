"""Atomic local checkpoint persistence."""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path

from pydantic import ValidationError

from sap_knowledge.errors import CheckpointError
from sap_knowledge.sync.models import SyncCheckpoint


class FileCheckpointStore:
    """Store one checkpoint as JSON using flush, fsync, and atomic replacement."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> SyncCheckpoint | None:
        if not self.path.exists():
            return None
        try:
            return SyncCheckpoint.model_validate_json(self.path.read_bytes())
        except (OSError, ValidationError) as exc:
            raise CheckpointError(f"cannot read checkpoint {self.path}") from exc

    def save(self, checkpoint: SyncCheckpoint) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        payload = checkpoint.model_dump_json(indent=2).encode("utf-8") + b"\n"
        try:
            with temporary.open("wb") as file:
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
            with suppress(OSError):
                temporary.chmod(0o600)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise CheckpointError(f"cannot save checkpoint {self.path}") from exc
