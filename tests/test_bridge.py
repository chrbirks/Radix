"""Bridge payload tests: the JSON-shaped API the Android app calls.

Everything the phone paints is pre-formatted here, so these goldens are the
executable spec for the register card, the readout and the error underline.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from radix.bridge import Bridge


@pytest.fixture
def bridge(tmp_path: Path) -> Bridge:
    return Bridge(str(tmp_path))


def test_bridge_imports_without_qt() -> None:
    code = "import sys, radix.bridge; assert 'PySide6' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)


def test_integer_payload_32(bridge: Bridge) -> None:
    p = bridge.preview("0xDEAD << 16 | 0xBEEF")
    assert p["kind"] == "int"
    assert p["text"] == "3735928559"
    assert p["normalized"] == "(57005 << 16) | 48879"
    assert p["hex"] == "0xDEAD_BEEF"
    assert p["dec"] == "3735928559"
    assert p["bin"] == "0b1101_1110_1010_1101_1011_1110_1110_1111"
    assert [n["hex"] for n in p["nibbles"]] == list("DEADBEEF")
    assert p["nibbles"][0]["bits"] == [1, 1, 0, 1]
    assert p["nibbles"][-1]["bits"] == [1, 1, 1, 1]
    assert p["truncated"] is False
    assert p["note"] == ""


def test_integer_payload_64_pads_leading_nibbles(bridge: Bridge) -> None:
    bridge.set_mode("word_size", 64)
    p = bridge.preview("0xDEAD << 16 | 0xBEEF")
    assert len(p["nibbles"]) == 16
    assert [n["hex"] for n in p["nibbles"]] == list("00000000DEADBEEF")


def test_integer_payload_8(bridge: Bridge) -> None:
    bridge.set_mode("word_size", 8)
    p = bridge.preview("0xEF")
    assert [n["hex"] for n in p["nibbles"]] == ["E", "F"]


def test_truncated_flag_when_literal_exceeds_word(bridge: Bridge) -> None:
    bridge.set_mode("word_size", 16)
    p = bridge.preview("0xDEADBEEF")
    assert [n["hex"] for n in p["nibbles"]] == list("BEEF")
    assert p["truncated"] is True


def test_note_uses_comma_decimal(bridge: Bridge) -> None:
    p = bridge.preview("clkdiv(50M; 115200)")
    assert p["kind"] == "int"
    assert p["text"] == "434"
    assert p["note"] == "actual 115,207373272k, error +64 ppm"


def test_real_payload_has_no_register(bridge: Bridge) -> None:
    p = bridge.preview("period(100M)")
    assert p["kind"] == "real"
    assert p["text"] == "10n"
    assert p["nibbles"] == []
    assert "hex" not in p


def test_signed_selects_dec_view(bridge: Bridge) -> None:
    bridge.set_mode("word_size", 8)
    unsigned = bridge.preview("-1")
    bridge.set_mode("signed", True)
    signed = bridge.preview("-1")
    assert unsigned["dec"] == "255"
    assert signed["dec"] == "-1"
    assert unsigned["hex"] == signed["hex"] == "0xFF"


def test_incomplete_error_is_flagged(bridge: Bridge) -> None:
    p = bridge.preview("1 +")
    assert p["kind"] == "error"
    assert p["incomplete"] is True
    assert p["span"] == [3, 3]


def test_hard_error_carries_span(bridge: Bridge) -> None:
    p = bridge.preview("foo(1)")
    assert p["kind"] == "error"
    assert p["incomplete"] is False
    assert p["message"] == "unknown function 'foo'"
    assert p["span"] == [0, 3]


def test_assign_payload_has_prefix(bridge: Bridge) -> None:
    p = bridge.preview("x = 5")
    assert p["kind"] == "int"
    assert p["prefix"] == "x"
    assert p["text"] == "5"


def test_help_is_info(bridge: Bridge) -> None:
    p = bridge.preview("help")
    assert p["kind"] == "info"
    assert "clog2" in p["info_text"]


def test_empty_input(bridge: Bridge) -> None:
    assert bridge.preview("   ")["kind"] == "empty"


def test_modes_ride_on_every_payload(bridge: Bridge) -> None:
    p = bridge.preview("1")
    assert p["modes"] == {
        "word_size": 32,
        "signed": False,
        "angle": "rad",
        "notation": "auto",
        "int_base": "dec",
    }


def test_comma_mode_is_fixed(bridge: Bridge) -> None:
    assert bridge.preview("3,14 * 2")["text"] == "6,28"


# -- commit, ans, history ----------------------------------------------------


def test_evaluate_commits_variables_and_ans(bridge: Bridge) -> None:
    bridge.evaluate("x = 5")
    assert bridge.preview("x + 1")["text"] == "6"
    assert bridge.preview("ans * 2")["text"] == "10"


def test_preview_does_not_commit(bridge: Bridge) -> None:
    bridge.preview("y = 7")
    assert bridge.preview("y")["kind"] == "error"
    assert bridge.history() == []


def test_evaluate_appends_persistent_history(bridge: Bridge, tmp_path: Path) -> None:
    bridge.evaluate("1+1")
    bridge.evaluate("x = 5")
    entries = bridge.history()
    assert [e["expression"] for e in entries] == ["1+1", "x = 5"]
    assert entries[0]["result"] == "2"
    assert entries[1]["prefix"] == "x"
    assert entries[0]["timestamp"] > 0
    reopened = Bridge(str(tmp_path))
    assert [e["expression"] for e in reopened.history()] == ["1+1", "x = 5"]


def test_history_reformats_on_base_change(bridge: Bridge) -> None:
    bridge.evaluate("1020")
    bridge.set_mode("int_base", "hex")
    assert bridge.history()[0]["result"] == "0x3FC"


def test_delete_and_clear_history(bridge: Bridge, tmp_path: Path) -> None:
    bridge.evaluate("1")
    bridge.evaluate("2")
    bridge.evaluate("3")
    assert [e["result"] for e in bridge.delete_history(1)] == ["1", "3"]
    assert Bridge(str(tmp_path)).history() == bridge.history()
    assert bridge.clear_history() == []
    assert not (tmp_path / "history.jsonl").exists()


def test_clear_command_wipes_history(bridge: Bridge) -> None:
    bridge.evaluate("1")
    p = bridge.evaluate("clear")
    assert p["kind"] == "info"
    assert bridge.history() == []


# -- bit editing ---------------------------------------------------------------


def test_toggle_bit_writes_hex_literal_to_input(bridge: Bridge) -> None:
    bridge.evaluate("0xF0")
    p = bridge.toggle_bit(0)
    assert p["input"] == "0xF1"
    assert p["kind"] == "int"
    assert p["text"] == "241"
    assert bridge.toggle_bit(0)["input"] == "0xF0"


def test_scratch_survives_word_size_cycling_but_not_edits(bridge: Bridge) -> None:
    # Cycling the word size only changes how the value is *displayed* — the
    # upper bits are kept (CLAUDE.md). An edit writes the masked literal back to
    # the input line, and the input line is the truth from then on.
    bridge.evaluate("0xDEADBEEF")
    bridge.set_mode("word_size", 8)
    bridge.set_mode("word_size", 32)
    assert bridge.toggle_bit(0)["input"] == "0xDEADBEEE"
    bridge.set_mode("word_size", 8)
    assert bridge.toggle_bit(0)["input"] == "0xEF"
    bridge.set_mode("word_size", 32)
    assert bridge.toggle_bit(0)["input"] == "0xEE"


def test_toggle_bit_marks_changed(bridge: Bridge) -> None:
    bridge.evaluate("0xF0")
    assert bridge.toggle_bit(4)["changed"] == [4]


def test_changed_bits_between_results(bridge: Bridge) -> None:
    bridge.evaluate("0b0001")
    assert bridge.preview("0b0011")["changed"] == [1]
    assert bridge.preview("0b0011")["changed"] == [1]  # same value: diff is kept
    assert bridge.preview("0b0111")["changed"] == [2]


def test_toggle_without_integer_is_an_error(bridge: Bridge) -> None:
    with pytest.raises(ValueError):
        bridge.toggle_bit(0)


def test_field_readout(bridge: Bridge) -> None:
    bridge.evaluate("0xDEADBEEF")
    p = bridge.field(15, 8)
    assert p["text"] == "[15:8] = 0xBE = 190"
    assert p["input"] == "0xDEADBEEF[15:8]"


# -- catalog and suggestions -------------------------------------------------


def test_functions_catalog_mirrors_engine_tables(bridge: Bridge) -> None:
    from radix.engine.functions import FUNCTIONS

    groups = bridge.functions()
    assert groups[0]["category"] == "Trigonometry"
    items = [item for g in groups for item in g["items"]]
    assert [i["name"] for i in items] == list(FUNCTIONS)
    clkdiv = next(i for i in items if i["name"] == "clkdiv")
    assert clkdiv["insert"] == "clkdiv("
    assert clkdiv["display"].startswith("clkdiv(") and "; " in clkdiv["display"]
    assert clkdiv["summary"]


def test_suggest_filters_by_identifier_prefix(bridge: Bridge) -> None:
    names = [s["name"] for s in bridge.suggest("1 + cl", 6)]
    assert names and all(n.startswith("cl") for n in names)
    assert "clog2" in names


def test_suggest_prefers_recently_used(bridge: Bridge) -> None:
    bridge.evaluate("clkdiv(50M; 115200)")
    bridge.evaluate("clog2(300)")
    names = [s["name"] for s in bridge.suggest("", 0)]
    assert names[:2] == ["clog2", "clkdiv"]
    assert bridge.suggest("", 0)[0]["insert"] == "clog2("


def test_suggest_respects_limit(bridge: Bridge) -> None:
    assert len(bridge.suggest("", 0, limit=3)) == 3


# -- state, version, rpc ---------------------------------------------------------


def test_state_round_trip(bridge: Bridge, tmp_path: Path) -> None:
    bridge.evaluate("x = 5")
    bridge.set_mode("word_size", 16)
    bridge.set_mode("signed", True)
    bridge.set_mode("notation", "eng_si")
    restored = Bridge(str(tmp_path), bridge.state_json())
    assert restored.preview("x")["text"] == "5"
    assert restored.preview("ans")["text"] == "5"
    assert restored.modes() == bridge.modes()


def test_malformed_state_falls_back_to_defaults(tmp_path: Path) -> None:
    restored = Bridge(str(tmp_path), "{not json")
    assert restored.modes()["word_size"] == 32


def test_version_is_single_sourced(bridge: Bridge) -> None:
    from radix import __version__

    assert bridge.version() == __version__


def test_rpc_round_trips_json(bridge: Bridge) -> None:
    import json

    from radix.bridge import rpc

    out = json.loads(rpc(bridge, "evaluate", '{"text": "1+1"}'))
    assert out["text"] == "2"
    assert json.loads(rpc(bridge, "history", "{}"))[0]["expression"] == "1+1"


def test_rpc_never_raises(bridge: Bridge) -> None:
    import json

    from radix.bridge import rpc

    unknown = json.loads(rpc(bridge, "nope", "{}"))
    assert unknown["kind"] == "error" and unknown["message"].startswith("internal:")
    private = json.loads(rpc(bridge, "_run", '{"text":"1","commit":true}'))
    assert private["kind"] == "error"
    bad_args = json.loads(rpc(bridge, "preview", "{not json"))
    assert bad_args["kind"] == "error"
    bad_mode = json.loads(rpc(bridge, "set_mode", '{"name":"word_size","value":7}'))
    assert bad_mode["kind"] == "error" and "word_size" in bad_mode["message"]
