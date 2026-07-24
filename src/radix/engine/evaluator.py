"""Tree-walking evaluator.

Semantics (the spec — see plan and tests):

- Exact ``int`` is preserved until a float-producing operation; ``/`` returns
  an int when the division is exact, otherwise mpf.
- ``//`` truncates toward zero and ``%`` takes the sign of the dividend
  (C-like pair, consistent with each other).
- Bitwise/shift operators require integer operands (explicit error otherwise,
  never silent truncation). Their operands and results are masked to the
  current word size — register-like wrap-on-overflow. ``>>`` is logical when
  unsigned, arithmetic when signed. Ordinary arithmetic is never masked.
- Operand guards keep pathological input (``10**10**10``) an error, not a hang.
"""

from __future__ import annotations

from collections.abc import Mapping

import mpmath

from radix.engine.csr import Csr, csr_from_nodes, decode_note, extract, flatten_spec
from radix.engine.errors import EvalError, Span
from radix.engine.functions import (
    CONSTANTS,
    FUNCTIONS,
    EvalContext,
    FunctionDomainError,
)
from radix.engine.nodes import (
    Assign,
    Binary,
    Call,
    Field,
    Literal,
    Name,
    Node,
    Slice,
    Unary,
)
from radix.engine.values import Number, Value, magnitude_fits

# Guards against pathological input.
MAX_POW_RESULT_BITS = 1_000_000
MAX_SHIFT_COUNT = 1_000_000
MAX_MPF_EXPONENT = 10**8

BIT_OPS = {"|", "^", "&", "<<", ">>"}


def evaluate(
    node: Node,
    ctx: EvalContext,
    variables: Mapping[str, Value],
    ans: Value | None,
    csrs: Mapping[str, Csr] | None = None,
) -> Value:
    """Evaluate an expression AST (not Assign — the session handles those)."""
    ev = _Evaluator(ctx, variables, ans, csrs)
    return ev.eval(node)


class _Evaluator:
    def __init__(
        self,
        ctx: EvalContext,
        variables: Mapping[str, Value],
        ans: Value | None,
        csrs: Mapping[str, Csr] | None = None,
    ) -> None:
        self.ctx = ctx
        self.variables = variables
        self.ans = ans
        self.csrs = csrs

    @property
    def _mask(self) -> int:
        return (1 << self.ctx.word_size) - 1

    def eval(self, node: Node) -> Value:
        if isinstance(node, Literal):
            return Value(node.value, node.declared_width)
        if isinstance(node, Name):
            return self._name(node)
        if isinstance(node, Unary):
            return self._unary(node)
        if isinstance(node, Binary):
            return self._binary(node)
        if isinstance(node, Call):
            return self._call(node)
        if isinstance(node, Slice):
            return self._slice(node)
        if isinstance(node, Field):
            return self._field(node)
        if isinstance(node, Assign):
            raise EvalError("assignment is only allowed at the start of a line", node.span)
        raise EvalError("internal: unknown node", node.span)  # pragma: no cover

    # -- leaves --------------------------------------------------------------

    def _name(self, node: Name) -> Value:
        ident = node.ident
        if ident == "ans":
            if self.ans is None:
                raise EvalError("no previous result", node.span)
            return self.ans
        if ident in CONSTANTS:
            return Value(CONSTANTS[ident][0])
        if ident in self.variables:
            return self.variables[ident]
        if ident in FUNCTIONS:
            raise EvalError(f"{ident} is a function — call it: {ident}(...)", node.span)
        raise EvalError(f"undefined variable {ident!r}", node.span)

    # -- operators -------------------------------------------------------------

    def _unary(self, node: Unary) -> Value:
        operand = self.eval(node.operand)
        if node.op == "-":
            n = operand.number
            return Value(-n if isinstance(n, int) else -mpmath.mpf(n))
        # ~
        a = self._require_int(operand, node.operand.span, "~")
        return Value(~(a & self._mask) & self._mask)

    def _binary(self, node: Binary) -> Value:
        left = self.eval(node.left)
        right = self.eval(node.right)
        op = node.op
        if op in BIT_OPS:
            return self._bit_op(node, left, right)
        a, b = left.number, right.number
        if op == "+":
            return Value(a + b)
        if op == "-":
            return Value(a - b)
        if op == "*":
            return Value(a * b)
        if op == "/":
            return self._true_div(node, a, b)
        if op == "//":
            return self._trunc_div(node, a, b)
        if op == "%":
            return self._c_mod(node, a, b)
        if op == "**":
            return self._power(node, a, b)
        raise EvalError(f"internal: unknown operator {op!r}", node.span)  # pragma: no cover

    def _true_div(self, node: Binary, a: Number, b: Number) -> Value:
        self._check_nonzero(b, node.right.span)
        if isinstance(a, int) and isinstance(b, int):
            q, r = divmod(a, b)
            if r == 0:
                return Value(q)
        return Value(mpmath.mpf(a) / mpmath.mpf(b))

    def _trunc_div(self, node: Binary, a: Number, b: Number) -> Value:
        self._check_nonzero(b, node.right.span)
        if isinstance(a, int) and isinstance(b, int):
            q = abs(a) // abs(b)
            return Value(-q if (a < 0) != (b < 0) else q)
        quotient = mpmath.mpf(a) / mpmath.mpf(b)
        truncated = mpmath.floor(quotient) if quotient >= 0 else mpmath.ceil(quotient)
        return Value(int(truncated))

    def _c_mod(self, node: Binary, a: Number, b: Number) -> Value:
        quotient = self._trunc_div(node, a, b).number
        if isinstance(a, int) and isinstance(b, int):
            assert isinstance(quotient, int)
            return Value(a - quotient * b)
        return Value(mpmath.mpf(a) - mpmath.mpf(quotient) * mpmath.mpf(b))

    def _power(self, node: Binary, a: Number, b: Number) -> Value:
        if isinstance(a, int) and isinstance(b, int):
            if b >= 0:
                if -1 <= a <= 1:
                    # 0, 1 and -1 stay one digit at any exponent, so the
                    # bit-length estimate below would wrongly reject trivially
                    # cheap results like 1**10000000.
                    if a == 1 or b == 0:
                        return Value(1)  # x**0 == 1, including 0**0
                    return Value(0 if a == 0 else (-1 if b % 2 else 1))
                result_bits = b * abs(a).bit_length()
                if result_bits > MAX_POW_RESULT_BITS:
                    raise EvalError("result too large", node.span)
                return Value(a**b)
            if a == 0:
                raise EvalError("0 cannot be raised to a negative power", node.span)
            return Value(mpmath.mpf(1) / mpmath.power(mpmath.mpf(a), -b))
        if abs(mpmath.mpf(b)) > MAX_MPF_EXPONENT:
            raise EvalError("exponent too large", node.right.span)
        base = mpmath.mpf(a)
        if base < 0:
            raise EvalError(
                "negative base with non-integer exponent (complex results not supported)",
                node.span,
            )
        if base == 0 and mpmath.mpf(b) < 0:
            raise EvalError("0 cannot be raised to a negative power", node.span)
        return Value(mpmath.power(base, mpmath.mpf(b)))

    def _bit_op(self, node: Binary, left: Value, right: Value) -> Value:
        op = node.op
        a = self._require_int(left, node.left.span, op)
        b = self._require_int(right, node.right.span, op)
        mask = self._mask
        if op in ("<<", ">>"):
            if b < 0:
                raise EvalError("shift count is negative", node.right.span)
            if b > MAX_SHIFT_COUNT:
                raise EvalError("shift count too large", node.right.span)
            value = a & mask
            if op == "<<":
                return Value((value << b) & mask)
            if self.ctx.signed and value >> (self.ctx.word_size - 1):
                value -= 1 << self.ctx.word_size  # arithmetic shift: sign-extend
            return Value((value >> b) & mask)
        a &= mask
        b &= mask
        if op == "&":
            return Value(a & b)
        if op == "|":
            return Value(a | b)
        return Value((a ^ b) & mask)

    # -- calls and slices ------------------------------------------------------

    def _call(self, node: Call) -> Value:
        if node.func == "csr":
            return self._csr_macro(node)
        spec = FUNCTIONS.get(node.func)
        if spec is not None:
            lo, hi = spec.arity
            if not lo <= len(node.args) <= hi:
                expected = str(lo) if lo == hi else f"{lo}–{hi}"
                raise EvalError(
                    f"{node.func} takes {expected} argument(s), got {len(node.args)}", node.span
                )
            args = [self.eval(arg).number for arg in node.args]
            try:
                result = spec.handler(args, self.ctx)
            except FunctionDomainError as exc:
                raise EvalError(str(exc), node.span) from exc
            value = result if isinstance(result, Value) else Value(result)
            # Guard every call result, not just the line's final value: some
            # handlers pre-format their argument into a note or viz payload, so
            # a runaway has to be stopped at the call that produced it rather
            # than one level further out.
            return guard_displayable(value, node.span)
        if self.csrs and node.func in self.csrs:
            return self._csr_call(node)
        raise EvalError(f"unknown function {node.func!r}", node.func_span)

    def _csr_macro(self, node: Call) -> Value:
        if len(node.args) < 2:
            raise EvalError(
                "csr takes a value and at least one field, e.g. csr(x, EN[7] CMD[3:0])",
                node.span,
            )
        value = self._require_int(self.eval(node.args[0]), node.args[0].span, "field decode")
        leaves: list[Node] = []
        for arg in node.args[1:]:
            leaves += flatten_spec(arg)
        csr = csr_from_nodes(leaves, name=None)
        return self._decode(csr, value, node.span)

    def _csr_call(self, node: Call) -> Value:
        assert self.csrs is not None
        csr = self.csrs[node.func]
        if len(node.args) != 1:
            raise EvalError(
                f"{node.func} takes 1 argument(s), got {len(node.args)}", node.span
            )
        value = self._require_int(self.eval(node.args[0]), node.args[0].span, "field decode")
        return self._decode(csr, value, node.span)

    def _decode(self, csr: Csr, value: int, span: Span) -> Value:
        if csr.top_bit >= self.ctx.word_size:
            field = next((f for f in csr.fields if f.msb == csr.top_bit), csr.fields[0])
            raise EvalError(
                f"field {field.name}[{field.msb}] is outside the {self.ctx.word_size}-bit word",
                span,
            )
        raw = value & self._mask
        return Value(value, csr=csr, note=decode_note(csr, raw))

    def _field(self, node: Field) -> Value:
        operand = self.eval(node.operand)
        if operand.csr is None:
            raise EvalError(
                "no field csr on this value — decode with a csr call "
                "or csr(...) first",
                node.operand.span,
            )
        f = operand.csr.field(node.name)
        if f is None:
            csr_desc = operand.csr.name or "this csr"
            names = ", ".join(fld.name for fld in operand.csr.fields)
            raise EvalError(f"no field {node.name!r} — {csr_desc} has {names}", node.name_span)
        raw = self._require_int(operand, node.operand.span, "field access") & self._mask
        return Value(extract(operand.csr, f, raw), declared_width=f.width)

    def _slice(self, node: Slice) -> Value:
        value = self._require_int(self.eval(node.operand), node.operand.span, "bit slice")
        lsb = self._require_int(self.eval(node.lsb), node.lsb.span, "bit index")
        msb = lsb
        if node.msb is not None:
            msb = self._require_int(self.eval(node.msb), node.msb.span, "bit index")
        if lsb < 0 or msb < lsb:
            raise EvalError(f"invalid bit range [{msb}:{lsb}]", node.span)
        if msb >= self.ctx.word_size:
            raise EvalError(
                f"bit {msb} is outside the {self.ctx.word_size}-bit word", node.span
            )
        width = msb - lsb + 1
        return Value((value & self._mask) >> lsb & ((1 << width) - 1), declared_width=width)

    # -- helpers ---------------------------------------------------------------

    def _require_int(self, value: Value, span: Span, what: str) -> int:
        n = value.number
        if isinstance(n, int):
            return n
        raise EvalError(
            f"{what} requires an integer operand (got a non-integer value)", span
        )

    def _check_nonzero(self, b: Number, span: Span) -> None:
        if (isinstance(b, int) and b == 0) or (not isinstance(b, int) and mpmath.mpf(b) == 0):
            raise EvalError("division by zero", span)


def guard_displayable(value: Value, span: Span) -> Value:
    """Reject results that could never be rendered, so they never reach display.

    Two ways that happens: inf/nan, and a real whose binary exponent has grown
    so large that decimal conversion cannot finish in bounded time (see
    ``values.MAX_MAGNITUDE_BITS``). Both are runaway intermediates rather than
    answers anyone asked for, and letting either through means the UI either
    hangs or dies formatting it.
    """
    n = value.number
    if isinstance(n, int):
        return value
    if not mpmath.isfinite(n):
        raise EvalError("result is not finite", span)
    if not magnitude_fits(n):
        raise EvalError("result is out of range", span)
    return value
