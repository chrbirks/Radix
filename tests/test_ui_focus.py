"""Keyboard-first contract: focus never leaves the input line, and edits the
program makes to the line (recall, inserts, re-highlights) never pop the
completer the way typing does."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from radix.session import Session  # noqa: E402
from radix.ui_qt.main_window import MainWindow  # noqa: E402
from radix.ui_qt.theme import DARK, LIGHT  # noqa: E402


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    """Shown and focused: focus assertions need a real active window."""
    win = MainWindow(Session(), LIGHT)
    qtbot.addWidget(win)
    win.show()
    win.input.setFocus()
    QApplication.processEvents()
    return win


def _submit(qtbot, window: MainWindow, text: str) -> None:  # type: ignore[no-untyped-def]
    window.input.setText(text)
    qtbot.keyClick(window.input, Qt.Key.Key_Return)


# -- focus leaks ----------------------------------------------------------------


def test_tab_with_help_showing_keeps_focus_on_input(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "help")
    assert window.help_pane.isVisibleTo(window)
    qtbot.keyClick(window.input, Qt.Key.Key_Tab)
    assert QApplication.focusWidget() is window.input
    qtbot.keyClicks(window.input, "1+1")
    assert window.input.text() == "1+1"


def test_click_on_help_pane_keeps_focus_on_input(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "help")
    qtbot.mouseClick(window.help_pane.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    assert QApplication.focusWidget() is window.input


def test_click_on_result_readout_keeps_focus_on_input(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "6*7")
    qtbot.mouseClick(window.result_label, Qt.MouseButton.LeftButton)
    assert QApplication.focusWidget() is window.input


def test_click_on_lane_value_keeps_focus_on_input(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF")
    qtbot.mouseClick(window.intview.rows["HEX"][1], Qt.MouseButton.LeftButton)
    assert QApplication.focusWidget() is window.input


# -- completer re-entrancy ------------------------------------------------------


def test_history_recall_does_not_pop_completer(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "a = 1")
    _submit(qtbot, window, "2*a")  # "a" also prefixes abs/acos/asin/atan/ans
    qtbot.keyClick(window.input, Qt.Key.Key_Up)
    assert window.input.text() == "2*a"
    assert not window.completer.active
    qtbot.keyClick(window.input, Qt.Key.Key_Up)  # recalls further, not popup navigation
    assert window.input.text() == "a = 1"


def test_vars_pane_insert_does_not_pop_completer(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "a = 1")
    window._show_vars()
    window._insert_var_name(window.vars_pane.item(0))
    assert window.input.text() == "a"
    assert not window.completer.active


def test_theme_change_does_not_reopen_dismissed_completer(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    qtbot.keyClicks(window.input, "si")
    assert window.completer.active
    qtbot.keyClick(window.input, Qt.Key.Key_Escape)
    assert not window.completer.active
    window.apply_palette(DARK)
    assert not window.completer.active


def test_decimal_mode_change_does_not_reopen_dismissed_completer(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    qtbot.keyClicks(window.input, "si")
    qtbot.keyClick(window.input, Qt.Key.Key_Escape)
    window._toggle_decimal_mode()
    assert not window.completer.active


def test_typing_still_pops_completer(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    qtbot.keyClicks(window.input, "si")
    assert window.completer.active
    qtbot.keyClick(window.input, Qt.Key.Key_Escape)
    qtbot.keyClicks(window.input, "n")  # a real edit after Esc reopens it
    assert window.completer.active
