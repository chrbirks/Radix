"""History persistence tests (tmp_path — never the real user data dir)."""

from __future__ import annotations

import json
from pathlib import Path

import mpmath

from radix.engine.values import Value
from radix.history.store import HistoryStore, StoredEntry


def test_roundtrip(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.jsonl")
    store.append("4.7k * 2", "9400")
    store.append("fix(0.7071, 1, 15)", "23170", note="Q1.15")
    entries = store.load()
    assert [e.expression for e in entries] == ["4.7k * 2", "fix(0.7071, 1, 15)"]
    assert entries[1].note == "Q1.15"
    assert entries[0].timestamp > 0


def test_corrupt_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    store = HistoryStore(path)
    store.append("1+1", "2")
    with path.open("a", encoding="utf-8") as fh:
        fh.write("not json\n")
        fh.write('{"missing": "keys"}\n')
    store.append("2+2", "4")
    assert [e.result for e in store.load()] == ["2", "4"]


def test_clear_removes_file(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.jsonl")
    store.append("1", "1")
    store.clear()
    assert store.load() == []
    store.clear()  # idempotent on a missing file


def test_load_missing_file(tmp_path: Path) -> None:
    assert HistoryStore(tmp_path / "nope.jsonl").load() == []


def test_int_value_roundtrips(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.jsonl")
    store.append("0xFF", "255", value=Value(255), prefix="")
    entries = store.load()
    assert entries[0].value is not None
    assert entries[0].value.number == 255


def test_float_value_roundtrips_bit_exact(tmp_path: Path) -> None:
    # Regression: real results must persist a reconstructable value so the
    # history panel can still reformat them (AUTO/SCI/ENG) after a restart.
    store = HistoryStore(tmp_path / "history.jsonl")
    number = mpmath.mpf("73.5e3") * mpmath.mpf("0.0272")
    store.append("73.5k*0.0272", "1999.2", value=Value(number))
    entries = store.load()
    assert entries[0].value is not None
    assert entries[0].value.number == number
    assert not entries[0].value.is_integer


def test_value_metadata_roundtrips(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.jsonl")
    store.append("period(4M)", "250n", value=Value(mpmath.mpf("2.5e-7"), prefer_si=True))
    entries = store.load()
    assert entries[0].value is not None
    assert entries[0].value.prefer_si is True


def test_no_value_roundtrips_as_none(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.jsonl")
    store.append("clear", "cleared")
    entries = store.load()
    assert entries[0].value is None


def test_load_legacy_bare_int_value(tmp_path: Path) -> None:
    # Files written by older versions stored `value` as a bare int.
    path = tmp_path / "history.jsonl"
    record = {"expression": "0xFF", "result": "255", "value": 255}
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    entries = HistoryStore(path).load()
    assert entries[0].value is not None
    assert entries[0].value.number == 255


def test_load_old_shape_without_value_or_prefix(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    record = {"expression": "0xFF", "result": "255", "note": "", "timestamp": 123.0}
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    entries = HistoryStore(path).load()
    assert len(entries) == 1
    assert entries[0].value is None
    assert entries[0].prefix == ""


def test_rewrite_persists_value_and_prefix(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.jsonl")
    store.rewrite([StoredEntry("x = 0xFF", "x ← 255", value=Value(255), prefix="x ← ")])
    entries = store.load()
    assert entries[0].value is not None
    assert entries[0].value.number == 255
    assert entries[0].prefix == "x ← "
