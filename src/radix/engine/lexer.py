"""Lexer for the unified calculator grammar.

Disambiguation rules (the spec — see plan and tests):

- A letter-run directly after a decimal literal is an SI/binary suffix only if
  the ENTIRE run is exactly one suffix token; otherwise the run is emitted as a
  separate identifier (the parser turns adjacency into implicit multiplication).
  So ``2pi`` = 2·pi, ``2p`` = 2e-12, ``4k`` = 4000, ``2pk`` = 2·<variable pk>.
- ``e``/``E`` is an exponent marker only when immediately followed by digits or
  a sign and digits (``1.5e-9``); otherwise it is an identifier (``2e`` = 2·e).
- Based literals (``0xFF``, ``0b1010``, ``0o17``) and HDL literals never take
  suffixes.
- HDL sized literals: ``8'hFF``, ``12'b1010_1010``, ``4'd9``, ``8'o17`` — the
  width is attached to the token for the bit panel; a value wider than the
  declared width is an error. VHDL hex strings ``x"FF"`` get width 4·digits.
- Prefixed literals: ``hFF`` and ``xFF`` are hex, ``b1010`` is binary — an
  identifier-shaped run counts as one of these only if everything after the
  lowercase prefix is a valid digit of that base (plus ``_``). Like the SI
  rule, the literal reading always wins, so ``b1`` or ``x0`` cannot be
  variable names; ``bad`` or ``h2o`` are ordinary identifiers.

Suffixed decimal literals are computed exactly via Fraction, so ``4.7k`` is the
exact int 4700 and stays usable with bitwise operators.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

import mpmath

from radix.engine import numsyntax
from radix.engine.errors import LexError, Span
from radix.engine.numsyntax import NumSyntax
from radix.engine.values import Number

SI_SUFFIXES: dict[str, int] = {
    "f": -15,
    "p": -12,
    "n": -9,
    "u": -6,
    "µ": -6,
    "m": -3,
    "k": 3,
    "M": 6,
    "G": 9,
    "T": 12,
}
BINARY_SUFFIXES: dict[str, int] = {"Ki": 2**10, "Mi": 2**20, "Gi": 2**30}

# Longest first so ** << >> // match before their one-char prefixes. The
# argument separator (`,` or `;`) is not in this shared list — each Lexer
# appends the active one, so `,` is a plain decimal char in comma mode.
OPERATORS_BASE = ["**", "<<", ">>", "//", "|", "^", "&", "+", "-", "*", "/", "%",
                  "~", "(", ")", "[", "]", ":", "=", "."]

_HDL_BASES = {"h": 16, "b": 2, "d": 10, "o": 8}


@dataclass(frozen=True)
class Token:
    kind: str  # "NUMBER" | "IDENT" | "OP" | "EOF"
    text: str
    span: Span
    value: Number | None = None
    declared_width: int | None = None


def _is_ident_start(ch: str) -> bool:
    return ch.isalpha() or ch == "_" or ch == "µ"


def _is_ident_cont(ch: str) -> bool:
    return ch.isalnum() or ch == "_" or ch == "µ"


def _decimal_to_number(mantissa: str, exp10: int, decimal_inputs: str = ".") -> Number:
    for ch in decimal_inputs:
        if ch != ".":
            mantissa = mantissa.replace(ch, ".")  # locale decimal → canonical "."
    float(mantissa)  # validates digit-separator placement; raises ValueError
    normalized = mantissa.replace("_", "")
    if normalized.startswith("."):
        normalized = "0" + normalized
    if normalized.endswith("."):
        normalized += "0"
    frac = Fraction(normalized) * Fraction(10) ** exp10
    if frac.denominator == 1:
        return int(frac)
    return mpmath.mpf(frac.numerator) / mpmath.mpf(frac.denominator)


class Lexer:
    def __init__(self, text: str, syntax: NumSyntax = numsyntax.DEFAULT) -> None:
        self.text = text
        self.pos = 0
        self.syntax = syntax
        self.operators = (*OPERATORS_BASE, syntax.arg_sep)

    def tokens(self) -> list[Token]:
        out: list[Token] = []
        while True:
            tok = self._next()
            out.append(tok)
            if tok.kind == "EOF":
                return out

    # -- internals ---------------------------------------------------------

    def _peek(self, offset: int = 0) -> str:
        i = self.pos + offset
        return self.text[i] if i < len(self.text) else ""

    def _next(self) -> Token:
        while self._peek().isspace():
            self.pos += 1
        start = self.pos
        ch = self._peek()
        if ch == "":
            return Token("EOF", "", Span(start, start))
        if ch.isdigit() or (ch in self.syntax.decimal_inputs and self._peek(1).isdigit()):
            return self._number(start)
        if _is_ident_start(ch):
            return self._ident_or_vhdl(start)
        for op in self.operators:
            if self.text.startswith(op, self.pos):
                self.pos += len(op)
                return Token("OP", op, Span(start, self.pos))
        raise LexError(f"unexpected character {ch!r}", Span(start, start + 1))

    def _take_while(self, pred: Callable[[str], bool]) -> str:
        begin = self.pos
        while self._peek() and pred(self._peek()):
            self.pos += 1
        return self.text[begin : self.pos]

    def _number(self, start: int) -> Token:
        if self._peek() == "0" and self._peek(1) in ("x", "X", "b", "B", "o", "O"):
            return self._based_number(start)
        decimals = self.syntax.decimal_inputs
        mantissa = self._take_while(lambda c: c.isdigit() or c == "_" or c in decimals)
        # HDL sized literal: width'hFF etc.
        if self._peek() == "'" and self._peek(1).lower() in _HDL_BASES:
            return self._hdl_number(start, mantissa)
        # Exponent: e/E only when followed by digits or sign+digits.
        if self._peek() in ("e", "E"):
            after = self._peek(1)
            if after.isdigit() or (after in ("+", "-") and self._peek(2).isdigit()):
                self.pos += 1  # e
                if self._peek() in ("+", "-"):
                    self.pos += 1
                self._take_while(str.isdigit)
        literal_text = self.text[start : self.pos]
        try:
            marker = "e" if "e" in literal_text else "E"
            if marker in literal_text:
                mant, _, exp = literal_text.partition(marker)
                value = _decimal_to_number(mant, int(exp), decimals)
            else:
                value = _decimal_to_number(literal_text, 0, decimals)
        except (ValueError, ZeroDivisionError) as exc:
            raise LexError(f"malformed number {literal_text!r}", Span(start, self.pos)) from exc
        # SI / binary suffix: the entire adjacent letter-run must be one suffix.
        run_start = self.pos
        run = self._take_while(_is_ident_cont)
        if run:
            if run in BINARY_SUFFIXES:
                value = _apply_binary_suffix(value, run)
            elif run in SI_SUFFIXES:
                value = _apply_si_suffix(value, run)
            else:
                self.pos = run_start  # not a suffix: separate IDENT token
        return Token("NUMBER", self.text[start : self.pos], Span(start, self.pos), value)

    def _based_number(self, start: int) -> Token:
        base_ch = self._peek(1).lower()
        base = {"x": 16, "b": 2, "o": 8}[base_ch]
        self.pos += 2
        digits = self._take_while(lambda c: c.isalnum() or c == "_")
        text = self.text[start : self.pos]
        span = Span(start, self.pos)
        try:
            value = int(digits, base)
        except ValueError as exc:
            raise LexError(f"malformed base-{base} literal {text!r}", span) from exc
        return Token("NUMBER", text, span, value)

    def _hdl_number(self, start: int, width_text: str) -> Token:
        try:
            width = int(width_text)
        except ValueError as exc:
            bad_span = Span(start, self.pos)
            raise LexError(f"malformed literal width {width_text!r}", bad_span) from exc
        base = _HDL_BASES[self._peek(1).lower()]
        self.pos += 2  # ' and base letter
        digits = self._take_while(lambda c: c.isalnum() or c == "_")
        text = self.text[start : self.pos]
        span = Span(start, self.pos)
        if width <= 0:
            raise LexError("literal width must be positive", span)
        try:
            value = int(digits, base)
        except ValueError as exc:
            raise LexError(f"malformed sized literal {text!r}", span) from exc
        if value.bit_length() > width:
            raise LexError(f"value does not fit in {width} bits", span)
        return Token("NUMBER", text, span, value, declared_width=width)

    def _ident_or_vhdl(self, start: int) -> Token:
        run = self._take_while(_is_ident_cont)
        if run in ("x", "X") and self._peek() == '"':
            return self._vhdl_hex(start)
        value = _prefixed_literal(run)
        if value is not None:
            return Token("NUMBER", run, Span(start, self.pos), value)
        return Token("IDENT", run, Span(start, self.pos))

    def _vhdl_hex(self, start: int) -> Token:
        self.pos += 1  # opening quote
        digits = self._take_while(lambda c: c != '"')
        if self._peek() != '"':
            raise LexError('unterminated x"..." literal', Span(start, self.pos))
        self.pos += 1
        text = self.text[start : self.pos]
        span = Span(start, self.pos)
        clean = digits.replace("_", "")
        try:
            value = int(clean, 16)
        except ValueError as exc:
            raise LexError(f"malformed VHDL hex literal {text!r}", span) from exc
        return Token("NUMBER", text, span, value, declared_width=4 * len(clean))


def _prefixed_literal(run: str) -> int | None:
    """hFF / xFF (hex) or b1010 (binary), else None. Lowercase prefix only."""
    if len(run) < 2:
        return None
    base = {"h": 16, "x": 16, "b": 2}.get(run[0])
    if base is None or run[1] == "_":
        return None
    try:
        return int(run[1:], base)
    except ValueError:
        return None


def _apply_si_suffix(value: Number, suffix: str) -> Number:
    exp10 = SI_SUFFIXES[suffix]
    if isinstance(value, int):
        frac = Fraction(value) * Fraction(10) ** exp10
    else:
        # mpf mantissa (e.g. 4.7k): go through Fraction for exactness.
        frac = Fraction(str(value)) * Fraction(10) ** exp10
    if frac.denominator == 1:
        return int(frac)
    return mpmath.mpf(frac.numerator) / mpmath.mpf(frac.denominator)


def _apply_binary_suffix(value: Number, suffix: str) -> Number:
    factor = BINARY_SUFFIXES[suffix]
    if isinstance(value, int):
        return value * factor
    result = value * factor
    as_int = int(result)
    return as_int if result == as_int else result


def tokenize(text: str, syntax: NumSyntax = numsyntax.DEFAULT) -> list[Token]:
    return Lexer(text, syntax).tokens()


def tokenize_prefix(text: str, syntax: NumSyntax = numsyntax.DEFAULT) -> list[Token]:
    """Tokens of the longest valid prefix; never raises (for highlighting)."""
    lexer = Lexer(text, syntax)
    out: list[Token] = []
    while True:
        try:
            tok = lexer._next()
        except LexError:
            return out
        if tok.kind == "EOF":
            return out
        out.append(tok)
