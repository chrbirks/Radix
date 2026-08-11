"""Syntax coloring for expressions, driven by the real engine lexer.

classify() runs the same tokenizer the parser uses, so the colors can never
disagree with how the input is actually interpreted (e.g. `4k` colors as one
number, `4*k` as number-operator-identifier). On a lex error the valid prefix
is still colored and the rest is left plain.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat, QTextDocument

from radix.engine import numsyntax
from radix.engine.functions import CONSTANTS, FUNCTIONS
from radix.engine.lexer import tokenize_prefix
from radix.engine.numsyntax import NumSyntax
from radix.ui_qt.theme import Palette

PARENS = {"(", ")", "[", "]"}

Segment = tuple[int, int, str]  # start, length, kind


def classify(text: str, syntax: NumSyntax = numsyntax.DEFAULT) -> list[Segment]:
    """Token segments as (start, length, kind); gaps are left uncolored.

    Kinds: "number", "function", "constant", "operator", "paren", "ident".
    On a lex error the valid prefix is still classified; the rest stays plain.
    """
    segments: list[Segment] = []
    for token in tokenize_prefix(text, syntax):
        if token.kind == "NUMBER":
            kind = "number"
        elif token.kind == "IDENT":
            if token.text in FUNCTIONS:
                kind = "function"
            elif token.text in CONSTANTS or token.text == "ans":
                kind = "constant"
            else:
                kind = "ident"
        elif token.text in PARENS:
            kind = "paren"
        else:
            kind = "operator"
        segments.append((token.span.start, token.span.end - token.span.start, kind))
    return segments


def color_for(kind: str, palette: Palette) -> QColor:
    return QColor(
        {
            "number": palette.syn_number,
            "function": palette.syn_function,
            "constant": palette.syn_function,
            "operator": palette.syn_operator,
            "paren": palette.muted,
            "ident": palette.text,
            "csr": palette.syn_function,
        }[kind]
    )


class ExprHighlighter(QSyntaxHighlighter):
    def __init__(
        self,
        document: QTextDocument,
        palette: Palette,
        syntax: NumSyntax = numsyntax.DEFAULT,
    ) -> None:
        super().__init__(document)
        self.palette_tokens = palette
        self.syntax = syntax
        self.error_span: tuple[int, int] | None = None

    def set_palette(self, palette: Palette) -> None:
        self.palette_tokens = palette
        self.rehighlight()

    def set_syntax(self, syntax: NumSyntax) -> None:
        """Re-tokenize under a new decimal/argument grammar; no-op if unchanged.

        The guard mirrors set_error_span: rehighlight() fires textChanged, so a
        blind rehighlight on every setting change would loop through the preview.
        """
        if syntax == self.syntax:
            return
        self.syntax = syntax
        self.rehighlight()

    def set_error_span(self, span: tuple[int, int] | None) -> None:
        """Underline [start, end) in the input; None clears.

        The no-change guard matters: rehighlight() fires textChanged, which
        re-schedules the preview, which sets the same span again.
        """
        if span == self.error_span:
            return
        self.error_span = span
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        for start, length, kind in classify(text, self.syntax):
            fmt = QTextCharFormat()
            fmt.setForeground(color_for(kind, self.palette_tokens))
            self.setFormat(start, length, fmt)
        if self.error_span is not None and text:
            start, end = self.error_span
            # Errors at end-of-input point past the last char; pull them back.
            start = min(max(start, 0), len(text) - 1)
            end = min(max(end, start + 1), len(text))
            for pos in range(start, end):
                fmt = self.format(pos)  # keep the token color underneath
                fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
                fmt.setUnderlineColor(QColor(self.palette_tokens.error))
                self.setFormat(pos, 1, fmt)
