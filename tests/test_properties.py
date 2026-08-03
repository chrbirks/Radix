"""Hypothesis property tests.

Invariants:
1. The parser+evaluator are *total* over arbitrary input — only CalcError
   subclasses may escape, never a hang or a foreign exception.
2. format→parse round-trips equal the original *at displayed precision*
   (formatting at 12 significant digits is lossy by design, so exact equality
   would be a false property).
3. Calculation correctness against independent references: bit operations and
   shifts against Python int semantics with the two's-complement spec restated
   in the test; FPGA helpers against algebraic laws (rotate inverses, byteswap
   involution, fix/unfix and float pack/unpack round-trips); transcendentals
   against mathematical identities.
"""

from __future__ import annotations

import contextlib

import mpmath
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from engine_harness import run_number
from radix.engine.errors import CalcError
from radix.engine.formatter import format_real
from radix.session import Session

expression_alphabet = st.text(
    alphabet="0123456789.eE+-*/%^&|~<>()[]:,_ xkMGTpnufm'\"abcdhoi",
    max_size=40,
)


@given(expression_alphabet)
@settings(max_examples=500, deadline=1000)
def test_engine_is_total(text: str) -> None:
    session = Session()
    with contextlib.suppress(CalcError):  # CalcError is the only permitted escape
        outcome = session.evaluate(text)
        # Display counts as part of the engine's contract: formatting used to
        # raise ValueError/OverflowError on results evaluation accepted happily,
        # and stopping at evaluate() is exactly why that went unnoticed. (The
        # preview renderer is already covered — evaluate() builds it eagerly.)
        # See test_limits.py for the specific magnitudes involved.
        if outcome.value is not None:
            session.format_value(outcome.value)
            session.views_for(outcome.value)
            session.float_views_for(outcome.value)


@given(
    st.floats(
        min_value=1e-30, max_value=1e30, allow_nan=False, allow_infinity=False
    ),
    st.sampled_from(["auto", "sci", "eng", "eng_si"]),
)
@settings(max_examples=300)
def test_format_parse_roundtrip_at_display_precision(x: float, notation: str) -> None:
    original = mpmath.mpf(x)
    text = format_real(original, notation)
    session = Session()
    outcome = session.evaluate(text)
    assert outcome.value is not None
    reparsed = mpmath.mpf(outcome.value.number)
    # Equal at displayed precision: formatting both must give identical text.
    assert format_real(reparsed, notation) == text


@given(st.integers(min_value=-(2**80), max_value=2**80))
@settings(max_examples=200)
def test_integer_roundtrip_is_exact(n: int) -> None:
    session = Session()
    outcome = session.evaluate(str(n))
    assert outcome.value is not None
    assert outcome.value.number == n


# -- bit operations vs Python int semantics -----------------------------------

WORD_SIZE_ST = st.sampled_from([8, 16, 32, 64])
INT64_ST = st.integers(min_value=-(2**64), max_value=2**64)
INT128_ST = st.integers(min_value=-(2**128), max_value=2**128)

_PY_BITWISE = {
    "&": lambda x, y: x & y,
    "|": lambda x, y: x | y,
    "^": lambda x, y: x ^ y,
}


@given(INT64_ST, INT64_ST, st.sampled_from(sorted(_PY_BITWISE)), WORD_SIZE_ST)
@settings(max_examples=150)
def test_bitwise_ops_match_python_reference(a: int, b: int, op: str, ws: int) -> None:
    mask = (1 << ws) - 1
    expected = _PY_BITWISE[op](a & mask, b & mask)
    assert run_number(f"({a}) {op} ({b})", word_size=ws) == expected


@given(INT64_ST, st.integers(min_value=0, max_value=130), st.booleans(), WORD_SIZE_ST)
@settings(max_examples=150)
def test_shift_semantics_match_twos_complement_reference(
    v: int, n: int, signed: bool, ws: int
) -> None:
    # The spec, restated: mask the operand into the word; << always masks the
    # result; >> is logical on the unsigned reading, arithmetic on the signed
    # one (Python's >> on a negative int IS an arithmetic shift).
    mask = (1 << ws) - 1
    u = v & mask
    s = u - (1 << ws) if u >> (ws - 1) else u
    expected_right = ((s if signed else u) >> n) & mask
    expected_left = (u << n) & mask
    assert run_number(f"({v}) >> {n}", word_size=ws, signed=signed) == expected_right
    assert run_number(f"({v}) << {n}", word_size=ws, signed=signed) == expected_left


@given(INT64_ST, st.integers(min_value=0, max_value=200), WORD_SIZE_ST)
@settings(max_examples=100)
def test_rotate_inverse_and_modularity(v: int, n: int, ws: int) -> None:
    mask = (1 << ws) - 1
    assert run_number(f"ror(rol({v}, {n}), {n})", word_size=ws) == v & mask
    assert run_number(f"rol({v}, {n})", word_size=ws) == run_number(
        f"rol({v}, {n % ws})", word_size=ws
    )


@given(st.integers(min_value=0, max_value=2**64 - 1), st.sampled_from([16, 32, 64]))
@settings(max_examples=100)
def test_byteswap_involution_and_reference(v: int, width: int) -> None:
    fn = f"byteswap{width}"
    masked = v & ((1 << width) - 1)
    expected = int.from_bytes(masked.to_bytes(width // 8, "big"), "little")
    assert run_number(f"{fn}({v})", word_size=64) == expected
    assert run_number(f"{fn}({fn}({v}))", word_size=64) == masked


@given(INT64_ST, st.integers(min_value=1, max_value=64), WORD_SIZE_ST)
@settings(max_examples=150)
def test_sext_zext_match_twos_complement_reference(v: int, bits: int, ws: int) -> None:
    assume(bits <= ws)
    low = v & ((1 << bits) - 1)
    assert run_number(f"zext({v}, {bits})", word_size=ws) == low
    as_signed = low - (1 << bits) if low >> (bits - 1) else low
    assert run_number(f"sext({v}, {bits})", word_size=ws) == as_signed & ((1 << ws) - 1)


@given(INT64_ST, WORD_SIZE_ST)
@settings(max_examples=100)
def test_popcount_parity_match_reference(v: int, ws: int) -> None:
    masked = v & ((1 << ws) - 1)
    assert run_number(f"popcount({v})", word_size=ws) == masked.bit_count()
    assert run_number(f"parity({v})", word_size=ws) == masked.bit_count() & 1


@given(st.integers(min_value=0, max_value=2**64 - 1))
@settings(max_examples=100)
def test_same_value_reads_identically_in_every_base(n: int) -> None:
    # One grammar, no modes: dec, hex, bin, and oct spellings of one value are
    # the same number, and cross-base arithmetic sees them as equal.
    dec = run_number(str(n))
    assert run_number(hex(n)) == dec
    assert run_number(bin(n)) == dec
    assert run_number(oct(n)) == dec
    assert run_number(f"{hex(n)} - {bin(n)}") == 0


# -- integer arithmetic is exact and never masked ------------------------------

@given(INT128_ST, INT128_ST, WORD_SIZE_ST)
@settings(max_examples=150)
def test_integer_arithmetic_matches_python_at_any_word_size(
    a: int, b: int, ws: int
) -> None:
    assert run_number(f"({a}) + ({b})", word_size=ws) == a + b
    assert run_number(f"({a}) - ({b})", word_size=ws) == a - b
    assert run_number(f"({a}) * ({b})", word_size=ws) == a * b


@given(INT128_ST, INT128_ST.filter(lambda b: b != 0))
@settings(max_examples=150)
def test_trunc_division_identity(a: int, b: int) -> None:
    q = run_number(f"({a}) // ({b})")
    r = run_number(f"({a}) % ({b})")
    assert a == q * b + r
    assert abs(r) < abs(b)
    assert q == 0 or (q < 0) == ((a < 0) != (b < 0))  # truncation toward zero


# -- transcendental identities at working precision ----------------------------

_REL_EPS = mpmath.mpf(10) ** -20


@given(
    st.floats(min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False)
)
@settings(max_examples=100)
def test_sin_cos_pythagorean_identity(x: float) -> None:
    expr = f"sin({x!r})**2 + cos({x!r})**2"
    assert mpmath.almosteq(mpmath.mpf(run_number(expr)), 1, rel_eps=_REL_EPS)


@given(
    st.floats(min_value=-20, max_value=20, allow_nan=False, allow_infinity=False).filter(
        lambda v: abs(v) >= 1e-3
    )
)
@settings(max_examples=100)
def test_ln_exp_inverse(x: float) -> None:
    got = mpmath.mpf(run_number(f"ln(exp({x!r}))"))
    assert mpmath.almosteq(got, mpmath.mpf(repr(x)), rel_eps=_REL_EPS)


@given(
    st.floats(min_value=1e-6, max_value=1e6, allow_nan=False, allow_infinity=False)
)
@settings(max_examples=100)
def test_exp_ln_inverse(x: float) -> None:
    got = mpmath.mpf(run_number(f"exp(ln({x!r}))"))
    assert mpmath.almosteq(got, mpmath.mpf(repr(x)), rel_eps=_REL_EPS)


@given(
    st.floats(min_value=-1.5, max_value=1.5, allow_nan=False, allow_infinity=False).filter(
        lambda v: abs(v) >= 1e-3
    )
)
@settings(max_examples=100)
def test_asin_sin_inverse_on_principal_branch(x: float) -> None:
    got = mpmath.mpf(run_number(f"asin(sin({x!r}))"))
    assert mpmath.almosteq(got, mpmath.mpf(repr(x)), rel_eps=_REL_EPS)


# -- FPGA round-trips ----------------------------------------------------------

@st.composite
def _fix_params(draw: st.DrawFn) -> tuple[int, int, int]:
    total = draw(st.integers(min_value=1, max_value=32))
    m = draw(st.integers(min_value=0, max_value=total))
    raw = draw(st.integers(min_value=0, max_value=2**total - 1))
    return m, total - m, raw


@given(_fix_params())
@settings(max_examples=150)
def test_fix_unfix_roundtrip_is_exact(params: tuple[int, int, int]) -> None:
    # Decode is exact and re-encoding an exactly representable value cannot
    # round, so the raw pattern must survive unchanged — including sign bits.
    m, n, raw = params
    assert run_number(f"fix(unfix({raw}, {m}, {n}), {m}, {n})") == raw


@given(
    st.floats(width=32, allow_nan=False, allow_infinity=False, allow_subnormal=False)
)
@settings(max_examples=100)
def test_float32_pack_unpack_bijection(x: float) -> None:
    got = run_number(f"unfloat32(float32({x!r}))")
    assert mpmath.mpf(got) == mpmath.mpf(x)


@given(st.floats(allow_nan=False, allow_infinity=False, allow_subnormal=False))
@settings(max_examples=100)
def test_float64_pack_unpack_bijection(x: float) -> None:
    got = run_number(f"unfloat64(float64({x!r}))")
    assert mpmath.mpf(got) == mpmath.mpf(x)
