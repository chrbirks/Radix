"""Pretty-printer for the live preview line.

Renders an AST back to text with everything *resolved*: literals normalized
(``4.7k`` → ``4700``), variables and constants substituted with their current
values, ``*`` (explicit or implicit) shown as ``×``, and ``^`` spelled ``XOR``
so its meaning is unmistakable. Non-negative integer exponents render as
superscripts (``(0.002)²``, ``2¹⁰``).

Grouping is made *explicit*: on top of the parentheses strictly required to
re-parse (a child binding looser than its parent), a binary child whose
precedence differs from its binary parent's — i.e. it binds tighter and so
groups first — is also parenthesized. That surfaces surprising precedence like
``16 >> (2 + 16) >> 2`` (``+`` binds tighter than ``>>``) directly in the
preview. A superscript power (``2³``) is self-grouping, so it is treated as an
atom and never gains clarifying parens; unary operators are likewise left as-is
— clarifying parens apply to a binary under a binary only.
"""

from __future__ import annotations

from collections.abc import Mapping

from radix.engine import numsyntax
from radix.engine.csr import flatten_spec
from radix.engine.formatter import format_number
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
from radix.engine.numsyntax import NumSyntax
from radix.engine.parser import BINARY_BP, SLICE_BP, UNARY_BP
from radix.engine.values import Value

_SUPERSCRIPTS = {"0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
                 "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹", "-": "⁻"}

_OP_DISPLAY = {"*": "×", "^": "XOR"}

# A superscript is a readability aid — past a handful of digits it stops being
# one. The cap also keeps this off str()'s int->digit limit, which matters
# because the preview renders *before* evaluation: without it an exponent too
# wide to print would crash here rather than reaching the evaluator's own
# "result too large".
MAX_SUPERSCRIPT_DIGITS = 6
_MAX_SUPERSCRIPT = 10**MAX_SUPERSCRIPT_DIGITS


def render(
    node: Node,
    variables: Mapping[str, Value],
    ans: Value | None,
    syntax: NumSyntax = numsyntax.DEFAULT,
) -> str:
    return _render(node, variables, ans, 0, syntax=syntax)


def _render(
    node: Node,
    variables: Mapping[str, Value],
    ans: Value | None,
    parent_bp: int,
    parent_op_bp: int | None = None,
    syntax: NumSyntax = numsyntax.DEFAULT,
) -> str:
    dec = syntax.decimal
    if isinstance(node, Literal):
        return format_number(Value(node.value), decimal=dec)
    if isinstance(node, Name):
        if node.ident == "ans" and ans is not None:
            return format_number(ans, decimal=dec)
        if node.ident in variables:
            return format_number(variables[node.ident], decimal=dec)
        return node.ident  # pi, e, undefined names: keep symbolic
    if isinstance(node, Unary):
        inner = _render(node.operand, variables, ans, UNARY_BP, syntax=syntax)
        return _paren(f"{node.op}{inner}", UNARY_BP, parent_bp)
    if isinstance(node, Binary):
        return _render_binary(node, variables, ans, parent_bp, parent_op_bp, syntax)
    if isinstance(node, Call):
        sep = f"{syntax.arg_sep} "
        if node.func == "csr" and node.args:
            value_text = _render(node.args[0], variables, ans, 0, syntax=syntax)
            parts = [value_text] + [_render_spec(a, syntax) for a in node.args[1:]]
            return f"csr({sep.join(parts)})"
        args = sep.join(_render(a, variables, ans, 0, syntax=syntax) for a in node.args)
        return f"{node.func}({args})"
    if isinstance(node, Slice):
        operand = _render(node.operand, variables, ans, SLICE_BP, syntax=syntax)
        lsb = _render(node.lsb, variables, ans, 0, syntax=syntax)
        if node.msb is None:
            return f"{operand}[{lsb}]"
        msb = _render(node.msb, variables, ans, 0, syntax=syntax)
        return f"{operand}[{msb}:{lsb}]"
    if isinstance(node, Field):
        operand = _render(node.operand, variables, ans, SLICE_BP, syntax=syntax)
        return f"{operand}.{node.name}"
    if isinstance(node, Assign):
        return f"{node.target} ← {_render(node.expr, variables, ans, 0, syntax=syntax)}"
    return "?"  # pragma: no cover


def _render_binary(
    node: Binary,
    variables: Mapping[str, Value],
    ans: Value | None,
    parent_bp: int,
    parent_op_bp: int | None,
    syntax: NumSyntax = numsyntax.DEFAULT,
) -> str:
    bp = BINARY_BP[node.op]
    if node.op == "**":
        superscript = _superscript_exponent(node.right)
        if superscript is not None:
            inner = _render(node.left, variables, ans, 0, syntax=syntax)
            base = inner if _is_atom(node.left) else f"({inner})"
            # A superscript is self-grouping: only *required* parens, never
            # clarifying ones, so `2**3 + 1` stays `2³ + 1`.
            return _paren(base + superscript, bp, parent_bp)
        left = _render(node.left, variables, ans, bp, bp, syntax)
        right = _render(node.right, variables, ans, bp, bp, syntax)  # right-assoc
        return _clarify(f"{left}**{right}", bp, parent_bp, parent_op_bp)
    left = _render(node.left, variables, ans, bp, bp, syntax)
    right = _render(node.right, variables, ans, bp + 1, bp, syntax)
    op = _OP_DISPLAY.get(node.op, node.op)
    return _clarify(f"{left} {op} {right}", bp, parent_bp, parent_op_bp)


def _render_spec(node: Node, syntax: NumSyntax = numsyntax.DEFAULT) -> str:
    """Render a csr()-spec argument as literal field syntax (no substitution)."""
    parts = []
    for leaf in flatten_spec(node):
        if isinstance(leaf, Slice) and isinstance(leaf.operand, Name):
            name = leaf.operand.ident
            # Bounds go through _render like any other literal: its formatting
            # already matches what a bare str() gave, and it stays safe for a
            # value too wide to print (the preview runs before evaluation, so
            # an out-of-range bound reaches here before anything rejects it).
            lsb = _render(leaf.lsb, {}, None, 0, syntax=syntax)
            if leaf.msb is None:
                parts.append(f"{name}[{lsb}]")
            else:
                parts.append(f"{name}[{_render(leaf.msb, {}, None, 0, syntax=syntax)}:{lsb}]")
        else:
            parts.append(_render(leaf, {}, None, 0, syntax=syntax))
    return " ".join(parts)


def _superscript_exponent(node: Node) -> str | None:
    """Superscript text for an integer-literal exponent, or None.

    Handles a plain non-negative literal (``2**10`` → ``¹⁰``) and a negated one
    (``2**-1`` / ``2**(-1)``, parsed as ``-`` over a literal → ``⁻¹``). Anything
    else (a variable, a compound expression) returns None so the caller falls
    back to textual ``**``.
    """
    if (
        isinstance(node, Literal)
        and isinstance(node.value, int)
        and 0 <= node.value < _MAX_SUPERSCRIPT
    ):
        return "".join(_SUPERSCRIPTS[d] for d in str(node.value))
    if (
        isinstance(node, Unary)
        and node.op == "-"
        and isinstance(node.operand, Literal)
        and isinstance(node.operand.value, int)
        and 0 <= node.operand.value < _MAX_SUPERSCRIPT
    ):
        return "".join(_SUPERSCRIPTS[d] for d in f"-{node.operand.value}")
    return None


def _is_atom(node: Node) -> bool:
    return isinstance(node, (Literal, Name, Call, Slice))


def _paren(text: str, bp: int, parent_bp: int) -> str:
    return f"({text})" if bp < parent_bp else text


def _clarify(text: str, bp: int, parent_bp: int, parent_op_bp: int | None) -> str:
    """Wrap a binary subexpression when parens are required *or* clarifying.

    Required: the node binds looser than its slot (``bp < parent_bp``).
    Clarifying: the node sits under a binary parent of a *different* precedence
    (``parent_op_bp`` set and ``!= bp``) — it binds tighter and groups first, so
    the parens make that grouping visible even though re-parsing wouldn't need
    them. ``parent_op_bp`` is ``None`` at the top level and under non-binary
    parents (function args, slices, unary), which stay paren-free.
    """
    if bp < parent_bp:
        return f"({text})"
    if parent_op_bp is not None and bp != parent_op_bp:
        return f"({text})"
    return text
