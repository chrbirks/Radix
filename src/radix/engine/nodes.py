"""AST node types produced by the parser.

Every node carries a Span so evaluation errors can point at the exact source
text that produced them.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from radix.engine.errors import Span
from radix.engine.values import Number


@dataclass(frozen=True)
class Node:
    span: Span


@dataclass(frozen=True)
class Literal(Node):
    value: Number
    declared_width: int | None = None  # HDL sized literal width (8 for 8'hFF)
    exact: Fraction | None = None  # what `value` rounded, for a non-integer literal


@dataclass(frozen=True)
class Name(Node):
    ident: str


@dataclass(frozen=True)
class Unary(Node):
    op: str  # "-" or "~"
    operand: Node


@dataclass(frozen=True)
class Binary(Node):
    op: str  # "|" "^" "&" "<<" ">>" "+" "-" "*" "/" "//" "%" "**"
    left: Node
    right: Node


@dataclass(frozen=True)
class Call(Node):
    func: str
    func_span: Span  # span of just the function name, for precise errors
    args: tuple[Node, ...]


@dataclass(frozen=True)
class Slice(Node):
    """Verilog-style bit slice/index: x[7:4] or x[3]. msb is None for x[3]."""

    operand: Node
    msb: Node | None
    lsb: Node


@dataclass(frozen=True)
class Field(Node):
    """Postfix field access on a decoded value: CTRL(x).ADDR or ans.EN."""

    operand: Node
    name: str
    name_span: Span


@dataclass(frozen=True)
class Assign(Node):
    """Statement-level `IDENT = expr`. Only valid at the top of an input line."""

    target: str
    target_span: Span
    expr: Node
