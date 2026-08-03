"""Calculation-correctness tests for the scientific function table.

Two mechanisms, chosen per case:

- EXACT/DEGREES/BANKERS pin identity values whose mathematically exact result
  is finitely representable at display precision — golden strings, each
  derivable by hand.
- ORACLE compares the raw result against the same quantity recomputed from its
  mathematical definition at 50 dps (``engine_harness.assert_close``), pinning
  the 25-dps working-precision contract where no closed-form display exists.
"""

from __future__ import annotations

from collections.abc import Callable

import mpmath
import pytest

from engine_harness import assert_close, run
from radix.engine.errors import EvalError
from radix.engine.values import Number

# -- exact identities (radians) ----------------------------------------------

EXACT = [
    ("cos(pi)", "-1"),
    ("tan(0)", "0"),
    ("atan(0)", "0"),
    ("sinh(0)", "0"),
    ("cosh(0)", "1"),
    ("tanh(0)", "0"),
    ("exp(0)", "1"),
    ("exp(1)", "2.71828182846"),  # e, 12 significant digits
    ("ln(1)", "0"),
    ("log(0.001)", "-3"),
    ("log2(1048576)", "20"),  # 2**20
    ("floor(-2.5)", "-3"),
    ("floor(2)", "2"),  # integer passes through untouched
    ("ceil(-2.5)", "-2"),
    ("abs(-4.5)", "4.5"),
    ("sqrt(2.25)", "1.5"),
    ("sqrt(0)", "0"),
]


@pytest.mark.parametrize(("text", "expected"), EXACT)
def test_exact_identities(text: str, expected: str) -> None:
    assert run(text) == expected


# -- degrees mode -------------------------------------------------------------

DEGREES = [
    ("cos(60)", "0.5"),
    ("tan(45)", "1"),
    ("sin(150)", "0.5"),
    ("sin(-90)", "-1"),
    ("cos(180)", "-1"),
    ("acos(0.5)", "60"),
    ("acos(0)", "90"),
    ("acos(-1)", "180"),
    ("atan(1)", "45"),
    ("asin(-1)", "-90"),
    ("asin(0.5)", "30"),
]


@pytest.mark.parametrize(("text", "expected"), DEGREES)
def test_degree_mode_identities(text: str, expected: str) -> None:
    assert run(text, angle_deg=True) == expected


# -- oracle comparisons at working precision ----------------------------------

# (input, oracle recomputing the same quantity from its definition, settings).
# Inputs are chosen binary-exact (ints, 0.25, 0.5, 2.5) so engine and oracle
# see the identical mathematical argument.
ORACLE: list[tuple[str, Callable[[], Number], dict[str, object]]] = [
    ("sin(1)", lambda: mpmath.sin(1), {}),
    ("cos(1)", lambda: mpmath.cos(1), {}),
    ("tan(pi/8)", lambda: mpmath.tan(mpmath.pi / 8), {}),
    ("asin(0.75)", lambda: mpmath.asin(mpmath.mpf("0.75")), {}),
    ("acos(0.25)", lambda: mpmath.acos(mpmath.mpf("0.25")), {}),
    ("atan(2)", lambda: mpmath.atan(2), {}),
    ("sinh(1)", lambda: mpmath.sinh(1), {}),
    ("cosh(1)", lambda: mpmath.cosh(1), {}),
    ("tanh(1)", lambda: mpmath.tanh(1), {}),
    ("exp(2.5)", lambda: mpmath.exp(mpmath.mpf("2.5")), {}),
    ("ln(10)", lambda: mpmath.log(10), {}),
    ("log(7)", lambda: mpmath.log10(7), {}),
    ("log2(10)", lambda: mpmath.log(10, 2), {}),
    ("sqrt(2)", lambda: mpmath.sqrt(2), {}),
    ("tan(30)", lambda: mpmath.tan(mpmath.radians(30)), {"angle_deg": True}),
    (
        "atan(0.5)",
        lambda: mpmath.atan(mpmath.mpf("0.5")) * 180 / mpmath.pi,
        {"angle_deg": True},
    ),
]


@pytest.mark.parametrize(
    ("text", "oracle", "settings"), ORACLE, ids=[case[0] for case in ORACLE]
)
def test_against_oracle(
    text: str, oracle: Callable[[], Number], settings: dict[str, object]
) -> None:
    assert_close(text, oracle, **settings)


# -- round(): ties to even ----------------------------------------------------

BANKERS = [
    ("round(2.5)", "2"),
    ("round(3.5)", "4"),
    ("round(-2.5)", "-2"),
    ("round(-3.5)", "-4"),
    ("round(0.5)", "0"),
    ("round(-0.5)", "0"),
    ("round(2.4)", "2"),
    ("round(2.6)", "3"),
    ("round(7)", "7"),
]


@pytest.mark.parametrize(("text", "expected"), BANKERS)
def test_round_ties_to_even(text: str, expected: str) -> None:
    assert run(text) == expected


# -- domain errors ------------------------------------------------------------

DOMAIN_ERRORS = [
    "asin(1.5)",
    "acos(2)",
    "acos(-2)",
    "log(0)",
    "log(-5)",
    "ln(-1)",
    "log2(0)",
    "log2(-4)",
]


@pytest.mark.parametrize("text", DOMAIN_ERRORS)
def test_domain_errors(text: str) -> None:
    with pytest.raises(EvalError):
        run(text)


def test_degree_mode_domain_error() -> None:
    # The deg/rad flag must not change inverse-trig domains.
    with pytest.raises(EvalError):
        run("asin(2)", angle_deg=True)
