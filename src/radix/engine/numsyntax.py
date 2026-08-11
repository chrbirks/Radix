"""How numbers are written: decimal separator and argument separator.

One immutable descriptor threaded through lexer → parser → formatter → preview
so a single setting flips the whole grammar and every rendering consistently.

Two modes only. In ``comma`` mode the decimal point is ``,`` and functions
separate arguments with ``;`` (mirroring European spreadsheets); ``.`` stays
accepted as a decimal on *input* (a ``.`` before a digit is never anything but
a number, and a ``.`` before an identifier is still field access), so both
separators type-in the same. In ``period`` mode it is the classic ``.``/``,``.

Engine primitives default to :data:`PERIOD`; only the ``Session``/app default is
comma, which keeps the direct-engine golden tables byte-identical.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NumSyntax:
    decimal: str  # output decimal point: "." or ","
    arg_sep: str  # function-argument separator token: "," or ";"
    decimal_inputs: str  # chars accepted as a decimal point on INPUT


PERIOD = NumSyntax(decimal=".", arg_sep=",", decimal_inputs=".")
COMMA = NumSyntax(decimal=",", arg_sep=";", decimal_inputs=".,")

DEFAULT = PERIOD  # engine-primitive default → golden tables stay valid
BY_MODE: dict[str, NumSyntax] = {"period": PERIOD, "comma": COMMA}
