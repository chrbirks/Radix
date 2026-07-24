"""Entry point: `radix` launches the GUI, `radix -e EXPR` evaluates once.

The -e form is also the frozen-binary smoke test in CI, so it must not require
a display.
"""

from __future__ import annotations

import argparse
import sys

from radix import __version__
from radix.engine.errors import CalcError
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
    if views is not None:
        line = f"{primary}  ({views.hex} | {views.dec_signed} | {views.binary})"
        if views.truncated:
            # Same masking the GUI's READOUT does, so it needs the same
            # caveat: without it `2**200` prints a parenthesised 0x0000_0000
            # that reads like part of the answer.
            line += f"  [low {session.word_size} bits of a {views.value_bits}-bit value]"
    else:
        line = primary
    if outcome.value.note:
        line += f"  [{outcome.value.note}]"
    print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="radix", description="Radix calculator")
    parser.add_argument("-e", "--evaluate", metavar="EXPR", help="evaluate once and exit")
    parser.add_argument(
        "--version", action="version", version=f"Radix {__version__}"
    )
    args = parser.parse_args(argv)
    session = Session()
    if args.evaluate is not None:
        return run_expression(session, args.evaluate)
    from radix.ui_qt.app import run_gui

    return run_gui(session)


if __name__ == "__main__":
    sys.exit(main())
