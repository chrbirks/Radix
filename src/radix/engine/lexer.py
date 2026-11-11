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
  declared width is an error. An ``s`` before the base (``8'sh80``) reads the
  pattern as two's complement, as Verilog does. VHDL hex strings ``x"FF"`` get
  width 4·digits.
- Prefixed literals: ``hFF`` and ``xFF`` are hex, ``b1010`` is binary — an
  identifier-shaped run counts as one of these only if everything after the
  lowercase prefix is a valid digit of that base (plus ``_``). Like the SI
  rule, the literal reading always wins, so ``b1`` or ``x0`` cannot be
  variable names; ``bad`` or ``h2o`` are ordinary identifiers.
- A decimal char binds into a number only when a digit follows it. At the
  very end of the line ``1.`` is *incomplete* (the fraction is still being
  typed); anywhere else it is a malformed number, so the comma-mode typo
  ``sin(1, 2)`` errors instead of quietly reading as ``sin(1) × 2``, and
  ``1e5.5`` is not ``1e5 × 0.5``.
- In comma mode a ``,`` glued to the value before it (``50M,5``, ``x,5``,
  ``f(a),5``) or followed by anything but a digit is the period-mode argument
  separator typed out of habit: an error that names ``;``, never ``50M × 0,5``.
  A leading-comma decimal is still fine where nothing precedes it (``,5``,
  ``2 * ,5``), and ``ans.5`` keeps its documented ``ans × 0.5`` reading.
- A literal prefix with nothing after it yet (``0x``, ``8'h``, ``x"F``) at the
  very end of the line is *incomplete*, like ``1.``: the digits are coming.
- A decimal literal is bounded where it is read: ``1e1000000`` is out of range
  at once rather than a million-bit integer built on every preview keystroke.

Suffixed decimal literals are computed exactly via Fraction, so ``4.7k`` is the
exact int 4700 and stays usable with bitwise operators.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

from radix.engine import numsyntax
from radix.engine.errors import CalcError, IncompleteError, LexError, Span
from radix.engine.numsyntax import NumSyntax
from radix.engine.values import MAX_MAGNITUDE_BITS, Number, fraction_to_mpf

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

# The largest decimal exponent a literal may reach: 10**301029 is the last
# power of ten inside the engine's million-bit magnitude budget.
MAX_DECIMAL_EXPONENT = MAX_MAGNITUDE_BITS * 30103 // 100000 - 1


class _OutOfRange(ValueError):
    """A literal whose magnitude is outside the engine's budget."""


@dataclass(frozen=True)
class Token:
    kind: str  # "NUMBER" | "IDENT" | "OP" | "EOF"
    text: str
    span: Span
    value: Number | None = None
    declared_width: int | None = None
    # The literal's exact value when `value` had to round it (0.1, 4.7m): lets
    # a caller that needs more than the working precision re-derive it.
    exact: Fraction | None = None


def _is_ident_start(ch: str) -> bool:
    return ch.isalpha() or ch == "_" or ch == "µ"


def _is_ident_cont(ch: str) -> bool:
    return ch.isalnum() or ch == "_" or ch == "µ"


def _decimal_fraction(mantissa: str, exp10: int, decimal_inputs: str = ".") -> Fraction:
    """The exact value of ``mantissa`` × 10**``exp10``.

    Raises ValueError for a malformed mantissa and ``_OutOfRange`` when the
    magnitude is outside the budget — checked from the digit counts alone, so
    the power of ten is only ever computed once it is known to be affordable.
    """
    for ch in decimal_inputs:
        if ch != ".":
            mantissa = mantissa.replace(ch, ".")  # locale decimal → canonical "."
    float(mantissa)  # validates digit-separator placement; raises ValueError
    normalized = mantissa.replace("_", "")
    if normalized.startswith("."):
        normalized = "0" + normalized
    whole, _, fraction = normalized.partition(".")
    whole = whole.lstrip("0")
    if not whole and not fraction.strip("0"):
        return Fraction(0)  # 0e999999999 is just zero
    if whole:
        magnitude = len(whole) - 1 + exp10
    else:
        magnitude = -(len(fraction) - len(fraction.lstrip("0")) + 1) + exp10
    if abs(magnitude) > MAX_DECIMAL_EXPONENT:
        raise _OutOfRange(magnitude)
    return Fraction(normalized) * Fraction(10) ** exp10


def _number_of(frac: Fraction) -> tuple[Number, Fraction | None]:
    """(value, exact): an exact int, or the nearest real plus what it rounded."""
    if frac.denominator == 1:
        return int(frac), None
    return fraction_to_mpf(frac), frac


class Lexer:
    def __init__(self, text: str, syntax: NumSyntax = numsyntax.DEFAULT) -> None:
        self.text = text
        self.pos = 0
        self.syntax = syntax
        self.operators = (*OPERATORS_BASE, syntax.arg_sep)
        self._prev: Token | None = None  # the token before the one being read

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
        tok = self._scan()
        self._prev = tok
        return tok

    def _glued_value(self, start: int) -> Token | None:
        """The operand the character at `start` is glued to, if there is one."""
        prev = self._prev
        if prev is None or prev.span.end != start:
            return None
        is_value = prev.kind in ("NUMBER", "IDENT") or (
            prev.kind == "OP" and prev.text in (")", "]")
        )
        return prev if is_value else None

    def _scan(self) -> Token:
        while self._peek().isspace():
            self.pos += 1
        start = self.pos
        ch = self._peek()
        if ch == "":
            return Token("EOF", "", Span(start, start))
        if ch == "," and self.syntax.arg_sep != ",":
            # Comma mode. A comma the number before it did not absorb is only a
            # decimal point when it *starts* a number; glued to a value, or with
            # no digit after it, it is the period-mode argument separator.
            glued = self._glued_value(start)
            if glued is not None or not self._peek(1).isdigit():
                after = f" after {glued.text!r}" if glued is not None else ""
                raise LexError(
                    f"unexpected ','{after} — use {self.syntax.arg_sep!r} between arguments",
                    Span(start, start + 1),
                )
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

    def _mantissa(self) -> str:
        """Digits and ``_``; a decimal char only when a digit follows it."""
        begin = self.pos
        decimals = self.syntax.decimal_inputs
        while True:
            ch = self._peek()
            if ch.isdigit() or ch == "_":
                self.pos += 1
            elif ch and ch in decimals and self._peek(1).isdigit():
                self.pos += 2
            else:
                return self.text[begin : self.pos]

    def _number(self, start: int) -> Token:
        if self._peek() == "0" and self._peek(1) in ("x", "X", "b", "B", "o", "O"):
            return self._based_number(start)
        decimals = self.syntax.decimal_inputs
        mantissa = self._mantissa()
        # HDL sized literal: width'hFF, or width'shFF for a signed pattern.
        if self._peek() == "'":
            signed = self._peek(1).lower() == "s"
            base_at = 2 if signed else 1
            base_ch = self._peek(base_at).lower()
            if base_ch in _HDL_BASES:
                return self._hdl_number(start, mantissa, signed)
            if base_ch == "":  # `8'` or `8's` so far: the base letter is coming
                self.pos += base_at
                raise IncompleteError(
                    f"incomplete sized literal {self.text[start:self.pos]!r}",
                    Span(start, self.pos),
                )
        # Exponent: e/E only when followed by digits or sign+digits.
        has_exponent = False
        if self._peek() in ("e", "E"):
            after = self._peek(1)
            if after.isdigit() or (after in ("+", "-") and self._peek(2).isdigit()):
                has_exponent = True
                self.pos += 1  # e
                if self._peek() in ("+", "-"):
                    self.pos += 1
                self._take_while(str.isdigit)
        trailing = self._peek()
        if trailing and trailing in decimals:
            # A decimal char the mantissa did not absorb: no digit follows it.
            # Only a first point at the very end of the line can still become a
            # number (`1.` → `1.5`); `1e5.5`, `1.5.`, `1. 2` never can.
            self.pos += 1
            span = Span(start, self.pos)
            if self._peek() == "" and not has_exponent and not any(c in decimals for c in mantissa):
                raise IncompleteError(f"incomplete number {self.text[start:self.pos]!r}", span)
            self._take_while(lambda c: c.isdigit() or c in decimals)
            hint = f" — use {self.syntax.arg_sep!r} between arguments" if trailing == "," else ""
            raise LexError(
                f"malformed number {self.text[start:self.pos]!r}: "
                f"a digit must follow {trailing!r}{hint}",
                Span(start, self.pos),
            )
        literal_text = self.text[start : self.pos]
        try:
            marker = "e" if "e" in literal_text else "E"
            if marker in literal_text:
                mant, _, exp = literal_text.partition(marker)
                if len(exp) > 12:  # int() of a huge exponent is itself the hazard
                    raise _OutOfRange(exp)
                frac = _decimal_fraction(mant, int(exp), decimals)
            else:
                frac = _decimal_fraction(literal_text, 0, decimals)
        except _OutOfRange as exc:
            raise LexError(
                f"number is out of range: {_brief(literal_text)}", Span(start, self.pos)
            ) from exc
        except (ValueError, ZeroDivisionError) as exc:
            raise LexError(f"malformed number {literal_text!r}", Span(start, self.pos)) from exc
        # SI / binary suffix: the entire adjacent letter-run must be one suffix.
        run_start = self.pos
        run = self._take_while(_is_ident_cont)
        if run:
            if run in BINARY_SUFFIXES:
                frac *= BINARY_SUFFIXES[run]
            elif run in SI_SUFFIXES:
                frac *= Fraction(10) ** SI_SUFFIXES[run]
            else:
                self.pos = run_start  # not a suffix: separate IDENT token
        value, exact = _number_of(frac)
        return Token(
            "NUMBER", self.text[start : self.pos], Span(start, self.pos), value, exact=exact
        )

    def _based_number(self, start: int) -> Token:
        base_ch = self._peek(1).lower()
        base = {"x": 16, "b": 2, "o": 8}[base_ch]
        self.pos += 2
        digits = self._take_while(lambda c: c.isalnum() or c == "_")
        text = self.text[start : self.pos]
        span = Span(start, self.pos)
        if not digits and self._peek() == "":
            # `0x` with the digits still to come — the phone even has a key for it.
            raise IncompleteError(f"incomplete base-{base} literal {text!r}", span)
        try:
            value = int(digits, base)
        except ValueError as exc:
            raise LexError(f"malformed base-{base} literal {text!r}", span) from exc
        return Token("NUMBER", text, span, value)

    def _hdl_number(self, start: int, width_text: str, signed: bool = False) -> Token:
        try:
            width = int(width_text)
        except ValueError as exc:
            bad_span = Span(start, self.pos)
            raise LexError(f"malformed literal width {width_text!r}", bad_span) from exc
        offset = 2 if signed else 1  # past the quote (and the `s`) to the base letter
        base = _HDL_BASES[self._peek(offset).lower()]
        self.pos += offset + 1
        digits = self._take_while(lambda c: c.isalnum() or c == "_")
        text = self.text[start : self.pos]
        span = Span(start, self.pos)
        if width <= 0:
            raise LexError("literal width must be positive", span)
        if not digits and self._peek() == "":
            raise IncompleteError(f"incomplete sized literal {text!r}", span)
        try:
            value = int(digits, base)
        except ValueError as exc:
            raise LexError(f"malformed sized literal {text!r}", span) from exc
        if value.bit_length() > width:
            raise LexError(f"value does not fit in {width} bits", span)
        if signed and value >> (width - 1):
            value -= 1 << width  # the MSB is the sign: 8'sh80 is -128
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
            # The scan above ran to the end of the line, so the closing quote
            # is simply not typed yet.
            raise IncompleteError('unterminated x"..." literal', Span(start, self.pos))
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


def _brief(text: str) -> str:
    """A literal for an error message, shortened if it is absurdly long."""
    return repr(text) if len(text) <= 24 else repr(text[:10] + "…" + text[-8:])


def tokenize(text: str, syntax: NumSyntax = numsyntax.DEFAULT) -> list[Token]:
    return Lexer(text, syntax).tokens()


def tokenize_prefix(text: str, syntax: NumSyntax = numsyntax.DEFAULT) -> list[Token]:
    """Tokens of the longest valid prefix; never raises (for highlighting)."""
    lexer = Lexer(text, syntax)
    out: list[Token] = []
    while True:
        try:
            tok = lexer._next()
        except CalcError:  # LexError, or IncompleteError for a trailing `1.`
            return out
        if tok.kind == "EOF":
            return out
        out.append(tok)
