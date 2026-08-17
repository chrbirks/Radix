"""History list: model + delegate rendering it as a grouped ledger.

Two lines per entry (three with a note): a muted `expression`, then an
accent `= ` leader followed by the result. An assignment paints a rounded
chip with the variable name instead of the `x ← ` prefix text. A hairline
divider separates one entry from the next — the last entry gets none, since
the RESULT caption's rule already closes the pane.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from radix.engine.values import Value
from radix.ui_qt.theme import Palette

EXPRESSION_ROLE = Qt.ItemDataRole.UserRole + 1
RESULT_ROLE = Qt.ItemDataRole.UserRole + 2
NOTE_ROLE = Qt.ItemDataRole.UserRole + 3
PREFIX_ROLE = Qt.ItemDataRole.UserRole + 4

ROW_PAD_H = 10
ROW_PAD_TOP = 8
ROW_PAD_BOT = 8
LINE_GAP = 3
RESULT_INDENT = 16
BADGE_PAD_H = 6
BADGE_GAP = 8
SELECT_BAR_W = 2


def split_assignment(result: str, prefix: str) -> tuple[str, str]:
    """("x", "12") for an assignment entry's (result, prefix), else ("", result).

    Used by the history delegate to paint the variable name as a separate
    badge chip instead of inlining the "x ← " prefix text.
    """
    if not prefix:
        return "", result
    name = prefix.partition(" ←")[0]  # "x ← " -> "x"
    return name, result[len(prefix) :]


@dataclass(frozen=True)
class HistoryEntry:
    expression: str
    result: str  # formatted primary text (or "x ← 12" for assignments)
    note: str = ""
    # The raw result value lets entries re-render when a display setting
    # (base, notation, word size) changes. Entries loaded from disk carry a
    # reconstructed Value when the original was an int (HistoryStore persists
    # the raw number for those); float/text-only entries still load as
    # value=None and simply keep their recorded text, to avoid re-deriving a
    # value the engine might now compute differently.
    value: Value | None = None
    prefix: str = ""  # "x ← " for assignments, else ""
    timestamp: float = 0.0  # persistence only; not rendered


class HistoryModel(QAbstractListModel):
    def __init__(self) -> None:
        super().__init__()
        self.entries: list[HistoryEntry] = []

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return len(self.entries)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self.entries):
            return None
        entry = self.entries[index.row()]
        if role == EXPRESSION_ROLE:
            return entry.expression
        if role in (RESULT_ROLE, Qt.ItemDataRole.DisplayRole):
            return entry.result
        if role == NOTE_ROLE:
            return entry.note
        if role == PREFIX_ROLE:
            return entry.prefix
        if role == Qt.ItemDataRole.ToolTipRole:
            # The delegate elides both lines to the row width, so a long result
            # (`2**200`) is readable somewhere without going via the context
            # menu's copy.
            return f"{entry.expression}\n= {entry.result}"
        return None

    def append(self, entry: HistoryEntry) -> None:
        self.beginInsertRows(QModelIndex(), len(self.entries), len(self.entries))
        self.entries.append(entry)
        self.endInsertRows()

    def clear(self) -> None:
        self.beginResetModel()
        self.entries.clear()
        self.endResetModel()

    def remove(self, row: int) -> None:
        if 0 <= row < len(self.entries):
            self.beginRemoveRows(QModelIndex(), row, row)
            del self.entries[row]
            self.endRemoveRows()

    def reformat(self, primary: Callable[[Value], str]) -> None:
        """Rewrite results after a display setting (base/notation/…) change."""
        changed = False
        for i, entry in enumerate(self.entries):
            if entry.value is None:
                continue
            result = entry.prefix + primary(entry.value)
            if result != entry.result:
                self.entries[i] = replace(entry, result=result)
                changed = True
        if changed:
            first, last = self.index(0), self.index(len(self.entries) - 1)
            self.dataChanged.emit(first, last)


def _scaled(base: QFont, factor: float) -> QFont:
    """Scale a font whether it is pixel-sized (QSS px) or point-sized."""
    font = QFont(base)
    if base.pixelSize() > 0:
        font.setPixelSize(max(1, round(base.pixelSize() * factor)))
    else:
        font.setPointSizeF(max(1.0, base.pointSizeF() * factor))
    return font


# Kept short enough that both columns fit the 520px minimum window; the
# painter elides and drops trailing rows anyway if a theme's metrics differ.
EMPTY_HINT: tuple[tuple[str, str], ...] = (
    ("4.7k * 2", "SI and binary prefixes"),
    ("0xFF << 2", "hex/dec/bin + bit grid"),
    ("clkdiv(50M, 115200)", "the FPGA toolkit"),
    ("csr CTRL = EN[31]", "name and decode registers"),
    ("help", "everything else  (F1)"),
)
HINT_GAP = 20  # between the example column and its description
HINT_LINE = 26


class HistoryView(QListView):
    """History list that shows worked examples while it is empty.

    A cold start otherwise offered a placeholder line and an all-zero register
    panel — nothing about SI suffixes, the FPGA toolkit or CSR decoding, which
    is most of why the tool exists.
    """

    def __init__(self, palette: Palette) -> None:
        super().__init__()
        self.palette_tokens = palette

    def set_palette(self, palette: Palette) -> None:
        self.palette_tokens = palette
        self.viewport().update()

    def _is_empty(self) -> bool:
        model = self.model()
        return model is None or model.rowCount() == 0

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if not self._is_empty():
            return
        painter = QPainter(self.viewport())
        p = self.palette_tokens
        example_font = _scaled(self.font(), 1.0)
        note_font = _scaled(self.font(), 0.85)
        example_metrics = QFontMetrics(example_font)
        note_metrics = QFontMetrics(note_font)
        column = max(example_metrics.horizontalAdvance(text) for text, _ in EMPTY_HINT)
        width = column + HINT_GAP + max(
            note_metrics.horizontalAdvance(note) for _, note in EMPTY_HINT
        )
        rect = self.viewport().rect()
        # Only draw the rows that actually fit: a half-painted last line reads
        # as breakage, and this pane can be as short as PANE_MIN_H.
        rows = min(len(EMPTY_HINT), max(0, (rect.height() - 2 * ROW_PAD_TOP) // HINT_LINE))
        if rows == 0:
            painter.end()
            return
        left = max(ROW_PAD_H, (rect.width() - width) // 2)
        note_left = left + column + HINT_GAP
        note_width = rect.width() - note_left - ROW_PAD_H
        top = max(ROW_PAD_TOP, (rect.height() - rows * HINT_LINE) // 2)
        for row, (example, note) in enumerate(EMPTY_HINT[:rows]):
            y = top + row * HINT_LINE
            painter.setFont(example_font)
            painter.setPen(QColor(p.syn_number))
            painter.drawText(
                QRect(left, y, column, HINT_LINE),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                example,
            )
            if note_width <= 0:
                continue  # too narrow for the second column; examples alone
            painter.setFont(note_font)
            painter.setPen(QColor(p.muted))
            painter.drawText(
                QRect(note_left, y, note_width, HINT_LINE),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                note_metrics.elidedText(note, Qt.TextElideMode.ElideRight, note_width),
            )
        painter.end()


class HistoryDelegate(QStyledItemDelegate):
    """Muted `expression`, then an accent `= ` leader and the result."""

    def __init__(self, palette: Palette) -> None:
        super().__init__()
        self.palette_tokens = palette

    def set_palette(self, palette: Palette) -> None:
        self.palette_tokens = palette

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        painter.save()
        p = self.palette_tokens
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(p.chip_bg_active))
            bar_rect = QRect(
                option.rect.left(), option.rect.top(), SELECT_BAR_W, option.rect.height()
            )
            painter.fillRect(bar_rect, QColor(p.accent))

        rect = option.rect.adjusted(ROW_PAD_H, ROW_PAD_TOP, -ROW_PAD_H, -ROW_PAD_BOT)
        expression = index.data(EXPRESSION_ROLE) or ""
        result = index.data(RESULT_ROLE) or ""
        note = index.data(NOTE_ROLE) or ""
        prefix = index.data(PREFIX_ROLE) or ""

        expr_font = _scaled(option.font, 0.9)
        result_font = _scaled(option.font, 1.1)
        result_font.setBold(True)
        leader_font = _scaled(option.font, 1.1)
        note_font = _scaled(option.font, 0.85)
        expr_h = QFontMetrics(expr_font).height()
        result_h = QFontMetrics(result_font).height()

        y = rect.top()
        painter.setFont(expr_font)
        painter.setPen(QColor(p.muted))
        expr_rect = QRect(rect.left(), y, rect.width(), expr_h)
        painter.drawText(
            expr_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            QFontMetrics(expr_font).elidedText(
                expression, Qt.TextElideMode.ElideRight, expr_rect.width()
            ),
        )
        y += expr_h + LINE_GAP

        result_rect = QRect(
            rect.left() + RESULT_INDENT, y, rect.width() - RESULT_INDENT, result_h
        )
        result_metrics = QFontMetrics(result_font)
        x = result_rect.left()

        painter.setFont(leader_font)
        painter.setPen(QColor(p.accent))
        leader_w = QFontMetrics(leader_font).horizontalAdvance("= ")
        painter.drawText(
            QRect(x, result_rect.top(), leader_w, result_rect.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "= ",
        )
        x += leader_w

        name, display_result = split_assignment(result, prefix)
        if name:
            badge_w = result_metrics.horizontalAdvance(name) + 2 * BADGE_PAD_H
            badge_rect = QRect(x, result_rect.top() + 2, badge_w, result_rect.height() - 4)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.chip_bg))
            painter.drawRoundedRect(badge_rect, 8, 8)
            painter.setPen(QColor(p.accent))
            painter.setFont(result_font)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, name)
            x += badge_w + BADGE_GAP

        painter.setFont(result_font)
        painter.setPen(QColor(p.text))
        # Elide rather than let the text run off the row: a 61-digit `2**200`
        # used to end flush at the edge mid-digit, indistinguishable from a
        # result that just happened to fit. The full text is in the tooltip.
        value_rect = QRect(
            x, result_rect.top(), max(0, result_rect.right() - x), result_rect.height()
        )
        painter.drawText(
            value_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            result_metrics.elidedText(
                display_result, Qt.TextElideMode.ElideRight, value_rect.width()
            ),
        )

        if note:
            y += result_h + LINE_GAP
            note_h = QFontMetrics(note_font).height()
            painter.setFont(note_font)
            painter.setPen(QColor(p.muted))
            note_rect = QRect(rect.left() + RESULT_INDENT, y, rect.width() - RESULT_INDENT, note_h)
            painter.drawText(
                note_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"({note})",
            )

        # Between entries only. The trailing rule under the newest entry
        # separated nothing, and landed a few pixels above the RESULT caption's
        # own rule — three hairlines inside ~18px, which read as an artifact.
        model = index.model()
        if model is not None and index.row() < model.rowCount() - 1:
            painter.setPen(QColor(p.hairline))
            painter.drawLine(
                option.rect.left() + ROW_PAD_H,
                option.rect.bottom(),
                option.rect.right() - ROW_PAD_H,
                option.rect.bottom(),
            )
        painter.restore()

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        expr_h = QFontMetrics(_scaled(option.font, 0.9)).height()
        result_h = QFontMetrics(_scaled(option.font, 1.1)).height()
        height = ROW_PAD_TOP + ROW_PAD_BOT + expr_h + LINE_GAP + result_h
        if index.data(NOTE_ROLE):
            note_h = QFontMetrics(_scaled(option.font, 0.85)).height()
            height += LINE_GAP + note_h
        return QSize(option.rect.width(), height)
