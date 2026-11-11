"""Silkscreen-style section captions for front-panel zones, and the label
variants the zones use to keep long values inside the window.

`ZoneCaption` is a small paint-only label (uppercase text + a hairline rule
filling the rest of the width) reused above the inspector's
TRACE/READOUT/REGISTER zones. Separate module so both `inspector.py` and
`bit_panel.py` can import it without creating a cycle between them.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStyle, QStyleOption, QWidget

from radix.ui_qt.theme import FONT_MICRO, LABEL_FAMILY, Palette

ZONE_CAPTION_H = 20
_RULE_GAP = 8  # space between caption text and the start of the hairline rule


def margin_wrap(widget: QWidget, side_margin: int) -> QWidget:
    """Wrap `widget` so its content aligns with a `side_margin`px gutter, e.g. to
    match a ZoneCaption to the lane grid or viz card content it sits above."""
    container = QWidget()
    inner = QHBoxLayout(container)
    inner.setContentsMargins(side_margin, 0, side_margin, 0)
    inner.addWidget(widget)
    return container


class ZoneCaption(QWidget):
    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text
        self._muted = "#000000"
        self._hairline = "#000000"
        self.setFixedHeight(ZONE_CAPTION_H)

    def text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        if text == self._text:
            return
        self._text = text
        self.update()

    def set_palette(self, palette: Palette) -> None:
        self._muted = palette.muted
        self._hairline = palette.hairline
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(LABEL_FAMILY)
        font.setPixelSize(FONT_MICRO)
        metrics = QFontMetrics(font)
        text_w = metrics.horizontalAdvance(self._text)
        painter.setFont(font)
        painter.setPen(QColor(self._muted))
        painter.drawText(
            QRectF(0, 0, text_w, self.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._text,
        )
        rule_x = text_w + _RULE_GAP
        if rule_x < self.width():
            y = self.height() / 2
            painter.setPen(QPen(QColor(self._hairline), 1))
            painter.drawLine(QPointF(rule_x, y), QPointF(self.width(), y))
        painter.end()


class ElidedLabel(QLabel):
    """One line of text that gives way instead of pushing the layout wider.

    A plain QLabel's minimum width is its text, so a long value (a pinned
    64-bit word in BIN base is 80 characters) widened the whole inspector past
    the window — and with horizontal scrolling off, everything to the right of
    the window edge was simply cut. This one shrinks, paints an ellipsis, and
    keeps the full text in ``text()`` and the tooltip.
    """

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.setText(text)  # through the override, so the tooltip is set too

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), 4 * self.fontMetrics().averageCharWidth()), hint.height())

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, event: QPaintEvent) -> None:
        metrics = QFontMetrics(self.font())
        rect = self.contentsRect()
        if metrics.horizontalAdvance(self.text()) <= rect.width():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(
            rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width()),
        )
        painter.end()


class WrapAnywhereLabel(QLabel):
    """A value readout that breaks a long number across lines.

    QLabel wraps only at word boundaries and a number has none, so a 61-digit
    result ended flush at the window edge, mid-number, looking complete. Text
    that fits one line is painted by QLabel as usual (mouse selection and all);
    text that does not is laid out here, breaking anywhere, on up to
    ``MAX_LINES`` lines with an ellipsis after that.
    """

    MAX_LINES = 4

    def _flags(self) -> Qt.AlignmentFlag | Qt.TextFlag:
        return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWrapAnywhere

    def _chrome(self) -> tuple[int, int]:
        """(horizontal, vertical) space the stylesheet's padding takes."""
        margins = self.contentsMargins()
        return margins.left() + margins.right(), margins.top() + margins.bottom()

    def _lines_at(self, width: int) -> int:
        metrics = QFontMetrics(self.font())
        available = max(1, width - self._chrome()[0] - metrics.horizontalAdvance("x"))
        if metrics.horizontalAdvance(self.text()) <= available:
            return 1
        wrapped = metrics.boundingRect(0, 0, available, 10_000, int(self._flags()), self.text())
        return max(1, min(self.MAX_LINES, round(wrapped.height() / metrics.lineSpacing())))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        metrics = QFontMetrics(self.font())
        lines = self._lines_at(width)
        if lines == 1:
            return super().heightForWidth(width)
        return lines * metrics.lineSpacing() + self._chrome()[1]

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), 8 * self.fontMetrics().averageCharWidth()), hint.height())

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        width = self.width() if self.width() > 0 else hint.width()
        return QSize(hint.width(), max(hint.height(), self.heightForWidth(width)))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if event.oldSize().width() != event.size().width():
            self.updateGeometry()  # the line count depends on the width

    def setText(self, text: str) -> None:
        super().setText(text)
        self.updateGeometry()

    def paintEvent(self, event: QPaintEvent) -> None:
        if self._lines_at(self.width()) == 1:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        option = QStyleOption()
        option.initFrom(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, self)
        metrics = QFontMetrics(self.font())
        # QLabel indents framed text by half an "x"; match it, so a value does
        # not jump sideways the moment it grows a second line.
        indent = metrics.horizontalAdvance("x") // 2
        rect = self.contentsRect().adjusted(indent, 0, -indent, 0)
        text = self.text()
        # Past MAX_LINES, cut to what fits and say so.
        per_line = max(1, rect.width() // max(1, metrics.averageCharWidth()))
        if len(text) > per_line * self.MAX_LINES:
            text = text[: per_line * self.MAX_LINES - 1] + "…"
        painter.setFont(self.font())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(rect, int(self._flags()), text)
        painter.end()


class ShrinkToFitLabel(QLabel):
    """A wrapping readout lane that never forces the panel wider than it is.

    The lanes wrap at spaces, but a 128-bit word is one unbroken 39-digit (or
    41-character hex) run: at narrow window widths that run set the minimum
    width of the whole inspector. Here the label may be made narrower than its
    longest run, and when it is, the text is drawn in a smaller size that fits
    — the whole value stays readable — down to ``MIN_PX``, then elided.
    """

    MIN_PX = 11

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), 12 * self.fontMetrics().averageCharWidth()), hint.height())

    def _plain_runs(self) -> list[str] | None:
        text = self.text()
        if "<" in text:  # rich text (the BIN lane): its runs are four digits long
            return None
        return text.split()

    def paintEvent(self, event: QPaintEvent) -> None:
        runs = self._plain_runs()
        rect = self.contentsRect()
        metrics = QFontMetrics(self.font())
        widest = max((metrics.horizontalAdvance(run) for run in runs), default=0) if runs else 0
        if not runs or widest <= rect.width():
            super().paintEvent(event)
            return
        font = QFont(self.font())
        base_px = font.pixelSize() if font.pixelSize() > 0 else metrics.height()
        font.setPixelSize(max(self.MIN_PX, int(base_px * rect.width() / widest)))
        small = QFontMetrics(font)
        painter = QPainter(self)
        painter.setFont(font)
        painter.setPen(self.palette().color(self.foregroundRole()))
        y = rect.top()
        for run in runs:  # one run per line: each was too long to share one
            painter.drawText(
                QRectF(rect.left(), y, rect.width(), small.lineSpacing()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                small.elidedText(run, Qt.TextElideMode.ElideMiddle, rect.width()),
            )
            y += small.lineSpacing()
        painter.end()
