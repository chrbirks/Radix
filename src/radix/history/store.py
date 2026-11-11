"""Append-only JSONL history in the platformdirs user-data directory.

Each line: {"expression": ..., "result": ..., "note": ..., "timestamp": ...,
"value": ..., "prefix": ...}. Mostly the display text is persisted — recalled
entries re-evaluate through the current session, so stored text can never
disagree with the engine. `value` is the exception: the full result value is
also persisted (alongside `prefix`, the assignment badge text) via
`value_to_json`, so entries can still reformat on a base/notation change after
a restart — reals round-trip bit-exact, same as session state does. Older
files stored `value` as a bare int (int-valued entries only); those still load.
Corrupt lines are skipped, never fatal; an unreadable, undecodable or
missing file loads as empty. Writes (`append`/`remove`/`rewrite`/`clear`) still
raise OSError so the caller can report the failure instead of silently losing
it. `remove` and `rewrite` replace the file atomically.
"""

from __future__ import annotations

import json
import os
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


def _dump(entry: StoredEntry) -> str:
    """One JSONL line for ``entry``."""
    return json.dumps(
        {
            "expression": entry.expression,
            "result": entry.result,
            "note": entry.note,
            "timestamp": entry.timestamp,
            "value": value_to_json(entry.value) if entry.value is not None else None,
            "prefix": entry.prefix,
        }
    )


def default_path() -> Path:
    return Path(platformdirs.user_data_dir("radix", appauthor=False)) / "history.jsonl"


class HistoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_path()

    def load(self) -> list[StoredEntry]:
        try:
            # errors="replace": a truncated multi-byte char (crash mid-write)
            # corrupts only its own line instead of discarding the whole file.
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            # Missing, unreadable (permissions) or a directory: load is called
            # at start-up, so never let the history file block the app.
            return []
        entries: list[StoredEntry] = []
        for line in text.splitlines():
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
        timestamp: float | None = None,
    ) -> StoredEntry:
        """Append one entry and return it exactly as stored.

        The caller keeps the returned entry (its timestamp in particular):
        that is what ``remove`` later matches against the file.
        """
        entry = StoredEntry(
            expression,
            result,
            note,
            time.time() if timestamp is None else timestamp,
            value=value,
            prefix=prefix,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(_dump(entry) + "\n")
        return entry

    def remove(self, entry: StoredEntry) -> None:
        """Delete the one line holding ``entry``, leaving every other line as is.

        Lines are matched by timestamp and expression and otherwise passed
        through untouched — including ones this version cannot parse and the
        ones older than the ``MAX_LOADED_ENTRIES`` a caller ever sees. Deleting
        used to rewrite the file from the caller's list, which erased both.
        """
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return  # nothing stored, nothing to remove
        for i in range(len(lines) - 1, -1, -1):  # newest first: duplicates are recent
            try:
                raw = json.loads(lines[i])
                hit = (
                    raw["expression"] == entry.expression
                    and float(raw.get("timestamp", 0.0)) == entry.timestamp
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            if hit:
                del lines[i]
                self._replace(lines)
                return

    def rewrite(self, entries: list[StoredEntry]) -> None:
        """Replace the file's contents with exactly ``entries``."""
        self._replace([_dump(entry) for entry in entries])

    def _replace(self, lines: list[str]) -> None:
        """Swap in new contents atomically: a crash mid-write keeps the old file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        scratch = self.path.with_name(self.path.name + ".tmp")
        try:
            with scratch.open("w", encoding="utf-8") as fh:
                fh.writelines(line + "\n" for line in lines)
            os.replace(scratch, self.path)
        finally:
            scratch.unlink(missing_ok=True)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
