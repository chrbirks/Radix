"""Formatter and preview-rendering tests."""

from __future__ import annotations

import mpmath

from radix.engine.formatter import format_int_base, format_real, integer_views
from radix.session import Session


def test_notations() -> None:
    x = mpmath.mpf("0.00001") * 47  # 4.7e-4
    assert format_real(x, "auto") == "0.00047"
    assert format_real(x, "sci") == "4.7e-4"
    assert format_real(x, "eng") == "470e-6"
    assert format_real(x, "eng_si") == "470u"


def test_auto_switches_to_scientific_for_extremes() -> None:
    assert format_real(mpmath.mpf("1.5e-9"), "auto") == "1.5e-9"
    assert format_real(mpmath.mpf("1e15"), "auto") == "1e+15"
    assert format_real(mpmath.mpf("123.25"), "auto") == "123.25"


def test_engineering_exponent_is_multiple_of_three() -> None:
    assert format_real(mpmath.mpf("1.0e-8"), "eng") == "10e-9"
    assert format_real(mpmath.mpf("1.0e-8"), "eng_si") == "10n"
    assert format_real(mpmath.mpf("2.5e7"), "eng") == "25e+6"
    assert format_real(mpmath.mpf("2.5e7"), "eng_si") == "25M"


def test_negative_and_zero() -> None:
    assert format_real(mpmath.mpf(0), "eng_si") == "0"
    assert format_real(mpmath.mpf("-4.7e3"), "eng_si") == "-4.7k"


def test_integer_views_grouping_and_signedness() -> None:
    views = integer_views(1020, 16)
    assert views.hex == "0x03FC"
    assert views.binary == "0b0000_0011_1111_1100"
    assert views.dec_unsigned == "1020"
    assert views.dec_signed == "1020"
    views = integer_views(-1, 8)
    assert views.hex == "0xFF"
    assert views.dec_unsigned == "255"
    assert views.dec_signed == "-1"


def test_float_views_double() -> None:
    from radix.engine.formatter import float_views

    views = float_views(1.0, 64)
    assert views is not None
    assert views.bits == 0x3FF0000000000000
    assert views.hex == "0x3FF0_0000_0000_0000"
    assert views.sign_text == "+"
    assert views.exponent_text == "1023 - bias 1023 = 2^0"
    assert views.mantissa_text == "1"


def test_float_views_single_and_specials() -> None:
    from radix.engine.formatter import float_views

    views = float_views(-2.5, 32)
    assert views is not None
    assert views.bits == 0xC0200000
    assert views.sign_text == "-"
    assert views.exponent_text == "128 - bias 127 = 2^1"
    assert views.mantissa_text == "1.25"
    zero = float_views(0.0, 32)
    assert zero is not None and zero.mantissa_text == "0"
    huge = float_views(1e300, 32)  # overflows single precision -> +inf pattern
    assert huge is not None and huge.mantissa_text == "inf"
    assert float_views(1.0, 16) is None  # no half-precision mapping


def test_integer_views_ascii() -> None:
    assert integer_views(0x746F6B31, 32).ascii == "tok1"
    assert integer_views(1020, 16).ascii == ".."  # 0x03 0xFC: non-printable
    assert integer_views(0x41, 8).ascii == "A"


def test_preview_rendering() -> None:
    session = Session()
    assert session.preview("2^10").normalized == "2 XOR 10"
    assert session.preview("4.7k*2").normalized == "4700 × 2"
    assert session.preview("2**2").normalized == "2²"
    assert session.preview("(1+1)**2").normalized == "(1 + 1)²"
    # Multi-digit exponents render as superscripts too, not textual `**`.
    assert session.preview("2**10").normalized == "2¹⁰"
    assert session.preview("2**64").normalized == "2⁶⁴"
    assert session.preview("(1+1)**12").normalized == "(1 + 1)¹²"
    # Negative integer exponents superscript too, with a superscript minus.
    assert session.preview("2**-1").normalized == "2⁻¹"
    assert session.preview("2**(-1)").normalized == "2⁻¹"
    assert session.preview("2**-10").normalized == "2⁻¹⁰"
    # A multi-digit superscript is still a self-grouping atom (no clarifying parens).
    assert session.preview("2**10+1").normalized == "2¹⁰ + 1"
    session.evaluate("x = 0xFF")
    assert session.preview("x << 2").normalized == "255 << 2"
    assert session.preview("y = 3*4").normalized == "y ← 3 × 4"
    assert session.preview("1/2pi").normalized == "1 / 2 × pi"


def test_preview_clarifying_parentheses() -> None:
    # Mixed-precedence subexpressions are parenthesized to make the grouping
    # explicit, even where the parens are not strictly required to re-parse.
    session = Session()

    def norm(text: str) -> str:
        return session.preview(text).normalized

    # The reported case: >> binds looser than +, so the + groups first.
    assert norm("x10>>2+h10>>2") == "16 >> (2 + 16) >> 2"
    assert norm("1+2*3") == "1 + (2 × 3)"
    assert norm("2*3+4*5") == "(2 × 3) + (4 × 5)"
    assert norm("7+3*5") == "7 + (3 × 5)"
    assert norm("2*3+7") == "(2 × 3) + 7"
    assert norm("1<<2|0xF0") == "(1 << 2) | 240"
    assert norm("1+2+3*4") == "1 + 2 + (3 × 4)"

    # Same-precedence chains stay clean — no gratuitous parens.
    assert norm("4+5+6") == "4 + 5 + 6"
    assert norm("9-2-3") == "9 - 2 - 3"
    assert norm("8/2/2") == "8 / 2 / 2"

    # A superscript power is self-grouping: treated as an atom, no parens.
    assert norm("2**3+1") == "2³ + 1"
    assert norm("7*2**3") == "7 × 2³"

    # Required parens (a looser child) still work as before.
    assert norm("(1+2)*3") == "(1 + 2) × 3"


def test_format_int_base_compact() -> None:
    assert format_int_base(1020, "dec", 64) == "1020"
    assert format_int_base(1020, "hex", 64) == "0x3FC"
    assert format_int_base(1020, "bin", 64) == "0b11_1111_1100"
    assert format_int_base(0, "hex", 64) == "0x0"
    assert format_int_base(0xDEADBEEF, "hex", 64) == "0xDEAD_BEEF"
    # Negatives render as word-size two's complement, matching the panel.
    assert format_int_base(-1, "hex", 8) == "0xFF"
    assert format_int_base(-1, "bin", 8) == "0b1111_1111"
    assert format_int_base(-2, "hex", 16) == "0xFFFE"


def test_session_format_value_honors_int_base() -> None:
    session = Session()
    value = session.evaluate("0xFF << 2").value
    assert value is not None
    assert session.format_value(value) == "1020"
    session.int_base = "hex"
    assert session.format_value(value) == "0x3FC"
    assert session.format_value(value, base="dec") == "1020"  # explicit override
    session.int_base = "bin"
    assert session.format_value(value) == "0b11_1111_1100"
    # Floats are untouched by the base setting.
    fval = session.evaluate("1/8").value
    assert fval is not None
    assert session.format_value(fval) == "0.125"


def test_int_results_follow_notation() -> None:
    session = Session()
    value = session.evaluate("10000000").value
    assert value is not None
    assert session.format_value(value) == "10000000"  # auto stays exact
    session.notation = "sci"
    assert session.format_value(value) == "1e+7"
    session.notation = "eng"
    assert session.format_value(value) == "10e+6"
    session.notation = "eng_si"
    assert session.format_value(value) == "10M"
    # The hex/bin display base still takes precedence over notation.
    session.int_base = "hex"
    assert session.format_value(value) == "0x98_9680"
