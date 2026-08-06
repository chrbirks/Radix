"""Help text, generated from the same tables the evaluator dispatches through.

Two renderings of the same content: plain text for the CLI (`-e help`) and a
rich-text variant for the GUI pane, where a real table keeps the signature and
summary columns aligned at any window width.
"""

from __future__ import annotations

from html import escape

from radix import __version__
from radix.engine.functions import CONSTANTS, FUNCTIONS

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


def general_help(shortcuts: str | None = None) -> str:
    lines = [_BASICS]
    lines.append("Operators (lowest to highest precedence)")
    for op, summary, example in _OPERATOR_HELP:
        lines.append(f"  {op:4} {summary}  e.g. {example}")
    lines.append("")
    lines.append("Functions")
    width = max(len(spec.signature) for spec in FUNCTIONS.values()) + 3
    for category in dict.fromkeys(spec.category for spec in FUNCTIONS.values()):
        lines.append(f"{category}")
        for spec in FUNCTIONS.values():
            if spec.category == category:
                lines.append(f"  {spec.signature:{width}}{spec.summary}")
        lines.append("")
    lines.append("Constants: " + ", ".join(sorted(CONSTANTS)))
    lines.append('Use help <name> for details, e.g. "help sin" or "help <<".')
    if shortcuts:
        lines.append("")
        lines.append(shortcuts)
    return "\n".join(lines)


def general_help_html(shortcuts: str | None = None) -> str:
    """Rich-text variant of general_help() for the GUI pane (same sources)."""

    def table(rows: list[tuple[str, str]]) -> str:
        cells = "".join(
            f'<tr><td style="white-space:pre">{escape(left)}&nbsp;&nbsp;&nbsp;</td>'
            f"<td>{escape(right)}</td></tr>"
            for left, right in rows
        )
        return f'<table cellspacing="0" cellpadding="1">{cells}</table>'

    parts = [f"<pre>{escape(_BASICS)}</pre>"]
    parts.append("<h3>Operators (lowest to highest precedence)</h3>")
    parts.append(table([(op, f"{summary}  e.g. {ex}") for op, summary, ex in _OPERATOR_HELP]))
    parts.append("<h3>Functions</h3>")
    for category in dict.fromkeys(spec.category for spec in FUNCTIONS.values()):
        parts.append(f"<p><b>{escape(category)}</b></p>")
        parts.append(
            table(
                [
                    (spec.signature, spec.summary)
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


def topic_help(topic: str) -> str | None:
    """Help for one function or operator; None if the topic is unknown."""
    if topic in _COMMAND_HELP:
        return _COMMAND_HELP[topic]
    spec = FUNCTIONS.get(topic)
    if spec is not None:
        lo, hi = spec.arity
        arity = str(lo) if lo == hi else f"{lo}–{hi}"
        return (
            f"{spec.signature} — {spec.summary}  ({arity} argument(s))\nExample: {spec.example}"
        )
    if topic in CONSTANTS:
        return f"{topic} — {CONSTANTS[topic][1]}"
    for op, summary, example in _OPERATOR_HELP:
        if topic == op:
            return f"{op} — {summary}\nExample: {example}"
    return None
