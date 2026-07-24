"""One-shot CLI tests (no display needed)."""

from __future__ import annotations

import pytest

from radix import __version__
from radix.__main__ import main


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_help_shows_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["-e", "help"]) == 0
    assert f"Radix v{__version__}" in capsys.readouterr().out


def test_evaluate_prints_integer_views(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["-e", "0xFF << 2"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("1020")
    assert "0x0000_03FC" in out


def test_evaluate_flags_word_size_truncation(capsys: pytest.CaptureFixture[str]) -> None:
    """The parenthesised views mask to the word size; say so when that loses bits."""
    assert main(["-e", "2**200"]) == 0
    out = capsys.readouterr().out
    assert "0x0000_0000" in out  # the misleading part
    assert "[low 32 bits of a 201-bit value]" in out


def test_evaluate_omits_truncation_note_when_the_value_fits(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["-e", "0xFF << 2"]) == 0
    assert "low 32 bits" not in capsys.readouterr().out


def test_evaluate_decodes_register_fields(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["-e", "csr(0xF3, MODE[7:4] CMD[3:0])"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("243")  # 0xF3 decimal
    assert "MODE=0b1111" in out
    assert "CMD=0b0011" in out


def test_evaluate_csr_definition_prints_confirmation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["-e", "csr CTRL = EN[31]"]) == 0
    assert "CTRL" in capsys.readouterr().out
