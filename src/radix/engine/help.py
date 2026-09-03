"""Help text, generated from the same tables the evaluator dispatches through.

Two renderings of the same content: plain text for the CLI (`-e help`) and a
rich-text variant for the GUI pane, where a real table keeps the signature and
summary columns aligned at any window width.

Examples are written once, in period syntax, and localized on the way out so
that what ``help`` shows in comma mode (``fix(0,7071; 1; 15)``) is exactly what
that mode accepts when typed back in.
"""

from __future__ import annotations

import re
from html import escape

from radix import __version__
from radix.engine import numsyntax
from radix.engine.functions import CONSTANTS, FUNCTIONS
from radix.engine.numsyntax import NumSyntax

_OPERATOR_HELP: list[tuple[str, str, str]] = [
    # (operator, summary, example) — lowest to highest precedence
    ("|", "Bitwise OR (integers; masked to the word size).", "0xF0 | 0x0F"),
    ("^", "Bitwise XOR — NOT power! Use ** for power.", "2^10 = 8"),
    ("&", "Bitwise AND (integers; masked to the word size).", "0xFF & 0x0F"),
    ("<<", "Shift left (masked to the word size).", "1 << 8"),
    (">>", "Shift right: logical when unsigned, arithmetic when signed.", "0x80 >> 4"),
    ("+", "Addition.", "1 + 2"),
    ("-", "Subtraction (also unary minus).", "5 - 3"),
    ("*", "Multiplication. Adjacency works too: 2pi, 3(x+1).", "6 * 7"),
    ("/", "True division (exact int when it divides evenly).", "10 / 4"),
    ("//", "Integer division, truncating toward zero.", "-7 // 2 = -3"),
    ("%", "Remainder with the sign of the dividend (C-like).", "-7 % 2 = -1"),
    ("~", "Bitwise NOT within the word size.", "~0 = 0xFF…"),
    ("**", "Power, right-associative.", "2**10 = 1024"),
    ("[]", "Bit slice/test: x[7:4] extracts bits, x[3] tests one.", "0xAB[7:4] = 0xA"),
]

_COMMAND_HELP: dict[str, str] = {
    "csr": (
        "csr NAME = FIELD[msb:lsb] ... — define a CSR field layout\n"
        "  csr CTRL = EN[31] IRQ[30:28] ADDR[27:8] CMD[7:0]      define\n"
        "  csr                                                   list all csrs\n"
        "  del CTRL                                              delete a csr\n"
        "  CTRL(0x8C01A0F3)                                      decode a value\n"
        "  ans.ADDR                                              read a field as an int\n"
        "  csr(x, EN[7] CMD[3:0])                                one-shot decode, no name"
    ),
}

_BASICS = f"""\
Radix v{__version__}

Type an expression and press Enter. Everything is keyboard-first — no buttons.

Literals   123   1.5   1.5e-9   0xFF   0b1010   0o17   0xFFFF_0000
           Prefixed: hFF = xFF = 0xFF   b1010 = 0b1010
           SI suffixes: 4.7k = 4700, 100n = 1e-7   (f p n u µ m k M G T)
           Binary prefixes: 32Ki = 32768   (Ki Mi Gi)
           HDL: 8'hFF   12'b1010_1010   4'd9   x"FF"
           Note: literals win over names — 4k is always 4000 (write 4*k for
           a variable k) and b1/x0/hA cannot be variable names.
Variables  x = 4.7k    then    x * 2      `ans` is the previous result.
Integers   Results that are integers also show hex/dec/bin and the bit panel.
           Word size and signedness affect bit operators and that display only.
Commands   help        this overview            help <name>   one operator/function
           clear       clear history (variables & csrs kept)
           csr NAME = FIELD[msb:lsb] ...      define a CSR field layout
"""


# A decimal literal in period syntax: digits, point, digits, not glued to a
# preceding word char (so `0x1A.` prose or `Q4.12` style tags are left alone).
_DECIMAL_LITERAL = re.compile(r"(?<![\w.])(\d+)\.(\d+)")


def _syntax_for(arg_sep: str, syntax: NumSyntax | None) -> NumSyntax:
    """The syntax to write help in.

    Callers that only know the argument separator (``", "`` / ``"; "``) get
    the mode it implies; the two are 1:1.
    """
    if syntax is not None:
        return syntax
    if arg_sep.strip() == numsyntax.COMMA.arg_sep:
        return numsyntax.COMMA
    return numsyntax.PERIOD


def localize(text: str, syntax: NumSyntax) -> str:
    """Rewrite period-syntax examples into ``syntax``.

    Only the decimal point inside numeric literals and the ``, `` between
    call arguments change; hex digits, field names and prose are untouched:
    ``fix(0.7071, 1, 15) = 0x5A82`` → ``fix(0,7071; 1; 15) = 0x5A82``.
    """
    if syntax == numsyntax.PERIOD:
        return text
    text = _DECIMAL_LITERAL.sub(lambda m: f"{m[1]}{syntax.decimal}{m[2]}", text)
    out: list[str] = []
    depth = 0  # only a `, ` inside parentheses separates arguments
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        elif ch == "," and depth and text.startswith(" ", i + 1):
            ch = syntax.arg_sep
        out.append(ch)
    return "".join(out)


def general_help(
    shortcuts: str | None = None, arg_sep: str = ", ", syntax: NumSyntax | None = None
) -> str:
    syntax = _syntax_for(arg_sep, syntax)
    arg_sep = syntax.arg_sep + " "
    lines = [localize(_BASICS, syntax)]
    lines.append("Operators (lowest to highest precedence)")
    for op, summary, example in _OPERATOR_HELP:
        lines.append(f"  {op:4} {summary}  e.g. {localize(example, syntax)}")
    lines.append("")
    lines.append("Functions")
    width = max(len(spec.signature_sep(arg_sep)) for spec in FUNCTIONS.values()) + 3
    for category in dict.fromkeys(spec.category for spec in FUNCTIONS.values()):
        lines.append(f"{category}")
        for spec in FUNCTIONS.values():
            if spec.category == category:
                lines.append(f"  {spec.signature_sep(arg_sep):{width}}{spec.summary}")
        lines.append("")
    lines.append("Constants: " + ", ".join(sorted(CONSTANTS)))
    lines.append('Use help <name> for details, e.g. "help sin" or "help <<".')
    if shortcuts:
        lines.append("")
        lines.append(shortcuts)
    return "\n".join(lines)


def general_help_html(
    shortcuts: str | None = None, arg_sep: str = ", ", syntax: NumSyntax | None = None
) -> str:
    """Rich-text variant of general_help() for the GUI pane (same sources)."""
    syntax = _syntax_for(arg_sep, syntax)
    arg_sep = syntax.arg_sep + " "

    def table(rows: list[tuple[str, str]]) -> str:
        cells = "".join(
            f'<tr><td style="white-space:pre">{escape(left)}&nbsp;&nbsp;&nbsp;</td>'
            f"<td>{escape(right)}</td></tr>"
            for left, right in rows
        )
        return f'<table cellspacing="0" cellpadding="1">{cells}</table>'

    parts = [f"<pre>{escape(localize(_BASICS, syntax))}</pre>"]
    parts.append("<h3>Operators (lowest to highest precedence)</h3>")
    parts.append(
        table(
            [
                (op, f"{summary}  e.g. {localize(ex, syntax)}")
                for op, summary, ex in _OPERATOR_HELP
            ]
        )
    )
    parts.append("<h3>Functions</h3>")
    for category in dict.fromkeys(spec.category for spec in FUNCTIONS.values()):
        parts.append(f"<p><b>{escape(category)}</b></p>")
        parts.append(
            table(
                [
                    (spec.signature_sep(arg_sep), spec.summary)
                    for spec in FUNCTIONS.values()
                    if spec.category == category
                ]
            )
        )
    parts.append("<p>Constants: " + ", ".join(sorted(CONSTANTS)) + "</p>")
    parts.append('<p>Use help &lt;name&gt; for details, e.g. "help sin" or "help &lt;&lt;".</p>')
    if shortcuts:
        parts.append(f"<pre>{escape(shortcuts)}</pre>")
    return "\n".join(parts)


def topic_help(
    topic: str, arg_sep: str = ", ", syntax: NumSyntax | None = None
) -> str | None:
    """Help for one function or operator; None if the topic is unknown."""
    syntax = _syntax_for(arg_sep, syntax)
    arg_sep = syntax.arg_sep + " "
    if topic in _COMMAND_HELP:
        return localize(_COMMAND_HELP[topic], syntax)
    spec = FUNCTIONS.get(topic)
    if spec is not None:
        lo, hi = spec.arity
        arity = str(lo) if lo == hi else f"{lo}–{hi}"
        return (
            f"{spec.signature_sep(arg_sep)} — {spec.summary}  ({arity} argument(s))"
            f"\nExample: {localize(spec.example, syntax)}"
        )
    if topic in CONSTANTS:
        return f"{topic} — {CONSTANTS[topic][1]}"
    for op, summary, example in _OPERATOR_HELP:
        if topic == op:
            return f"{op} — {summary}\nExample: {localize(example, syntax)}"
    return None
