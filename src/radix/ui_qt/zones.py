"""Silkscreen-style section captions for front-panel zones.

A small paint-only label (uppercase text + a hairline rule filling the rest
of the width) reused above the inspector's TRACE/READOUT/REGISTER zones.
Separate module so both `inspector.py` and `bit_panel.py` can import it
without creating a cycle between them.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QHBoxLayout, QWidget

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
