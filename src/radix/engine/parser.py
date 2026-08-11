"""Pratt (top-down operator-precedence) parser over the unified grammar.

Precedence ladder, lowest → highest binding power:

    |          10
    ^  (XOR)   20
    &          30
    << >>      40
    + -        50
    * / // %   60   (implicit multiplication binds here too)
    unary - ~  70
    **         80   (right-associative)
    x[msb:lsb] 90   (postfix bit slice)

An input line is either ``IDENT = expr`` (statement-level assignment) or a bare
expression. ``IDENT(`` is always a function call; adjacency of two operands
(``2pi``, ``3(x+1)``, ``(a)(b)``) is implicit multiplication.

Errors at end-of-input raise IncompleteError so the live preview can tell
"still typing" apart from "genuinely wrong".
"""

from __future__ import annotations

from radix.engine import numsyntax
from radix.engine.errors import IncompleteError, ParseError, Span
from radix.engine.lexer import Token, tokenize
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

BINARY_BP: dict[str, int] = {
    "|": 10,
    "^": 20,
    "&": 30,
    "<<": 40,
    ">>": 40,
    "+": 50,
    "-": 50,
    "*": 60,
    "/": 60,
    "//": 60,
    "%": 60,
    "**": 80,
}
RIGHT_ASSOC = {"**"}
UNARY_BP = 70
IMPLICIT_MUL_BP = 60
SLICE_BP = 90


class Parser:
    def __init__(self, text: str, syntax: NumSyntax = numsyntax.DEFAULT) -> None:
        self.syntax = syntax
        self.toks = tokenize(text, syntax)
        self.i = 0

    # -- token helpers -----------------------------------------------------

    @property
    def cur(self) -> Token:
        return self.toks[self.i]

    def _advance(self) -> Token:
        tok = self.cur
        if tok.kind != "EOF":
            self.i += 1
        return tok

    def _error(self, message: str, span: Span) -> ParseError:
        if self.cur.kind == "EOF":
            return IncompleteError(message, span)
        return ParseError(message, span)

    def _expect_op(self, op: str) -> Token:
        if self.cur.kind == "OP" and self.cur.text == op:
            return self._advance()
        raise self._error(f"expected {op!r}", self.cur.span)

    # -- entry points ------------------------------------------------------

    def parse_line(self) -> Node:
        """Parse a full input line: assignment statement or bare expression."""
        if (
            self.cur.kind == "IDENT"
            and self.toks[self.i + 1].kind == "OP"
            and self.toks[self.i + 1].text == "="
        ):
            target = self._advance()
            self._advance()  # =
            expr = self._expression(0)
            self._expect_eof()
            return Assign(
                Span(target.span.start, expr.span.end), target.text, target.span, expr
            )
        expr = self._expression(0)
        self._expect_eof()
        return expr

    def _expect_eof(self) -> None:
        if self.cur.kind != "EOF":
            raise ParseError(f"unexpected {self.cur.text!r}", self.cur.span)

    # -- Pratt core --------------------------------------------------------

    def _expression(self, min_bp: int) -> Node:
        left = self._nud()
        while True:
            tok = self.cur
            if tok.kind == "OP" and tok.text in BINARY_BP:
                bp = BINARY_BP[tok.text]
                if bp < min_bp:
                    return left
                self._advance()
                rhs_bp = bp if tok.text in RIGHT_ASSOC else bp + 1
                right = self._expression(rhs_bp)
                left = Binary(Span(left.span.start, right.span.end), tok.text, left, right)
            elif tok.kind == "OP" and tok.text == "[":
                if min_bp > SLICE_BP:
                    return left
                left = self._slice(left)
            elif tok.kind == "OP" and tok.text == ".":
                if min_bp > SLICE_BP:
                    return left
                self._advance()
                if self.cur.kind != "IDENT":
                    raise self._error("expected a field name after '.'", self.cur.span)
                name_tok = self._advance()
                left = Field(
                    Span(left.span.start, name_tok.span.end), left, name_tok.text, name_tok.span
                )
            elif self._starts_operand(tok):
                # Implicit multiplication: two adjacent operands.
                if min_bp > IMPLICIT_MUL_BP:
                    return left
                right = self._expression(IMPLICIT_MUL_BP + 1)
                left = Binary(Span(left.span.start, right.span.end), "*", left, right)
            else:
                return left

    @staticmethod
    def _starts_operand(tok: Token) -> bool:
        return tok.kind in ("NUMBER", "IDENT") or (tok.kind == "OP" and tok.text == "(")

    def _nud(self) -> Node:
        tok = self.cur
        if tok.kind == "NUMBER":
            self._advance()
            assert tok.value is not None
            return Literal(tok.span, tok.value, tok.declared_width)
        if tok.kind == "IDENT":
            self._advance()
            if self.cur.kind == "OP" and self.cur.text == "(":
                return self._call(tok)
            return Name(tok.span, tok.text)
        if tok.kind == "OP" and tok.text in ("-", "~"):
            self._advance()
            operand = self._expression(UNARY_BP)
            return Unary(Span(tok.span.start, operand.span.end), tok.text, operand)
        if tok.kind == "OP" and tok.text == "+":
            self._advance()  # unary plus: allowed, a no-op
            return self._expression(UNARY_BP)
        if tok.kind == "OP" and tok.text == "(":
            self._advance()
            inner = self._expression(0)
            closing = self._expect_op(")")
            return _respan(inner, Span(tok.span.start, closing.span.end))
        if tok.kind == "EOF":
            raise IncompleteError("expected an expression", tok.span)
        raise ParseError(f"unexpected {tok.text!r}", tok.span)

    def _call(self, name_tok: Token) -> Node:
        self._advance()  # (
        args: list[Node] = []
        if not (self.cur.kind == "OP" and self.cur.text == ")"):
            args.append(self._expression(0))
            while self.cur.kind == "OP" and self.cur.text == self.syntax.arg_sep:
                self._advance()
                args.append(self._expression(0))
        closing = self._expect_op(")")
        return Call(
            Span(name_tok.span.start, closing.span.end),
            name_tok.text,
            name_tok.span,
            tuple(args),
        )

    def _slice(self, operand: Node) -> Node:
        self._advance()  # [
        first = self._expression(0)
        msb: Node | None = None
        lsb = first
        if self.cur.kind == "OP" and self.cur.text == ":":
            self._advance()
            msb = first
            lsb = self._expression(0)
        closing = self._expect_op("]")
        return Slice(Span(operand.span.start, closing.span.end), operand, msb, lsb)


def _respan(node: Node, span: Span) -> Node:
    """Widen a node's span to include enclosing parentheses."""
    import dataclasses

    return dataclasses.replace(node, span=span)


def parse(text: str, syntax: NumSyntax = numsyntax.DEFAULT) -> Node:
    return Parser(text, syntax).parse_line()
