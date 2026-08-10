"""Golden tests for the FPGA/HDL toolkit."""

from __future__ import annotations

import pytest

from engine_harness import run, run_number
from radix.engine.errors import EvalError
from radix.session import Session

# -- bit utilities ----------------------------------------------------------------

CASES = [
    ("clog2(300)", "9"),
    ("clog2(256)", "8"),
    ("clog2(257)", "9"),
    ("clog2(1)", "0"),
    ("flog2(300)", "8"),
    ("flog2(256)", "8"),
    ("mask(12)", "4095"),
    ("mask(0)", "0"),
    ("bit(7)", "128"),
    ("popcount(0xF0F0)", "8"),
    ("parity(0b1011)", "1"),
    ("parity(0b11)", "0"),
    ("revbits(0b1101, 4)", "11"),  # 0b1011
    ("byteswap16(0x1234)", "13330"),  # 0x3412
    ("byteswap32(0x12345678)", "2018915346"),  # 0x78563412
    ("byteswap64(1)", "72057594037927936"),  # 1 << 56
    ("bit(0)", "1"),
    ("bit(31)", "2147483648"),  # 1 << 31
    ("popcount(0)", "0"),
    ("popcount(0xFFFF_FFFF)", "32"),
    ("revbits(1, 8)", "128"),
    ("revbits(1)", "2147483648"),  # width defaults to the 32-bit word
    ("byteswap64(0x0123456789ABCDEF)", str(0xEFCD_AB89_6745_2301)),  # bytes reversed
    ("zext(0x1FF, 8)", "255"),
    ("zext(0xFFFF, 4)", "15"),
    ("sext(0x80, 8)", "4294967168"),  # sign-extended to 32 bits (default word size)
    ("sext(0x7F, 8)", "127"),  # sign bit clear: unchanged
    ("sext(0xF8, 8)", "4294967288"),  # 0xFFFF_FFF8
    ("rol(0x80, 1)", "256"),
    ("ror(1, 1)", "2147483648"),  # 1 << 31 (default word size)
]


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_bit_utilities(text: str, expected: str) -> None:
    assert run(text) == expected


def test_rotates_use_word_size() -> None:
    assert run("rol(0x80, 1)", word_size=8) == "1"  # wraps around at 8 bits
    assert run("ror(1, 1)", word_size=8) == "128"


def test_rotates_at_64_bits() -> None:
    assert run("ror(1, 1)", word_size=64) == str(1 << 63)
    assert run("rol(1, 65)", word_size=64) == "2"  # count is taken mod the word size
    assert run("rol(1, 64)", word_size=64) == "1"


def test_sext_respects_word_size() -> None:
    assert run("sext(0x80, 8)", word_size=16) == "65408"  # 0xFF80


def test_sext_zext_bits_capped_by_word_size() -> None:
    with pytest.raises(EvalError):
        run("sext(0xFF, 16)", word_size=8)
    with pytest.raises(EvalError):
        run("zext(0xFF, 16)", word_size=8)


def test_bit_utility_domain_errors() -> None:
    for text in ("clog2(0)", "clog2(-1)", "flog2(0)", "mask(-1)", "clog2(1.5)",
                 "sext(1, 0)", "sext(1, 100)", "rol(1.5, 1)"):
        with pytest.raises(EvalError):
            run(text)


# -- clock & unit helpers -----------------------------------------------------------

def test_period_and_freq() -> None:
    assert run("period(100M)") == "10n"
    assert run("freq(8n)") == "125M"
    assert run("period(freq(10n))") == "10n"
    with pytest.raises(EvalError):
        run("period(0)")


def test_period_notation_override() -> None:
    # An explicit session notation beats the SI preference.
    assert run("period(100M)", notation="sci") == "1e-8"


# -- fixed point ----------------------------------------------------------------------

def test_fix_golden() -> None:
    session = Session()
    outcome = session.evaluate("fix(0.7071, 1, 15)")
    assert outcome.value is not None
    assert outcome.value.number == 0x5A82
    assert outcome.value.declared_width == 16
    assert outcome.value.note is not None and "quantization error" in outcome.value.note


def test_fix_unfix_roundtrip() -> None:
    assert run("unfix(0x5A82, 1, 15)") == "0.707092285156"  # 12 sig digits displayed
    assert run("unfix(fix(0.5, 1, 15), 1, 15)") == "0.5"
    # Negative values are two's complement raw
    session = Session()
    outcome = session.evaluate("fix(-0.5, 1, 15)")
    assert outcome.value is not None and outcome.value.number == 0xC000
    assert run("unfix(0xC000, 1, 15)") == "-0.5"


def test_clkdiv_golden_and_viz() -> None:
    from radix.engine.viz import ClockViz

    assert run("clkdiv(50M, 115200)") == "434"
    assert run("clkdiv(100M, 25M)") == "4"
    session = Session()
    outcome = session.evaluate("clkdiv(50M, 115200)")
    assert outcome.value is not None
    viz = outcome.value.viz
    assert isinstance(viz, ClockViz)
    assert viz.divisor == 434
    assert viz.achieved_text == "115.207373272k"
    assert viz.error_ppm is not None and abs(viz.error_ppm - 64) < 1
    assert viz.error_text == "+64 ppm"
    assert outcome.value.note is not None and "error" in outcome.value.note
    with pytest.raises(EvalError, match="positive"):
        run("clkdiv(50M, 0)")


def test_clkdiv_wave_fields() -> None:
    from radix.engine.viz import ClockViz

    def wave(text: str) -> tuple[int | None, int | None, str | None]:
        outcome = Session().evaluate(text)
        assert outcome.value is not None
        viz = outcome.value.viz
        assert isinstance(viz, ClockViz)
        return viz.wave_high, viz.wave_low, viz.duty_text

    assert wave("clkdiv(100M, 33.34M)") == (4, 2, "66.7%")  # odd divider: asymmetric
    assert wave("clkdiv(100, 50)") == (2, 2, "50%")
    assert wave("clkdiv(100, 100)") == (1, 1, "50%")  # /1 passes the clock through
    assert wave("clkdiv(50M, 115200)") == (434, 434, "50%")  # computed even when undrawn
    assert wave("period(100M)") == (None, None, None)


def test_period_freq_attach_clock_viz() -> None:
    from radix.engine.viz import ClockViz

    session = Session()
    outcome = session.evaluate("period(100M)")
    assert outcome.value is not None
    viz = outcome.value.viz
    assert isinstance(viz, ClockViz)
    assert (viz.freq_text, viz.period_text) == ("100M", "10n")
    assert viz.divisor is None

    outcome = session.evaluate("freq(8n)")
    viz = outcome.value.viz if outcome.value else None
    assert isinstance(viz, ClockViz)
    assert (viz.freq_text, viz.period_text) == ("125M", "8n")


def test_mem_golden_and_viz() -> None:
    from radix.engine.viz import MemViz

    assert run("mem(4096, 36)") == "147456"
    session = Session()
    outcome = session.evaluate("mem(4096, 36)")
    assert outcome.value is not None
    viz = outcome.value.viz
    assert isinstance(viz, MemViz)
    assert (viz.addr_bits, viz.addressable) == (12, 4096)
    assert viz.bytes_text == "18 KiB"
    assert viz.utilization == 1.0
    assert outcome.value.note == "addr 12 bits, 18 KiB"

    outcome = session.evaluate("mem(3000, 8)")
    viz = outcome.value.viz if outcome.value else None
    assert isinstance(viz, MemViz)
    assert (viz.addr_bits, viz.addressable) == (12, 4096)
    assert 0.72 < viz.utilization < 0.74 and viz.util_text == "73%"

    with pytest.raises(EvalError, match="positive"):
        run("mem(0, 8)")


def test_fix_attaches_viz_payload() -> None:
    from radix.engine.viz import FixedPointViz

    session = Session()
    outcome = session.evaluate("fix(0.5, 1, 15)")
    assert outcome.value is not None
    viz = outcome.value.viz
    assert isinstance(viz, FixedPointViz)
    assert (viz.m, viz.n, viz.raw) == (1, 15, 0x4000)
    assert viz.error_lsb == 0.0  # 0.5 is exactly representable
    assert viz.stored_text == "0.5"
    # Pre-formatted for the REGISTER lanes: the panel derives nothing itself.
    assert viz.hex_text == "0x4000"
    assert (viz.dec_text, viz.dec_signed_text) == ("16384", "16384")
    assert viz.error_lsb_text == "0 LSB"
    assert len(viz.bit_weights) == 16
    assert (viz.bit_weights[15], viz.bit_weights[14], viz.bit_weights[0]) == (
        "-2^0", "2^-1", "2^-15",
    )

    outcome = session.evaluate("unfix(0x5A82, 1, 15)")
    assert outcome.value is not None
    viz = outcome.value.viz
    assert isinstance(viz, FixedPointViz)
    assert viz.raw == 0x5A82
    assert viz.error_lsb == 0.0 and viz.error_text == "0"

    outcome = session.evaluate("fix(-1.5, 8, 4)")  # negative: signed decimal differs
    assert outcome.value is not None
    viz = outcome.value.viz
    assert isinstance(viz, FixedPointViz)
    assert (viz.hex_text, viz.dec_text, viz.dec_signed_text) == ("0xFE8", "4072", "-24")
    assert viz.bit_weights[11] == "-2^7"


def test_fix_quantization_error_is_reported_in_lsbs() -> None:
    from radix.engine.viz import FixedPointViz

    outcome = Session().evaluate("fix(0.7071, 1, 15)")
    assert outcome.value is not None
    viz = outcome.value.viz
    assert isinstance(viz, FixedPointViz)
    assert 0.25 < viz.error_lsb < 0.26
    assert viz.error_lsb_text == "0.25 LSB"


def test_fix_range_errors() -> None:
    with pytest.raises(EvalError, match="does not fit"):
        run("fix(1.5, 1, 15)")  # Q1.15 max is ~0.99997
    with pytest.raises(EvalError):
        run("fix(0.5, 0, 0)")


# -- IEEE-754 ----------------------------------------------------------------------

def test_float_pack_golden_and_viz() -> None:
    from radix.engine.viz import FloatBitsViz

    session = Session()
    outcome = session.evaluate("float32(1.5)")
    assert outcome.value is not None
    assert outcome.value.number == 0x3FC00000
    assert outcome.value.declared_width == 32
    viz = outcome.value.viz
    assert isinstance(viz, FloatBitsViz)
    assert (viz.width, viz.exp_width, viz.man_width) == (32, 8, 23)
    assert viz.hex_text == "0x3FC0_0000"
    assert viz.exponent_text == "127 - bias 127 = 2^0"
    assert viz.mantissa_text == "1.5"
    assert viz.rounded is False
    assert outcome.value.note == "float32 stores 1.5"


def test_float32_rounds_and_reports_it() -> None:
    from radix.engine.viz import FloatBitsViz

    session = Session()
    outcome = session.evaluate("float32(0.1)")
    assert outcome.value is not None
    viz = outcome.value.viz
    assert isinstance(viz, FloatBitsViz)
    assert viz.rounded is True
    assert viz.stored_text == "0.100000001"
    assert viz.exact_text == "0.1"


def test_float_pack_bit_patterns() -> None:
    # 1.5 = 2^0 × 1.5: sign 0, biased exponent 127 (float32) / 1023 (float64),
    # mantissa field .5 — patterns derivable by hand from the IEEE-754 layout.
    assert run_number("float32(1.5)") == 0x3FC0_0000
    assert run_number("float64(1.5)") == 0x3FF8_0000_0000_0000
    assert run_number("float32(-2)") == 0xC000_0000  # sign 1, 2^1, mantissa 1.0


def test_unfloat_golden_values() -> None:
    assert run("unfloat64(0x3FF8000000000000)") == "1.5"
    assert run("unfloat64(0x4009000000000000)") == "3.125"  # 2^1 × 1.5625
    assert run("unfloat32(0xC0000000)") == "-2"


def test_unfloat_roundtrip_and_subnormal() -> None:
    from radix.engine.viz import FloatBitsViz

    assert run("unfloat32(0x3FC00000)") == "1.5"
    assert run("unfloat64(float64(pi))") == "3.14159265359"
    session = Session()
    outcome = session.evaluate("unfloat32(1)")  # smallest positive subnormal
    assert outcome.value is not None
    viz = outcome.value.viz
    assert isinstance(viz, FloatBitsViz)
    assert "subnormal" in viz.exponent_text
    assert viz.rounded is False


def test_float_slice_extracts_fields() -> None:
    assert run("float32(1.5)[30:23]") == "127"  # the exponent field
    assert run("float32(-1.5)[31]") == "1"  # the sign bit


def test_float_domain_errors() -> None:
    for text in ("float32(1e300)", "unfloat32(0x7F800000)",  # inf pattern
                 "unfloat32(0x7FC00000)",  # nan pattern
                 "unfloat32(1.5)"):
        with pytest.raises(EvalError):
            run(text)


def test_hdl_width_and_slicing_flow() -> None:
    session = Session()
    session.evaluate("x = 8'hA5")
    assert session.evaluate("x[7:4]").primary_text == "10"
    assert session.evaluate("popcount(x)").primary_text == "4"


def test_help_covers_fpga_functions() -> None:
    session = Session()
    text = session.evaluate("help clog2").help_text
    assert text is not None and "clog2(300)" in text
    overview = session.evaluate("help").help_text
    assert overview is not None and "fix" in overview and "period" in overview
