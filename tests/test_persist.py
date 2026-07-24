"""Round-trip tests for persisting variables/csrs/ans across restarts."""

from __future__ import annotations

import json

import mpmath
import pytest

from radix.engine.csr import Csr, CsrField, csr_from_json, csr_to_json
from radix.engine.values import Value, value_from_json, value_to_json
from radix.session import Session


def test_value_to_json_roundtrips_int() -> None:
    v = Value(42, declared_width=8, prefer_si=True, note="a note")
    restored = value_from_json(json.loads(json.dumps(value_to_json(v))))
    assert restored.number == 42
    assert isinstance(restored.number, int)
    assert restored.declared_width == 8
    assert restored.prefer_si is True
    assert restored.note == "a note"
    assert restored.csr is None
    assert restored.viz is None


def test_value_to_json_roundtrips_real_exactly() -> None:
    x = mpmath.mpf(1) / mpmath.mpf(3)
    v = Value(x)
    restored = value_from_json(json.loads(json.dumps(value_to_json(v))))
    assert not isinstance(restored.number, int)
    assert restored.number == x
    assert restored.number._mpf_ == x._mpf_


def test_value_to_json_roundtrips_special_reals() -> None:
    for x in (mpmath.mpf(0), mpmath.mpf("-2.5"), mpmath.inf, -mpmath.inf, mpmath.mpf("1e400")):
        restored = value_from_json(json.loads(json.dumps(value_to_json(Value(x)))))
        assert restored.number == x


def test_load_state_survives_wrong_typed_sections() -> None:
    # The state blob lives in an editable INI file, so a wrong shape has to fall
    # back to defaults rather than raise out of MainWindow's constructor.
    for blob in ({"variables": [1, 2]}, {"csrs": "nope"}, {"variables": None}):
        session = Session()
        session.load_state_json(blob)
        assert session.variables == {}
        assert session.csrs == {}


def test_load_state_drops_malformed_entries_but_keeps_the_rest() -> None:
    good = value_to_json(Value(42))
    session = Session()
    session.load_state_json(
        {"variables": {"ok": good, "bad": {"number": {"kind": "int", "value": "not an int"}}}}
    )
    assert list(session.variables) == ["ok"]


def test_load_state_rejects_a_malformed_mpf_tuple() -> None:
    # make_mpf accepts any tuple without checking it, so a short one would only
    # blow up later, while formatting.
    session = Session()
    session.load_state_json(
        {
            "variables": {
                "x": {
                    "number": {"kind": "real", "mpf": [0, 1, 2]},
                    "declared_width": None,
                    "prefer_si": False,
                    "note": None,
                    "csr": None,
                }
            }
        }
    )
    assert session.variables == {}


def test_load_state_drops_out_of_range_values() -> None:
    # Live results pass guard_displayable before being committed; a value edited
    # straight into the file never met that guard.
    session = Session()
    session.load_state_json({"ans": value_to_json(Value(mpmath.inf))})
    assert session.ans is None


def test_csr_from_json_rejects_out_of_range_field_bits() -> None:
    with pytest.raises(ValueError, match="field bit index"):
        csr_from_json({"name": "X", "fields": [{"name": "A", "msb": 10**5000, "lsb": 0}]})


def test_value_to_json_roundtrips_nested_csr() -> None:
    csr = Csr("CTRL", (CsrField("EN", 31, 31), CsrField("ADDR", 27, 8)))
    v = Value(0x8C01A0F3, csr=csr)
    restored = value_from_json(json.loads(json.dumps(value_to_json(v))))
    assert restored.csr is not None
    assert restored.csr.name == "CTRL"
    assert restored.csr.fields == csr.fields


def test_csr_to_json_roundtrip() -> None:
    csr = Csr("CTRL", (CsrField("EN", 31, 31), CsrField("IRQ", 30, 28)))
    restored = csr_from_json(json.loads(json.dumps(csr_to_json(csr))))
    assert restored == csr


def test_csr_to_json_roundtrip_anonymous() -> None:
    csr = Csr(None, (CsrField("CMD", 7, 0),))
    restored = csr_from_json(json.loads(json.dumps(csr_to_json(csr))))
    assert restored == csr


def test_session_state_roundtrip() -> None:
    session = Session()
    session.evaluate("csr CTRL = EN[31] ADDR[27:8]")
    session.evaluate("x = CTRL(0x8C01A0F3)")
    session.evaluate("y = 1/3")

    blob = json.loads(json.dumps(session.state_to_json()))

    restored = Session()
    restored.load_state_json(blob)
    assert set(restored.variables) == {"x", "y"}
    assert restored.variables["x"].number == 0x8C01A0F3
    assert restored.variables["x"].csr is not None
    assert restored.variables["x"].csr.name == "CTRL"
    assert restored.variables["y"].number == session.variables["y"].number
    assert set(restored.csrs) == {"CTRL"}
    assert restored.ans is not None
    assert session.ans is not None
    assert restored.ans.number == session.ans.number


def test_session_state_roundtrip_without_ans() -> None:
    session = Session()
    assert session.ans is None
    restored = Session()
    restored.load_state_json(session.state_to_json())
    assert restored.ans is None
    assert restored.variables == {}
    assert restored.csrs == {}


def test_load_state_json_skips_corrupt_variable_entries() -> None:
    session = Session()
    session.evaluate("x = 5")
    session.evaluate("y = 6")
    blob = session.state_to_json()
    blob["variables"]["x"] = {"not": "a valid value"}

    restored = Session()
    restored.load_state_json(blob)
    assert set(restored.variables) == {"y"}
    assert restored.variables["y"].number == 6


def test_load_state_json_skips_corrupt_csr_entries() -> None:
    session = Session()
    session.evaluate("csr CTRL = EN[31]")
    session.evaluate("csr STATUS = IRQ[3:0]")
    blob = session.state_to_json()
    blob["csrs"]["CTRL"] = {"garbage": True}

    restored = Session()
    restored.load_state_json(blob)
    assert set(restored.csrs) == {"STATUS"}


def test_load_state_json_skips_reserved_names() -> None:
    session = Session()
    blob = session.state_to_json()
    blob["variables"] = {"pi": value_to_json(Value(3))}

    restored = Session()
    restored.load_state_json(blob)
    assert "pi" not in restored.variables
