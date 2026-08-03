"""Shared helpers for engine-level golden and oracle tests.

Every helper evaluates on a fresh ``Session`` so cases stay independent;
settings are applied as attribute assignments, matching how the UI mutates
the session.
"""

from __future__ import annotations

from collections.abc import Callable

import mpmath

from radix.engine.formatter import IntegerViews
from radix.engine.values import Number
from radix.session import Session


def make_session(**settings: object) -> Session:
    session = Session()
    for key, value in settings.items():
        setattr(session, key, value)
    return session


def run(text: str, **settings: object) -> str:
    """Evaluate on a fresh session and return the primary formatted text."""
    session = make_session(**settings)
    outcome = session.evaluate(text)
    assert outcome.value is not None
    return session.format_value(outcome.value)


def run_number(text: str, **settings: object) -> Number:
    """Evaluate on a fresh session and return the raw result number."""
    session = make_session(**settings)
    outcome = session.evaluate(text)
    assert outcome.value is not None
    return outcome.value.number


def run_views(text: str, **settings: object) -> tuple[str, IntegerViews]:
    """Formatted text plus the hex/dec/bin views of an integer result."""
    session = make_session(**settings)
    outcome = session.evaluate(text)
    assert outcome.value is not None
    views = session.views_for(outcome.value)
    assert views is not None
    return session.format_value(outcome.value), views


def assert_close(text: str, oracle: Callable[[], Number], **settings: object) -> None:
    """Compare an engine result against an independently computed oracle.

    The oracle runs at 50 dps — double the engine's 25-dps working precision —
    and the comparison demands 20 correct significant digits, far beyond what
    float64-quality math (~16 digits) could deliver. That pins the working-
    precision contract, not just the 12 displayed digits.
    """
    actual = run_number(text, **settings)
    with mpmath.workdps(50):
        expected = mpmath.mpf(oracle())
        assert mpmath.almosteq(
            mpmath.mpf(actual), expected, rel_eps=mpmath.mpf(10) ** -20
        ), f"{text}: got {actual!r}, oracle says {expected!r}"
