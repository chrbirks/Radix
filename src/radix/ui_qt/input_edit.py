"""Single-line expression input with syntax highlighting.

QLineEdit cannot render per-token colors, so this is a QPlainTextEdit
constrained to one line: Enter submits instead of inserting a newline,
pasted newlines are stripped, and the height is locked to one text row.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QMimeData, Qt, Signal
from PySide6.QtGui import QFontMetrics, QKeyEvent, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget


class InputEdit(QPlainTextEdit):
    submitted = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        self._lock_height()

    def _lock_height(self) -> None:
        height = QFontMetrics(self.font()).height() + 24  # matches the QSS padding
        self.setFixedHeight(height)

    def changeEvent(self, event: object) -> None:  # font/style changes
        super().changeEvent(event)  # type: ignore[arg-type]
        self._lock_height()

    # -- QLineEdit-compatible helpers -----------------------------------------

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:
        self.setPlainText(text)
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)

    # -- single-line behavior ----------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.submitted.emit()
            return
        mods = event.modifiers()
        if mods == Qt.KeyboardModifier.ControlModifier and self._handle_ctrl_key(event.key()):
            return
        if mods == Qt.KeyboardModifier.AltModifier and self._handle_alt_key(event.key()):
            return
        super().keyPressEvent(event)

    # -- bash/readline-style line editing ----------------------------------------

    def _handle_ctrl_key(self, key: int) -> bool:
        cursor = self.textCursor()
        if key == Qt.Key.Key_B:
            cursor.movePosition(QTextCursor.MoveOperation.Left)
        elif key == Qt.Key.Key_F:
            cursor.movePosition(QTextCursor.MoveOperation.Right)
        elif key == Qt.Key.Key_E:
            cursor.movePosition(QTextCursor.MoveOperation.EndOfLine)
        elif key == Qt.Key.Key_D:
            cursor.deleteChar()
        elif key == Qt.Key.Key_H:
            cursor.deletePreviousChar()
        elif key == Qt.Key.Key_W:
            cursor.movePosition(QTextCursor.MoveOperation.WordLeft, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
        else:
            return False
        self.setTextCursor(cursor)
        return True

    def _handle_alt_key(self, key: int) -> bool:
        cursor = self.textCursor()
        if key == Qt.Key.Key_B:
            cursor.movePosition(QTextCursor.MoveOperation.WordLeft)
        elif key == Qt.Key.Key_F:
            cursor.movePosition(QTextCursor.MoveOperation.WordRight)
        else:
            return False
        self.setTextCursor(cursor)
        return True

    def insertFromMimeData(self, source: QMimeData) -> None:
        self.insertPlainText(" ".join(source.text().splitlines()))


class InputBar(QWidget):
    """Prompt glyph + expression input + live preview, styled as one control.

    Grows an accent underline while `input` has focus (the `focused` dynamic
    property), so the always-focused input line still gives visible feedback
    when focus briefly leaves it (e.g. a history double-click).
    """

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("inputBar")
        # Plain QWidgets ignore QSS background/border without this — the
        # surface band and the focus underline silently never painted.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("focused", "false")

        self.prompt = QLabel("›")
        self.prompt.setObjectName("prompt")

        self.input = InputEdit()
        self.input.setObjectName("input")
        self.input.installEventFilter(self)

        self.preview = QLabel(" ")
        self.preview.setObjectName("preview")

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.prompt)
        row.addWidget(self.input, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(row)
        layout.addWidget(self.preview)

    def eventFilter(self, obj: object, event: QEvent) -> bool:
        if obj is self.input and event.type() in (
            QEvent.Type.FocusIn,
            QEvent.Type.FocusOut,
        ):
            self._set_focused(event.type() == QEvent.Type.FocusIn)
        return super().eventFilter(obj, event)  # type: ignore[arg-type]

    def _set_focused(self, focused: bool) -> None:
        self.setProperty("focused", "true" if focused else "false")
        self.style().unpolish(self)
        self.style().polish(self)
