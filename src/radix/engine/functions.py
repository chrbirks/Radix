"""Built-in function and constant tables.

This is the single source of truth: the evaluator dispatches through it and the
help system renders from it, so documentation can never drift from behavior.
Handlers receive plain numbers plus the evaluation context (word size,
signedness, angle unit) and return a number; argument-count checking is done by
the evaluator from the declared arity.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import mpmath

from radix.engine.values import Number, Value

# Handlers may return a bare number, or a Value carrying display metadata
# (declared width, SI-suffix preference, a note).
Handler = Callable[[list[Number], "EvalContext"], "Number | Value"]


@dataclass(frozen=True)
class EvalContext:
    word_size: int  # 8 | 16 | 32 | 64
    signed: bool
    angle_deg: bool  # True = degrees, False = radians
    decimal: str = "."  # decimal point for engine-built display text (viz/notes)


@dataclass(frozen=True)
class FunctionSpec:
    name: str
    arity: tuple[int, int]  # (min, max) argument count
    params: str  # display argument names, e.g. "x" or "value, m, n"
    category: str  # help-pane grouping, e.g. "Bit utilities"
    summary: str
    example: str
    handler: Handler

    @property
    def signature(self) -> str:
        return f"{self.name}({self.params})"

    def signature_sep(self, sep: str = ", ") -> str:
        """Signature with the argument separator swapped (`; ` in comma mode)."""
        return f"{self.name}({self.params.replace(', ', sep)})"


class FunctionDomainError(ValueError):
    """Raised by handlers on domain errors; the evaluator adds the span."""


def _mpf(x: Number) -> mpmath.mpf:
    return mpmath.mpf(x)


def _real_or_domain_error(result: object, what: str) -> mpmath.mpf:
    if isinstance(result, mpmath.mpc) or (
        isinstance(result, mpmath.mpf) and not mpmath.isfinite(result)
    ):
        raise FunctionDomainError(f"{what}: argument out of domain")
    assert isinstance(result, mpmath.mpf)
    return result


def _trig(fn: Callable[[mpmath.mpf], object]) -> Callable[[list[Number], EvalContext], Number]:
    def handler(args: list[Number], ctx: EvalContext) -> Number:
        x = _mpf(args[0])
        if ctx.angle_deg:
            x = x * mpmath.pi / 180
        return _real_or_domain_error(fn(x), "trig")

    return handler


def _inverse_trig(
    fn: Callable[[mpmath.mpf], object],
) -> Callable[[list[Number], EvalContext], Number]:
    def handler(args: list[Number], ctx: EvalContext) -> Number:
        result = _real_or_domain_error(fn(_mpf(args[0])), "inverse trig")
        if ctx.angle_deg:
            result = result * 180 / mpmath.pi
        return result

    return handler


def _plain(
    fn: Callable[[mpmath.mpf], object], what: str
) -> Callable[[list[Number], EvalContext], Number]:
    def handler(args: list[Number], ctx: EvalContext) -> Number:
        return _real_or_domain_error(fn(_mpf(args[0])), what)

    return handler


def _abs(args: list[Number], ctx: EvalContext) -> Number:
    x = args[0]
    return abs(x) if isinstance(x, int) else abs(_mpf(x))


def _floor(args: list[Number], ctx: EvalContext) -> Number:
    x = args[0]
    return x if isinstance(x, int) else int(_real_or_domain_error(mpmath.floor(_mpf(x)), "floor"))


def _ceil(args: list[Number], ctx: EvalContext) -> Number:
    x = args[0]
    return x if isinstance(x, int) else int(_real_or_domain_error(mpmath.ceil(_mpf(x)), "ceil"))


def _round(args: list[Number], ctx: EvalContext) -> Number:
    x = args[0]
    return x if isinstance(x, int) else int(_real_or_domain_error(mpmath.nint(_mpf(x)), "round"))


def _sqrt(args: list[Number], ctx: EvalContext) -> Number:
    x = args[0]
    if isinstance(x, int) and x >= 0:
        root = math.isqrt(x)
        if root * root == x:
            return root
    return _real_or_domain_error(mpmath.sqrt(_mpf(x)), "sqrt")


FUNCTIONS: dict[str, FunctionSpec] = {}


def _register(
    name: str,
    arity: tuple[int, int],
    params: str,
    category: str,
    summary: str,
    example: str,
    handler: Handler,
) -> None:
    FUNCTIONS[name] = FunctionSpec(name, arity, params, category, summary, example, handler)


_TRIG = "Trigonometry"
_HYP = "Hyperbolic"
_LOG = "Logarithms & exponentials"
_ROUND = "Roots & rounding"
_REG = "Register fields"

_trig_note = "uses the current deg/rad setting"
_inv_note = "result in the current angle unit"
_register("sin", (1, 1), "x", _TRIG, f"Sine ({_trig_note}).", "sin(pi/4)", _trig(mpmath.sin))
_register("cos", (1, 1), "x", _TRIG, f"Cosine ({_trig_note}).", "cos(0)", _trig(mpmath.cos))
_register("tan", (1, 1), "x", _TRIG, f"Tangent ({_trig_note}).", "tan(pi/8)", _trig(mpmath.tan))
_register(
    "asin", (1, 1), "x", _TRIG,
    f"Inverse sine; {_inv_note}.", "asin(0.5)", _inverse_trig(mpmath.asin),
)
_register(
    "acos", (1, 1), "x", _TRIG,
    f"Inverse cosine; {_inv_note}.", "acos(0.5)", _inverse_trig(mpmath.acos),
)
_register(
    "atan", (1, 1), "x", _TRIG,
    f"Inverse tangent; {_inv_note}.", "atan(1)", _inverse_trig(mpmath.atan),
)
_register("sinh", (1, 1), "x", _HYP, "Hyperbolic sine.", "sinh(1)", _plain(mpmath.sinh, "sinh"))
_register("cosh", (1, 1), "x", _HYP, "Hyperbolic cosine.", "cosh(1)", _plain(mpmath.cosh, "cosh"))
_register("tanh", (1, 1), "x", _HYP, "Hyperbolic tangent.", "tanh(1)", _plain(mpmath.tanh, "tanh"))
_register("log", (1, 1), "x", _LOG, "Base-10 logarithm.", "log(1000)", _plain(mpmath.log10, "log"))
_register("ln", (1, 1), "x", _LOG, "Natural logarithm.", "ln(e)", _plain(mpmath.log, "ln"))
_register(
    "log2", (1, 1), "x", _LOG,
    "Base-2 logarithm.", "log2(1024)", _plain(lambda x: mpmath.log(x, 2), "log2"),
)
_register(
    "exp", (1, 1), "x", _LOG, "e raised to the argument.", "exp(1)", _plain(mpmath.exp, "exp")
)
_register("sqrt", (1, 1), "x", _ROUND, "Square root (exact for perfect squares).", "sqrt(2)", _sqrt)
_register("abs", (1, 1), "x", _ROUND, "Absolute value.", "abs(-4)", _abs)
_register("floor", (1, 1), "x", _ROUND, "Round down to an integer.", "floor(2.7)", _floor)
_register("ceil", (1, 1), "x", _ROUND, "Round up to an integer.", "ceil(2.1)", _ceil)
_register("round", (1, 1), "x", _ROUND, "Round to the nearest integer.", "round(2.5)", _round)


def _csr_stub(args: list[Number], ctx: EvalContext) -> Number:
    raise AssertionError("csr() is macro-dispatched in the evaluator")  # pragma: no cover


_register(
    "csr", (2, 2), "value, NAME[msb:lsb] ...", _REG,
    "Decode value into named bit-fields; draws them on the REGISTER grid.",
    "csr(0xF3, MODE[7:4] CMD[3:0])", _csr_stub,
)

CONSTANTS: dict[str, tuple[Number, str]] = {
    "pi": (mpmath.mpf(0), "The circle constant π."),  # filled in below after dps set
    "e": (mpmath.mpf(0), "Euler's number."),
}


def refresh_constants() -> None:
    """(Re)compute constants at the current working precision."""
    CONSTANTS["pi"] = (+mpmath.pi, CONSTANTS["pi"][1])
    CONSTANTS["e"] = (+mpmath.e, CONSTANTS["e"][1])


refresh_constants()
