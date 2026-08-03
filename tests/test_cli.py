"""One-shot CLI tests (no display needed)."""

from __future__ import annotations

import subprocess
import sys

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


def test_eval_error_exit_code_and_stderr_caret(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Errors exit 1 and render on stderr as echo, caret line, error message."""
    assert main(["-e", "1/0"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines() == ["1/0", "  ^", "error: division by zero"]


def test_lex_error_uses_the_same_stderr_shape(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["-e", "0xZZ"]) == 1
    err = capsys.readouterr().err.splitlines()
    assert err[0] == "0xZZ"
    assert err[1] == "^^^^"  # span covers the whole malformed literal
    assert err[2].startswith("error:")


def test_float_result_prints_bare(capsys: pytest.CaptureFixture[str]) -> None:
    # No parenthesized hex/dec/bin views for non-integer results.
    assert main(["-e", "1/3"]) == 0
    assert capsys.readouterr().out == "0.333333333333\n"


def test_si_preference_reaches_the_cli(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["-e", "period(100M)"]) == 0
    assert capsys.readouterr().out == "10n\n"


def test_note_prints_in_brackets(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["-e", "clkdiv(50M, 115200)"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("434")
    assert "[actual 115.207373272k, error +64 ppm]" in out


def test_subprocess_end_to_end() -> None:
    """One true subprocess round-trip per exit code, display-free."""
    ok = subprocess.run(
        [sys.executable, "-m", "radix", "-e", "0xFF << 2"],
        capture_output=True, text=True, timeout=60,
    )
    assert ok.returncode == 0
    assert ok.stdout.startswith("1020")

    bad = subprocess.run(
        [sys.executable, "-m", "radix", "-e", "1 +"],
        capture_output=True, text=True, timeout=60,
    )
    assert bad.returncode == 1
    assert "error:" in bad.stderr
