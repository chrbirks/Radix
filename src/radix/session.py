"""Session façade: the only API the UI (and CLI) talk to.

Owns all mutable state — variables, ``ans``, word size, signedness, angle unit,
notation — and exposes ``evaluate(text, commit=...)``. With ``commit=False``
evaluation is completely side-effect free, which is what the live preview uses:
``ans``, variables, and history only change when the user presses Enter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from radix.engine import evaluator, render
from radix.engine import fpga as _fpga  # noqa: F401 — registers the FPGA toolkit
from radix.engine import help as help_mod
from radix.engine.csr import (
    Csr,
    csr_from_json,
    csr_from_nodes,
    csr_to_json,
    flatten_spec,
)
from radix.engine.errors import CalcError, EvalError, Span, shift
from radix.engine.formatter import (
    FloatViews,
    IntegerViews,
    float_views,
    format_int_base,
    format_number,
    integer_views,
)
from radix.engine.functions import CONSTANTS, FUNCTIONS, EvalContext
from radix.engine.lexer import tokenize
from radix.engine.nodes import Assign
from radix.engine.numsyntax import BY_MODE, NumSyntax
from radix.engine.parser import parse
from radix.engine.values import (
    Value,
    magnitude_fits,
    value_from_json,
    value_to_json,
)

WORD_SIZES = (8, 16, 32, 64)
NOTATIONS = ("auto", "sci", "eng", "eng_si")
INT_BASES = ("dec", "hex", "bin")
DECIMAL_MODES = ("comma", "period")

RESERVED_NAMES = (
    frozenset({"ans", "help", "clear", "vars", "del", "csr"})
    | frozenset(CONSTANTS)
    | frozenset(FUNCTIONS)
)


@dataclass(frozen=True)
class Outcome:
    """Result of evaluating one input line."""

    kind: str  # "value" | "assign" | "help" | "clear" | "vars" | "del" | "csr" | "empty"
    value: Value | None = None
    target: str | None = None  # assignment target
    normalized: str = ""  # resolved pretty-print of the parse, for the preview
    help_text: str | None = None

    @property
    def primary_text(self) -> str:
        if self.value is None:
            return ""
        return format_number(self.value)


@dataclass
class Session:
    word_size: int = 32
    signed: bool = False
    angle_deg: bool = False
    notation: str = "auto"
    int_base: str = "dec"  # display base for integer results (dec/hex/bin)
    # "period" (./,) or "comma" (,/;). The dataclass default is period so the
    # engine golden tables read canonically; the app opts into comma (its
    # shipped default) at the entry point — see radix.__main__.main.
    decimal_mode: str = "period"
    show_float_view: bool = False  # IEEE-754 breakdown in READOUT/REGISTER
    variables: dict[str, Value] = field(default_factory=dict)
    csrs: dict[str, Csr] = field(default_factory=dict)
    ans: Value | None = None

    # -- settings ------------------------------------------------------------

    @property
    def context(self) -> EvalContext:
        return EvalContext(self.word_size, self.signed, self.angle_deg, self.decimal_char)

    @property
    def decimal_syntax(self) -> NumSyntax:
        return BY_MODE[self.decimal_mode]

    @property
    def decimal_char(self) -> str:
        return self.decimal_syntax.decimal

    def cycle_word_size(self) -> int:
        i = WORD_SIZES.index(self.word_size)
        self.word_size = WORD_SIZES[(i + 1) % len(WORD_SIZES)]
        return self.word_size

    def cycle_notation(self) -> str:
        i = NOTATIONS.index(self.notation)
        self.notation = NOTATIONS[(i + 1) % len(NOTATIONS)]
        return self.notation

    def cycle_int_base(self) -> str:
        i = INT_BASES.index(self.int_base)
        self.int_base = INT_BASES[(i + 1) % len(INT_BASES)]
        return self.int_base

    def cycle_decimal_mode(self) -> str:
        i = DECIMAL_MODES.index(self.decimal_mode)
        self.decimal_mode = DECIMAL_MODES[(i + 1) % len(DECIMAL_MODES)]
        return self.decimal_mode

    # -- evaluation ------------------------------------------------------------

    def evaluate(self, text: str, commit: bool = True) -> Outcome:
        """Evaluate one input line. Raises CalcError subclasses on bad input."""
        line = text.strip()
        if not line:
            return Outcome("empty")
        command = self._command(line, commit)
        if command is not None:
            return command
        node = parse(line, self.decimal_syntax)
        preview = render.render(node, self.variables, self.ans, self.decimal_syntax)
        if isinstance(node, Assign):
            if node.target in RESERVED_NAMES:
                raise EvalError(
                    f"{node.target!r} is reserved and cannot be assigned", node.target_span
                )
            if node.target in self.csrs:
                raise EvalError(
                    f"{node.target!r} is already a csr — del it first", node.target_span
                )
            value = evaluator.evaluate(
                node.expr, self.context, self.variables, self.ans, csrs=self.csrs
            )
            value = evaluator.guard_displayable(value, node.expr.span)
            if commit:
                self.variables[node.target] = value
                self.ans = value
            return Outcome("assign", value, node.target, normalized=preview)
        value = evaluator.evaluate(
            node, self.context, self.variables, self.ans, csrs=self.csrs
        )
        value = evaluator.guard_displayable(value, node.span)
        if commit:
            self.ans = value
        return Outcome("value", value, normalized=preview)

    def _command(self, line: str, commit: bool) -> Outcome | None:
        # Split on any whitespace run, so `del<TAB>x` is the command it looks
        # like rather than a bare identifier the parser then rejects. `line` is
        # stripped and non-empty by the time we get here, so parts[0] exists.
        parts = line.split(None, 1)
        word = parts[0]
        rest = parts[1].strip() if len(parts) > 1 else ""
        if word == "help":
            if rest.startswith("="):
                return None  # `help = ...` is an assignment attempt → reserved-name error
            arg_sep = self.decimal_syntax.arg_sep + " "
            if rest:
                text = help_mod.topic_help(rest, arg_sep)
                if text is None:
                    text = f"no help for {rest!r} — try plain `help` for the overview"
            else:
                text = help_mod.general_help(arg_sep=arg_sep)
            # target carries the topic so the GUI can tell overview from topic.
            return Outcome("help", target=rest or None, help_text=text)
        if word == "clear" and not rest:
            # `clear` wipes history only; named variables and csrs are kept.
            # `ans` is the transient last-result, so it clears with the display.
            if commit:
                self.ans = None
            return Outcome("clear")
        if word == "vars" and not rest:
            lines = [f"{k} = {self.format_value(v)}" for k, v in self.variables.items()]
            lines += [f"{name} = csr {c.spec_text()}" for name, c in self.csrs.items()]
            return Outcome("vars", help_text="\n".join(lines) or "no variables defined")
        if word == "del":
            if rest.startswith("="):
                return None  # `del = ...` is an assignment attempt → reserved-name error
            if not rest:
                raise EvalError("del: which variable? e.g. del x", Span(0, len(line)))
            if rest in self.variables:
                if commit:
                    del self.variables[rest]
                return Outcome("del", target=rest)
            if rest in self.csrs:
                if commit:
                    del self.csrs[rest]
                return Outcome("del", target=rest)
            raise EvalError(
                f"no variable or csr named {rest!r}", Span(len(word) + 1, len(line))
            )
        if word == "csr":
            if rest.startswith("="):
                return None  # `csr = ...` is an assignment attempt → reserved-name error
            if not rest:
                lines = [
                    f"{name} = csr {c.spec_text()}" for name, c in self.csrs.items()
                ]
                return Outcome("csr", help_text="\n".join(lines) or "no csrs defined")
            return self._csr_command(line, word, rest, commit)
        return None

    def _csr_command(self, line: str, word: str, rest: str, commit: bool) -> Outcome:
        usage_error = EvalError(
            "csr: expected 'NAME = FIELD[msb:lsb] ...', e.g. csr CTRL = EN[31]",
            Span(len(word) + 1, len(line)),
        )
        if "=" not in rest:
            raise usage_error
        name_raw, _, spec_raw = rest.partition("=")
        name = name_raw.strip()
        if not name:
            raise usage_error
        name_start = line.index(name_raw, len(word) + 1)
        name_span = Span(name_start, name_start + len(name))
        toks = tokenize(name)
        if not (len(toks) == 2 and toks[0].kind == "IDENT" and toks[1].kind == "EOF"):
            raise EvalError(f"{name!r} is not a valid csr name", name_span)
        if name in RESERVED_NAMES:
            raise EvalError(f"{name!r} is reserved and cannot be assigned", name_span)
        if name in self.variables:
            raise EvalError(f"{name!r} is already a variable — del it first", name_span)
        spec_text = spec_raw.strip()
        if not spec_text:
            raise EvalError(
                "csr: expected at least one field, e.g. csr CTRL = EN[31]",
                Span(len(line), len(line)),
            )
        eq_index = name_start + len(name_raw)
        spec_offset = eq_index + 1
        while spec_offset < len(line) and line[spec_offset].isspace():
            spec_offset += 1
        try:
            node = parse(spec_text, self.decimal_syntax)
            leaves = flatten_spec(node)
            new_csr = csr_from_nodes(leaves, name=name)
        except CalcError as exc:
            raise type(exc)(exc.message, shift(exc.span, spec_offset)) from exc
        if commit:
            self.csrs[name] = new_csr
        return Outcome(
            "csr", target=name, help_text=f"csr {name} = {new_csr.spec_text()}"
        )

    # -- display helpers -------------------------------------------------------

    def format_value(self, value: Value, base: str | None = None) -> str:
        """Primary display text; integer results honor the display base."""
        base = self.int_base if base is None else base
        if base != "dec" and isinstance(value.number, int):
            return format_int_base(value.number, base, self.word_size)
        return format_number(value, self.notation, self.decimal_char)

    def views_for(self, value: Value) -> IntegerViews | None:
        """Hex/dec/bin renderings if the value is an integer, else None."""
        if not isinstance(value.number, int):
            return None
        return integer_views(value.number, self.word_size)

    def float_views_for(self, value: Value) -> FloatViews | None:
        """IEEE-754 decomposition if the value is a real and the word size
        maps to a float format (32/64), else None."""
        if isinstance(value.number, int):
            return None
        return float_views(value.number, self.word_size, self.decimal_char)

    def preview(self, text: str) -> Outcome:
        """Side-effect-free evaluation for the live preview line.

        Raises CalcError like evaluate(); IncompleteError means "still typing".
        """
        return self.evaluate(text, commit=False)

    # -- persistence -------------------------------------------------------

    def state_to_json(self) -> dict[str, Any]:
        """Variables, csrs, and ``ans`` — the state that persists across restarts."""
        return {
            "variables": {name: value_to_json(v) for name, v in self.variables.items()},
            "csrs": {name: csr_to_json(c) for name, c in self.csrs.items()},
            "ans": value_to_json(self.ans) if self.ans is not None else None,
        }

    def load_state_json(self, data: dict[str, Any]) -> None:
        """Inverse of ``state_to_json``. Skips individual malformed entries
        rather than discarding the whole stored state.

        Every container is type-checked before iteration: this parses a file a
        user can edit (or that a half-finished write can truncate), so a wrong
        shape must degrade to defaults, never raise into the caller's startup.
        """

        def section(key: str) -> dict[str, Any]:
            raw = data.get(key)
            return raw if isinstance(raw, dict) else {}

        def restore(entry: Any) -> Value | None:
            """A stored value, or None if it is malformed or out of range.

            The range check matters because the file is editable: live results
            pass guard_displayable before they are ever committed, but a value
            typed straight into the config never met that guard.
            """
            try:
                value = value_from_json(entry)
            except (KeyError, TypeError, ValueError):
                return None
            return value if magnitude_fits(value.number) else None

        variables: dict[str, Value] = {}
        for name, entry in section("variables").items():
            if name in RESERVED_NAMES:
                continue
            value = restore(entry)
            if value is not None:
                variables[name] = value
        csrs: dict[str, Csr] = {}
        for name, entry in section("csrs").items():
            if name in RESERVED_NAMES or name in variables:
                continue
            try:
                csrs[name] = csr_from_json(entry)
            except (KeyError, TypeError, ValueError):
                continue
        self.variables = variables
        self.csrs = csrs
        ans_data = data.get("ans")
        self.ans = restore(ans_data) if ans_data is not None else None

__all__ = [
    "Session",
    "Outcome",
    "CalcError",
    "WORD_SIZES",
    "NOTATIONS",
    "INT_BASES",
    "DECIMAL_MODES",
]
