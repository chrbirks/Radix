"""Append-only JSONL history in the platformdirs user-data directory.

Each line: {"expression": ..., "result": ..., "note": ..., "timestamp": ...,
"value": ..., "prefix": ...}. Mostly the display text is persisted — recalled
entries re-evaluate through the current session, so stored text can never
disagree with the engine. `value` is the exception: the full result value is
also persisted (alongside `prefix`, the assignment badge text) via
`value_to_json`, so entries can still reformat on a base/notation change after
a restart — reals round-trip bit-exact, same as session state does. Older
files stored `value` as a bare int (int-valued entries only); those still load.
Corrupt lines are skipped, never fatal.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import platformdirs

from radix.engine.values import Value, value_from_json, value_to_json

MAX_LOADED_ENTRIES = 500


@dataclass(frozen=True)
class StoredEntry:
    expression: str
    result: str
    note: str = ""
    timestamp: float = 0.0
    value: Value | None = None
    prefix: str = ""


def _value_from_raw(raw_value: object) -> Value | None:
    """Reconstruct a persisted value, accepting the legacy bare-int shape."""
    if raw_value is None:
        return None
    if isinstance(raw_value, int) and not isinstance(raw_value, bool):
        return Value(raw_value)  # legacy files stored the raw integer
    if isinstance(raw_value, dict):
        return value_from_json(raw_value)
    raise ValueError(f"unrecognized value shape: {type(raw_value).__name__}")


def default_path() -> Path:
    return Path(platformdirs.user_data_dir("radix", appauthor=False)) / "history.jsonl"


class HistoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_path()

    def load(self) -> list[StoredEntry]:
        if not self.path.exists():
            return []
        entries: list[StoredEntry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                raw = json.loads(line)
                entries.append(
                    StoredEntry(
                        expression=str(raw["expression"]),
                        result=str(raw["result"]),
                        note=str(raw.get("note", "")),
                        timestamp=float(raw.get("timestamp", 0.0)),
                        value=_value_from_raw(raw.get("value")),
                        prefix=str(raw.get("prefix", "")),
                    )
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue  # skip corrupt lines rather than losing the file
        return entries[-MAX_LOADED_ENTRIES:]

    def append(
        self,
        expression: str,
        result: str,
        note: str = "",
        value: Value | None = None,
        prefix: str = "",
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "expression": expression,
            "result": result,
            "note": note,
            "timestamp": time.time(),
            "value": value_to_json(value) if value is not None else None,
            "prefix": prefix,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    def rewrite(self, entries: list[StoredEntry]) -> None:
        """Replace the file's contents (after deleting an entry from the UI)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as fh:
            for entry in entries:
                record = {
                    "expression": entry.expression,
                    "result": entry.result,
                    "note": entry.note,
                    "timestamp": entry.timestamp,
                    "value": value_to_json(entry.value) if entry.value is not None else None,
                    "prefix": entry.prefix,
                }
                fh.write(json.dumps(record) + "\n")

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
