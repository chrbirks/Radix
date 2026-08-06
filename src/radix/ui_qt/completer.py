"""Keyboard-driven autocomplete popup for the input line.

Completions come from the same FUNCTIONS/CONSTANTS tables the evaluator
dispatches through, plus the session's variables, ``ans``, and the typed
commands — so the popup can never offer a name the engine would reject.

Interaction contract: the popup appears while typing an identifier (or on
Ctrl+Space), Up/Down navigate it, Tab inserts the highlighted item, and Enter
inserts only after the user has navigated — a plain Enter always evaluates,
so typing a full expression is never hijacked. Esc closes just the popup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeyEvent, QPainter
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from radix.engine.functions import CONSTANTS, FUNCTIONS
from radix.session import Session
from radix.ui_qt.highlight import color_for
from radix.ui_qt.input_edit import InputEdit
from radix.ui_qt.theme import Palette

MAX_VISIBLE_ROWS = 8
ITEM_ROLE = Qt.ItemDataRole.UserRole + 1
_IDENT_BEFORE_CURSOR = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

_COMMANDS = (
    ("help", "This overview; help <name> for one function or operator."),
    ("clear", "Clear history (variables & csrs kept)."),
    ("vars", "List defined variables (Alt+V pane)."),
    ("del", "del <name>: remove one variable."),
    ("csr", "Define/list CSR field layouts."),
)


@dataclass(frozen=True)
class Completion:
    name: str  # matched against the typed prefix
    insert: str  # replaces the prefix when accepted
    display: str  # left column in the popup (signature for functions)
    summary: str
    kind: str  # highlight kind driving the name color


def completions(session: Session) -> list[Completion]:
    items = [
        Completion(spec.name, spec.name + "(", spec.signature, spec.summary, "function")
        for spec in FUNCTIONS.values()
    ]
    for name in sorted(CONSTANTS):
        items.append(Completion(name, name, name, CONSTANTS[name][1], "constant"))
    if session.ans is not None:
        items.append(Completion("ans", "ans", "ans", "The previous result.", "constant"))
    for name in session.variables:
        items.append(Completion(name, name, name, "Session variable.", "ident"))
    for name, c in session.csrs.items():
        items.append(
            Completion(name, f"{name}(", name, f"csr: {c.spec_text()}", "csr")
        )
    for name, summary in _COMMANDS:
        items.append(Completion(name, name, name, summary, "paren"))
    return items


class _PopupDelegate(QStyledItemDelegate):
    """One row: bold colored signature, muted summary in a second column."""

    def __init__(self, palette: Palette) -> None:
        super().__init__()
        self.palette_tokens = palette
        self.name_column_px = 100  # set by Completer when populating

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        completion: Completion = index.data(ITEM_ROLE)
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(self.palette_tokens.hairline))
        rect = option.rect.adjusted(10, 0, -10, 0)
        flags = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        name_font = option.font
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(color_for(completion.kind, self.palette_tokens))
        painter.drawText(rect, flags, completion.display)
        name_font.setBold(False)
        painter.setFont(name_font)
        painter.setPen(QColor(self.palette_tokens.muted))
        summary_rect = rect.adjusted(self.name_column_px, 0, 0, 0)
        summary = painter.fontMetrics().elidedText(
            completion.summary, Qt.TextElideMode.ElideRight, summary_rect.width()
        )
        painter.drawText(summary_rect, flags, summary)
        painter.restore()

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        return QSize(option.rect.width(), option.fontMetrics.height() + 10)


class Completer:
    """Owns the popup and its interaction with one InputEdit."""

    def __init__(self, input_edit: InputEdit, session: Session, palette: Palette) -> None:
        self.input = input_edit
        self.session = session
        self.palette_tokens = palette
        self.navigated = False  # user pressed Up/Down since the popup appeared
        self.active = False  # popup is showing (isVisible is false in unshown tests)
        self._span = (0, 0)  # start and length of the prefix being completed
        self._suppress = False

        # A plain child widget overlaying the window — never a top-level
        # window, so no WM focus/positioning games (Wayland-safe).
        self.popup = QListWidget(input_edit.window())
        self.popup.setObjectName("completerPopup")
        self.popup.hide()
        self.popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.popup.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.popup.setUniformItemSizes(True)
        self.delegate = _PopupDelegate(palette)
        self.popup.setItemDelegate(self.delegate)
        self.popup.itemClicked.connect(lambda _item: self._accept())

        input_edit.textChanged.connect(self._on_change)
        input_edit.cursorPositionChanged.connect(self._on_change)

    # -- lifecycle ---------------------------------------------------------------

    def suppress_next(self) -> None:
        """Skip the popup for the next programmatic setText (history recall…)."""
        self._suppress = True

    def _on_change(self) -> None:
        if self._suppress:
            self._suppress = False
            self.hide()
            return
        self.refresh()

    def refresh(self, force: bool = False) -> None:
        prefix_at = self._current_prefix()
        if prefix_at is None:
            if not force:
                self.hide()
                return
            prefix_at = (self.input.textCursor().position(), "")
        start, prefix = prefix_at
        if not prefix and not force:
            self.hide()
            return
        matches = [c for c in completions(self.session) if c.name.startswith(prefix)]
        if not matches or (not force and len(matches) == 1 and matches[0].name == prefix):
            self.hide()  # nothing to offer beyond what is already typed
            return
        self._span = (start, len(prefix))
        window = self.input.window()
        if self.popup.parent() is not window:  # input was not in a window at init
            self.popup.setParent(window)
        self._populate(matches)
        self._position()
        self.popup.show()
        self.popup.raise_()
        self.active = True
        self.navigated = False

    def hide(self) -> None:
        self.popup.hide()
        self.active = False
        self.navigated = False

    def set_palette(self, palette: Palette) -> None:
        self.palette_tokens = palette
        self.delegate.palette_tokens = palette
        self.popup.viewport().update()

    # -- key handling (called first from MainWindow's event filter) ---------------

    def handle_key(self, event: QKeyEvent) -> bool:
        key = event.key()
        if (
            key == Qt.Key.Key_Space
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.refresh(force=True)
            return True
        if not self.active:
            return False
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            row = self.popup.currentRow() + (1 if key == Qt.Key.Key_Down else -1)
            self.popup.setCurrentRow(max(0, min(row, self.popup.count() - 1)))
            self.navigated = True
            return True
        if key == Qt.Key.Key_Tab:
            self._accept()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.navigated:
                self._accept()
                return True
            self.hide()  # plain Enter: let the expression evaluate
            return False
        if key == Qt.Key.Key_Escape:
            self.hide()
            return True
        return False

    # -- internals ----------------------------------------------------------------

    def _current_prefix(self) -> tuple[int, str] | None:
        """(start, text) of the identifier run just left of the cursor."""
        text = self.input.text()
        pos = self.input.textCursor().position()
        match = _IDENT_BEFORE_CURSOR.search(text[:pos])
        if match is None:
            return None
        start = match.start()
        # A run glued to a digit or ' is SI-suffix / HDL-literal territory
        # (2p, 8'h…): the lexer won't read it as a name, so don't offer names.
        if start > 0 and (text[start - 1].isdigit() or text[start - 1] == "'"):
            return None
        return start, match.group(0)

    def _accept(self) -> None:
        item = self.popup.currentItem()
        if item is None:
            return
        completion: Completion = item.data(ITEM_ROLE)
        start, length = self._span
        cursor = self.input.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(start + length, cursor.MoveMode.KeepAnchor)
        self._suppress = True
        cursor.insertText(completion.insert)
        self.input.setTextCursor(cursor)
        self.hide()

    def _populate(self, matches: list[Completion]) -> None:
        self.popup.clear()
        base_font = self.popup.font()
        bold = QFont(base_font)
        bold.setBold(True)
        name_metrics = QFontMetrics(bold)
        metrics = QFontMetrics(base_font)  # widget.fontMetrics() can dangle in PySide6
        name_w = max(name_metrics.horizontalAdvance(c.display) for c in matches) + 24
        summary_w = max(metrics.horizontalAdvance(c.summary) for c in matches)
        self.delegate.name_column_px = name_w
        for completion in matches:
            item = QListWidgetItem()
            item.setData(ITEM_ROLE, completion)
            self.popup.addItem(item)
        self.popup.setCurrentRow(0)
        row_h = metrics.height() + 10
        rows = min(len(matches), MAX_VISIBLE_ROWS)
        window_w = self.input.window().width()
        width = min(name_w + summary_w + 44, max(window_w - 24, 320))
        self.popup.setFixedSize(width, rows * row_h + 8)

    def _position(self) -> None:
        cursor = self.input.textCursor()
        cursor.setPosition(self._span[0])
        rect = self.input.cursorRect(cursor)
        window = self.input.window()
        anchor = self.input.viewport().mapTo(window, rect.topLeft())
        x = max(0, min(anchor.x() - 10, window.width() - self.popup.width()))
        self.popup.move(x, max(0, anchor.y() - self.popup.height() - 6))
