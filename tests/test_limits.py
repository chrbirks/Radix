"""Guards on result magnitude, and the totality of the display pipeline.

The engine's contract (see engine/errors.py) is that only CalcError subclasses
escape it. Evaluation alone always honored that; *display* did not, and that is
where these regressions lived:

- ints wider than Python's int->str cap (4300 digits) raised ValueError out of
  format_number, even though the evaluator's own ceiling permits ~301030-digit
  results;
- reals whose binary exponent ran away made mpmath's decimal conversion take
  22s and then fail (and longer inputs never finished at all);
- mem() converted unbounded ints to float and raised OverflowError.

Each escaped as a bare exception through Session.evaluate, which the GUI turns
into a silent no-op and the CLI into a traceback.
"""

from __future__ import annotations

import time

import pytest

from radix.engine.errors import CalcError
from radix.engine.evaluator import MAX_POW_RESULT_BITS
from radix.engine.values import MAX_MAGNITUDE_BITS
from radix.session import Session


def _display(session: Session, text: str) -> str:
    """Evaluate and render exactly as the UI's preview path does."""
    outcome = session.evaluate(text, commit=False)
    assert outcome.value is not None
    return session.format_value(outcome.value)


# -- wide integers: exact while they fit, scientific past the cap ---------------


def test_int_within_str_cap_stays_exact() -> None:
    session = Session()
    assert _display(session, "2**14000") == str(2**14000)


def test_int_past_str_cap_falls_back_to_scientific() -> None:
    # 2**20000 is 6021 digits: past Python's 4300-digit int->str cap, but well
    # inside the evaluator's own result ceiling, so it must still display.
    assert _display(Session(), "2**20000") == "3.98027684034e+6020"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("10**5000", "1e+5000"), ("1e5000", "1e+5000"), ("99999**3000", "9.70445387981e+14999")],
)
def test_wide_int_results_display(text: str, expected: str) -> None:
    assert _display(Session(), text) == expected


@pytest.mark.parametrize(
    ("notation", "expected"),
    [
        ("sci", "3.98027684034e+6020"),
        ("eng", "398.027684034e+6018"),  # exponent forced to a multiple of 3
        ("eng_si", "398.027684034e+6018"),  # no SI suffix reaches this far out
    ],
)
def test_wide_int_honors_explicit_notations(notation: str, expected: str) -> None:
    assert _display(Session(notation=notation), "2**20000") == expected


def test_wide_int_hex_base_is_exact() -> None:
    # Hex/bin never went through str(), so they must stay digit-exact.
    text = _display(Session(int_base="hex"), "2**20000")
    assert text.startswith("0x1_0000") and text.endswith("0000")


def test_assignment_of_a_wide_int_commits_and_reformats() -> None:
    # The old failure committed the variable and *then* raised while formatting
    # it, leaving a session that broke every later render mentioning the name.
    session = Session()
    session.evaluate("big = 2**20000")
    assert "big" in session.variables
    assert session.format_value(session.variables["big"]) == "3.98027684034e+6020"
    assert _display(session, "big + 1") == "3.98027684034e+6020"


# -- runaway reals ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "exp(2**20000)",  # was 22s, then ValueError
        "exp(2**100000)",  # never finished
        "exp(1e8)",
        "period(exp(-2**20000))",  # reciprocal of a runaway underflow
        "freq(exp(-2**20000))",
        "fix(exp(2**20000), 1, 15)",
        "clkdiv(exp(2**20000), 1)",
    ],
)
def test_runaway_real_is_a_calc_error(text: str) -> None:
    session = Session()
    with pytest.raises(CalcError) as exc:
        _display(session, text)
    assert exc.value.message == "result is out of range"


def test_runaway_is_caught_at_the_call_that_produced_it() -> None:
    # Not one level further out: handlers pre-format their argument into notes
    # and viz payloads, so period() must never receive the runaway at all.
    text = "period(exp(-2**20000))"
    with pytest.raises(CalcError) as exc:
        Session().evaluate(text, commit=False)
    assert text[exc.value.span.start : exc.value.span.end] == "exp(-2**20000)"


def test_real_magnitude_ceiling_matches_the_integer_one() -> None:
    # Both budgets are "about a million bits" so neither can outrun the other.
    assert MAX_MAGNITUDE_BITS == MAX_POW_RESULT_BITS


def test_reals_within_range_are_untouched() -> None:
    session = Session()
    assert _display(session, "exp(1000)").startswith("1.97007111402e+434")
    assert _display(session, "period(100M)") == "10n"
    assert _display(session, "1e-300").startswith("1e-300")


# -- mem() sizing ------------------------------------------------------------------


@pytest.mark.parametrize("text", ["mem(2**2000, 1)", "mem(10**400, 8)", "mem(1e400, 8)"])
def test_mem_rejects_dimensions_that_would_overflow_float(text: str) -> None:
    with pytest.raises(CalcError) as exc:
        Session().evaluate(text, commit=False)
    assert "at most 2**64" in exc.value.message


def test_mem_still_sizes_normal_memories() -> None:
    outcome = Session().evaluate("mem(4096, 36)", commit=False)
    assert outcome.value is not None
    assert outcome.value.number == 147456
    assert outcome.value.note == "addr 12 bits, 18 KiB"


# -- power guard identities ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1**10000000", "1"),
        ("0**10000000", "0"),
        ("(-1)**10000000", "1"),
        ("(-1)**9999999", "-1"),
        ("0**0", "1"),
        ("1**0", "1"),
    ],
)
def test_trivial_powers_are_not_rejected_as_too_large(text: str, expected: str) -> None:
    # Sizing these by bit_length made 1**10000000 a "result too large" error.
    assert _display(Session(), text) == expected


def test_genuinely_large_powers_are_still_rejected() -> None:
    with pytest.raises(CalcError) as exc:
        Session().evaluate("2**999999", commit=False)
    assert exc.value.message == "result too large"


# -- the preview renderer, which runs before evaluation ------------------------------


def test_huge_exponent_falls_back_from_superscript() -> None:
    # str() on the exponent ran before the evaluator could reject the power.
    assert Session().evaluate("0 ** 1e5000", commit=False).normalized == "0**1e+5000"


def test_normal_exponents_still_render_as_superscripts() -> None:
    session = Session()
    for text, expected in (("2**10", "2¹⁰"), ("2**64", "2⁶⁴"), ("2**-1", "2⁻¹")):
        assert session.evaluate(text, commit=False).normalized == expected


def test_csr_field_index_is_bounded() -> None:
    with pytest.raises(CalcError) as exc:
        Session().evaluate("csr(0, EN[1e5000])", commit=False)
    assert exc.value.message == "field bit index must be 0..4095"


def test_csr_field_past_the_word_size_still_reports_that() -> None:
    # The bound must sit above any word size, so this stays a decode error.
    with pytest.raises(CalcError) as exc:
        Session(word_size=8).evaluate("csr(0, A[8])", commit=False)
    assert exc.value.message == "field A[8] is outside the 8-bit word"


# -- totality ------------------------------------------------------------------------


PATHOLOGICAL = [
    "2**20000", "10**5000", "1e5000", "99999**3000", "2**14300", "2**999999",
    "exp(2**20000)", "exp(2**300000)", "period(exp(-2**20000))", "0 ** 1e5000",
    "2 ** 1e5000", "csr(0, EN[1e5000])", "mem(2**2000, 1)", "fix(1e5000, 1, 15)",
    "sqrt(2**20000)", "1e9 ** 32Ki", "-2**20000", "~(2**20000)", "(2**20000)[3:0]",
    "float64(2**20000)", "unfix(2**20000, 1, 15)", "clog2(2**20000)", "1e-5000",
]


@pytest.mark.parametrize("text", PATHOLOGICAL)
def test_display_pipeline_is_total(text: str) -> None:
    """Every display path must finish, and fail only as a CalcError."""
    session = Session()
    started = time.perf_counter()
    try:
        outcome = session.evaluate(text, commit=False)
        if outcome.value is not None:
            session.format_value(outcome.value)
            session.views_for(outcome.value)
            session.float_views_for(outcome.value)
    except CalcError:
        pass
    # Generous next to the ~0.5s worst case, but these used to take 22s or hang
    # outright — and this runs on the debounced preview, i.e. while typing.
    assert time.perf_counter() - started < 10.0
