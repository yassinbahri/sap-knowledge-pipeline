"""Synchronization event sink contracts and JSON Lines output."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from sap_knowledge.sync.models import SyncEvent


class SyncEventSink(Protocol):
    """Durably accept a complete source page before its checkpoint advances."""

    async def write(self, events: Sequence[SyncEvent]) -> None: ...


class JsonlEventSink:
    """Append portable upsert and delete events to a UTF-8 JSON Lines file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _write_sync(self, events: Sequence[SyncEvent]) -> None:
        if not events:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as file:
            for event in events:
                file.write(event.model_dump_json().encode("utf-8"))
                file.write(b"\n")
            file.flush()
            os.fsync(file.fileno())

    async def write(self, events: Sequence[SyncEvent]) -> None:
        await asyncio.to_thread(self._write_sync, events)
