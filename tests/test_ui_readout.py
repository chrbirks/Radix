"""The RESULT readout and what Ctrl+Shift+C copies are one thing: the last
history entry under the current display settings. The inspector, when locked
on an entry, re-renders that entry when a setting changes."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from radix.history.store import HistoryStore  # noqa: E402
from radix.session import Session  # noqa: E402
from radix.ui_qt.main_window import MainWindow  # noqa: E402
from radix.ui_qt.theme import LIGHT  # noqa: E402


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    win = MainWindow(Session(), LIGHT)
    qtbot.addWidget(win)
    return win


def _submit(qtbot, window: MainWindow, text: str) -> None:  # type: ignore[no-untyped-def]
    window.input.setText(text)
    qtbot.keyClick(window.input, Qt.Key.Key_Return)


# -- copy follows the readout ---------------------------------------------------


def test_copy_result_follows_display_base(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "255")
    window._cycle_int_base()  # dec -> hex
    assert window.result_label.text() == "0xFF"
    window._copy_result()
    assert QApplication.clipboard().text() == "0xFF"


def test_copy_result_for_assignment_copies_value_only(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "x = 5")
    assert window.result_label.text() == "x ← 5"
    window._copy_result()
    assert QApplication.clipboard().text() == "5"


def test_copy_result_works_for_restored_history(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    store = HistoryStore(tmp_path / "history.jsonl")
    win1 = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win1)
    _submit(qtbot, win1, "6*7")
    win1.close()

    win2 = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win2)
    assert win2.result_label.text() == "42"
    QApplication.clipboard().setText("sentinel")
    win2._copy_result()
    assert QApplication.clipboard().text() == "42"


# -- readout empties with the history ------------------------------------------


def test_clear_resets_readout(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "255")
    _submit(qtbot, window, "clear")
    assert window.result_label.text() == "—"
    assert window.result_label.property("dimmed") == "true"
    QApplication.clipboard().setText("sentinel")
    window._copy_result()
    assert QApplication.clipboard().text() == "sentinel"  # nothing to copy


def test_deleting_last_entry_moves_readout_to_previous(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "1")
    _submit(qtbot, window, "255")
    window._history_action("delete", 1)
    assert window.result_label.text() == "1"


def test_deleting_only_entry_resets_readout(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "255")
    window._history_action("delete", 0)
    assert window.result_label.text() == "—"
    assert window.result_label.property("dimmed") == "true"


def test_clearing_history_view_resets_readout(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "255")
    window._clear_history_view()  # Ctrl+L
    assert window.result_label.text() == "—"


# -- locked inspector re-renders under new settings -----------------------------


def test_word_size_change_rerenders_locked_float_entry(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window._toggle_float_view()  # FLOAT ON
    _submit(qtbot, window, "2.5")
    window._inspect_from_view(window.model.index(0))
    assert window._inspect_locked
    assert window.intview.float_mode is not None
    assert window.intview.float_mode.width == 32
    window._cycle_word_size()  # 32 -> 64
    assert window.intview.float_mode is not None
    assert window.intview.float_mode.width == 64
    assert window._inspect_locked  # a setting change is not "typing"


def test_float_off_clears_locked_float_view(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window._toggle_float_view()  # FLOAT ON
    _submit(qtbot, window, "2.5")
    window._inspect_from_view(window.model.index(0))
    assert window.intview.float_mode is not None
    window._toggle_float_view()  # FLOAT OFF
    assert window.intview.float_mode is None
