"""Entry point: `radix` launches the GUI, `radix -e EXPR` evaluates once.

The -e form is also the frozen-binary smoke test in CI, so it must not require
a display.
"""

from __future__ import annotations

import argparse
import sys

from radix import __version__
from radix.engine.errors import CalcError
from radix.engine.formatter import integer_views
from radix.session import Session


def run_expression(session: Session, text: str) -> int:
    if text.strip() == "help":
        outcome = session.evaluate("help")
        print(outcome.help_text)
        return 0
    try:
        outcome = session.evaluate(text)
    except CalcError as exc:
        print(text, file=sys.stderr)
        print(exc.span.caret_line(), file=sys.stderr)
        print(f"error: {exc.message}", file=sys.stderr)
        return 1
    if outcome.kind in ("help", "vars", "csr"):
        print(outcome.help_text)
        return 0
    if outcome.value is None:
        return 0
    primary = session.format_value(outcome.value)
    views = session.views_for(outcome.value)
    bits = session.word_size
    declared = outcome.value.declared_width
    if views is not None and declared is not None and declared > bits:
        # A result that states its own width (a Q64.64 word, a 48-bit sized
        # literal) is shown at that width: the low word of it is not the value.
        bits = declared
        number = outcome.value.number
        assert isinstance(number, int)
        views = integer_views(number, bits)
    if views is not None:
        line = f"{primary}  ({views.hex} | {views.dec_signed} | {views.binary})"
        if views.truncated:
            # Same masking the GUI's READOUT does, so it needs the same
            # caveat: without it `2**200` prints a parenthesised 0x0000_0000
            # that reads like part of the answer.
            line += f"  [low {bits} bits of a {views.value_bits}-bit value]"
    else:
        line = primary
    if outcome.value.note:
        line += f"  [{outcome.value.note}]"
    print(line)
    return 0


def _join_expression(argv: list[str]) -> list[str]:
    """Glue ``-e EXPR`` into ``--evaluate=EXPR``.

    argparse reads a separate argument that starts with ``-`` as an option, so
    ``radix -e "-5+3"`` died with a usage error. Joined, it is unambiguous.
    """
    out: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] in ("-e", "--evaluate") and i + 1 < len(argv):
            out.append(f"--evaluate={argv[i + 1]}")
            i += 2
        else:
            out.append(argv[i])
            i += 1
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="radix", description="Radix calculator")
    parser.add_argument("-e", "--evaluate", metavar="EXPR", help="evaluate once and exit")
    parser.add_argument(
        "--version", action="version", version=f"Radix {__version__}"
    )
    args = parser.parse_args(_join_expression(sys.argv[1:] if argv is None else argv))
    # Comma is the shipped default (see Session.decimal_mode). The GUI's
    # load_session overrides this with the user's persisted choice if any.
    session = Session(decimal_mode="comma")
    if args.evaluate is not None:
        return run_expression(session, args.evaluate)
    from radix.ui_qt.app import run_gui

    return run_gui(session)


if __name__ == "__main__":
    sys.exit(main())
