"""The engine's value model.

Two runtime value kinds flow through the evaluator:

- ``int``: exact, arbitrary precision. Stays exact until a float-producing
  operation. Bitwise/shift operators accept only this kind.
- ``mpmath.mpf``: real numbers at elevated working precision (no float64
  artifacts like 0.1 + 0.2).

A value may carry an optional *declared width* (from HDL sized literals such as
``8'hFF``) which the UI uses to decide how many bit cells to light. Width is
display metadata only — it never changes arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeAlias

import mpmath

if TYPE_CHECKING:
    from radix.engine.csr import Csr
    from radix.engine.viz import VizPayload

# Working precision (decimal digits) for real-number math. Display precision is
# independent and much lower; see formatter.py.
WORKING_DPS = 25

# Ceiling on the magnitude of a real, stated in the same currency as the
# evaluator's integer ceiling (MAX_POW_RESULT_BITS): about a million bits, so
# reals top out near 10**301030 just as exact ints do. Two costs sit behind it.
# An mpf is ``man * 2**exp``, and decimal conversion works in the size of that
# *exponent* — measured at ~0ms for a 61-bit exponent, 0.6s at 5k bits, 22s at
# 20k, and a hard failure past ~14k where the decimal exponent outgrows Python's
# int->str limit. Separately, any handler converting a real back to int (fix(),
# clkdiv()) materializes that many bits. Holding reals and ints to one budget
# keeps either from blowing past the other.
MAX_MAGNITUDE_BITS = 1_000_000

# mpmath ships no type stubs, so mpf is Any to the type checker.
Mpf: TypeAlias = Any
Number: TypeAlias = int | Mpf


@dataclass(frozen=True)
class Value:
    """Evaluation result: a number plus optional display metadata."""

    number: Number
    declared_width: int | None = None  # from HDL sized literals, e.g. 8 for 8'hFF
    prefer_si: bool = False  # period()/freq(): render with an SI suffix (10n, 125M)
    note: str | None = None  # e.g. fix(): quantization error, shown next to the result
    viz: VizPayload | None = None  # structured payload for the UI's VizPanel
    csr: Csr | None = None  # csr field layout for register-decode results

    @property
    def is_integer(self) -> bool:
        return isinstance(self.number, int)


def set_working_precision() -> None:
    mpmath.mp.dps = WORKING_DPS


# Engine-wide invariant: importing the engine sets the working precision.
set_working_precision()


def magnitude_fits(n: Number) -> bool:
    """True if ``n`` is small enough to render and convert in bounded time.

    Exact ints always qualify — their width is already bounded where they are
    produced, by the evaluator's result guards. Reals qualify while their binary
    exponent stays inside ``MAX_MAGNITUDE_BITS``, in either direction: a value
    too close to zero is as dangerous as a huge one, since ``period()``/``freq()``
    take its reciprocal.
    """
    if isinstance(n, int):
        return True
    if not mpmath.isfinite(n):
        return False
    _sign, _man, exp, bc = n._mpf_
    return abs(int(exp + bc)) <= MAX_MAGNITUDE_BITS


def value_to_json(value: Value) -> dict[str, Any]:
    """JSON-safe representation of a value, for session persistence.

    ``mpf`` reals round-trip bit-exact via mpmath's internal
    ``(sign, man, exp, bc)`` tuple — all plain ints, regardless of working
    precision. ``viz`` is dropped: it's a transient display payload
    recomputed by evaluation, not meaningful to freeze.
    """
    from radix.engine.csr import csr_to_json

    if isinstance(value.number, int):
        number: dict[str, Any] = {"kind": "int", "value": value.number}
    else:
        number = {"kind": "real", "mpf": list(value.number._mpf_)}
    return {
        "number": number,
        "declared_width": value.declared_width,
        "prefer_si": value.prefer_si,
        "note": value.note,
        "csr": csr_to_json(value.csr) if value.csr is not None else None,
    }


def _int_or_raise(raw: object, what: str) -> int:
    # bool is an int subclass; a stored `true` is corruption, not a width.
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ValueError(f"{what} is not an integer")
    return raw


def value_from_json(data: dict[str, Any]) -> Value:
    """Inverse of ``value_to_json``. Raises on malformed data.

    Shape validation is strict rather than best-effort: ``make_mpf`` accepts any
    4-tuple without checking it, so a malformed one would build a Value that
    only blows up much later, at display time, far from this call. *Range* is
    deliberately not policed here — this codec round-trips faithfully, including
    inf; deciding what a session may hold is ``Session.load_state_json``'s job.
    """
    from radix.engine.csr import csr_from_json

    number_data = data["number"]
    number: Number
    if number_data["kind"] == "int":
        number = _int_or_raise(number_data["value"], "stored integer")
    else:
        parts = number_data["mpf"]
        if not isinstance(parts, list) or len(parts) != 4:
            raise ValueError("stored real is not a 4-part mpf tuple")
        number = mpmath.make_mpf(tuple(_int_or_raise(p, "mpf component") for p in parts))
    width = data["declared_width"]
    if width is not None:
        _int_or_raise(width, "declared_width")
    csr_data = data["csr"]
    return Value(
        number=number,
        declared_width=data["declared_width"],
        prefer_si=data["prefer_si"],
        note=data["note"],
        csr=csr_from_json(csr_data) if csr_data is not None else None,
    )
