"""Hypothesis property tests.

Two invariants from the plan:
1. The parser+evaluator are *total* over arbitrary input — only CalcError
   subclasses may escape, never a hang or a foreign exception.
2. format→parse round-trips equal the original *at displayed precision*
   (formatting at 12 significant digits is lossy by design, so exact equality
   would be a false property).
"""

from __future__ import annotations

import contextlib

import mpmath
from hypothesis import given, settings
from hypothesis import strategies as st

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
