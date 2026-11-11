"""Regression tests for the November 2026 review of the desktop UI.

Each test names the defect it pins. Geometry is asserted on `styled_window`
(the real stylesheet and Fusion metrics, as `app.run_gui` sets them) because
none of these layout defects exist at the bare default font.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QObject, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QFontMetrics  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from radix.engine.viz import ClockViz, MemViz  # noqa: E402
from radix.history.store import HistoryStore  # noqa: E402
from radix.session import Session  # noqa: E402
from radix.ui_qt import theme  # noqa: E402
from radix.ui_qt.main_window import MainWindow  # noqa: E402
from radix.ui_qt.theme import DARK, LIGHT  # noqa: E402

CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    win = MainWindow(Session(), LIGHT)
    qtbot.addWidget(win)
    return win


@pytest.fixture
def styled(qtbot, qapp):  # type: ignore[no-untyped-def]
    """Factory for shown windows under the real stylesheet: styled(width, height, **session)."""
    mono, label = theme.load_bundled_font()
    previous_sheet = qapp.styleSheet()
    previous_style = qapp.style().objectName()
    qapp.setStyle("Fusion")
    qapp.setStyleSheet(theme.stylesheet(LIGHT, mono, label))

    def make(width: int = 640, height: int = 880, **settings: object) -> MainWindow:
        win = MainWindow(Session(**settings), LIGHT)  # type: ignore[arg-type]
        qtbot.addWidget(win)
        win.resize(width, height)
        win.show()
        qtbot.waitExposed(win)
        qtbot.wait(30)
        return win

    yield make
    qapp.setStyleSheet(previous_sheet)
    QApplication.setStyle(previous_style)


@pytest.fixture
def stored(qtbot, tmp_path):  # type: ignore[no-untyped-def]
    """Factory for windows backed by a real history file and an isolated INI."""
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "cfg"))
    store = HistoryStore(tmp_path / "history.jsonl")

    def make(**settings: object) -> MainWindow:
        win = MainWindow(Session(**settings), LIGHT, store=store)  # type: ignore[arg-type]
        qtbot.addWidget(win)
        return win

    make.store = store  # type: ignore[attr-defined]
    return make


def _submit(qtbot, window: MainWindow, text: str) -> None:  # type: ignore[no-untyped-def]
    window.input.setText(text)
    qtbot.keyClick(window.input, Qt.Key.Key_Return)


def _type(qtbot, window: MainWindow, text: str) -> None:  # type: ignore[no-untyped-def]
    window.input.clear()
    qtbot.keyClicks(window.input, text)
    window._update_preview()  # what the debounce timer would do


def _disk_lines(store: HistoryStore) -> int:
    return len(store.path.read_text(encoding="utf-8").splitlines()) if store.path.exists() else 0


# -- pinned channels ---------------------------------------------------------------------


class _WindowSpy(QObject):
    """Records every top-level widget that gets shown, other than `main`."""

    def __init__(self, main: QWidget) -> None:
        super().__init__()
        self.main = main
        self.shown: list[str] = []

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.Show
            and isinstance(obj, QWidget)
            and obj.isWindow()
            and obj is not self.main
        ):
            self.shown.append(type(obj).__name__)
        return False


def test_pinning_never_shows_a_second_top_level_window(qtbot, styled) -> None:  # type: ignore[no-untyped-def]
    # The strip's bit row was made visible before it had a parent, so every pin
    # (and every setting change with a pin) created and showed a native 640x12
    # window. Offscreen that also took activation away: all shortcuts died.
    win = styled()
    _submit(qtbot, win, "0xDEADBEEF")
    spy = _WindowSpy(win)
    QApplication.instance().installEventFilter(spy)
    try:
        win._pin_last_result()
        win._cycle_word_size()  # rebuilds the rack
        win.channels._toggle_ref(0)
        QApplication.processEvents()
    finally:
        QApplication.instance().removeEventFilter(spy)
    assert spy.shown == []
    assert QApplication.activeWindow() is win


def test_wide_pinned_value_never_widens_the_inspector_past_the_window(qtbot, styled) -> None:  # type: ignore[no-untyped-def]
    # BIN base + a pinned 64-bit value made the inspector 989px wide in a 640px
    # window with horizontal scrolling off: copy buttons and bit cells clipped.
    win = styled(640, 880, word_size=64)
    _submit(qtbot, win, "0xDEADBEEFCAFEF00D")
    win._pin_last_result()
    win._cycle_int_base()
    win._cycle_int_base()  # dec -> hex -> bin
    win.channels._toggle_ref(0)
    qtbot.wait(30)
    viewport = win.inspector_scroll.viewport().width()
    assert win.inspector.minimumSizeHint().width() <= viewport
    assert win.inspector.width() <= viewport
    label = win.channels._strips[0].value_label
    assert label.text().startswith("0b1101_1110")  # the value itself is intact...
    assert label.toolTip() == label.text()  # ...and readable in full on hover


def test_inspector_fits_the_minimum_window_for_a_128_bit_word(qtbot, styled) -> None:  # type: ignore[no-untyped-def]
    win = styled(520, 600)
    _submit(qtbot, win, "fix(-0.3, 64, 64)")
    qtbot.wait(30)
    assert win.inspector.minimumSizeHint().width() <= win.inspector_scroll.viewport().width()


def test_pinned_value_past_the_digit_cap_survives_the_settings_file(qtbot, stored) -> None:  # type: ignore[no-untyped-def]
    win = stored()
    _submit(qtbot, win, "2**20000")
    win._pin_last_result()
    win.close()  # writes the rack to the INI
    again = stored()
    assert again.channels.channels[0].value is not None
    assert again.channels.channels[0].value.number == 2**20000


def test_rack_starts_at_the_session_word_size(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    # It was hard-coded to 64 until the first setting change: at 32-bit a
    # pinned -1 drew 64 lit bits and "-> input" wrote 0xFFFFFFFFFFFFFFFF.
    _submit(qtbot, window, "-1")
    window._pin_last_result()
    sent: list[str] = []
    window.channels.to_input.connect(sent.append)
    window.channels._strips[0]._send_to_input()
    assert sent == ["0xFFFFFFFF"]


# -- persistence ---------------------------------------------------------------------------


def test_a_failed_history_write_does_not_strand_the_line(qtbot, stored, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    win = stored()

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(win.store, "append", fail)
    _submit(qtbot, win, "6*7")
    assert win.input.text() == ""  # evaluated and cleared, as on a good day
    assert win.model.entries[-1].result == "42"
    assert "not saved" in win.preview.text()  # ...and the failure is said out loud


def test_value_past_the_digit_cap_does_not_break_saving(qtbot, stored) -> None:  # type: ignore[no-untyped-def]
    win = stored()
    _submit(qtbot, win, "x = 2**20000")
    assert win.input.text() == ""
    _submit(qtbot, win, "1+1")
    assert win.input.text() == ""
    assert _disk_lines(stored.store) == 2
    win.close()
    again = stored()
    assert again.session.variables["x"].number == 2**20000


def test_deleting_an_entry_after_ctrl_l_keeps_the_hidden_history_on_disk(qtbot, stored) -> None:  # type: ignore[no-untyped-def]
    win = stored()
    for text in ("1+1", "2+2", "3+3", "4+4"):
        _submit(qtbot, win, text)
    win._clear_history_view()  # Ctrl+L: the view only
    assert win.model.rowCount() == 0 and _disk_lines(stored.store) == 4
    _submit(qtbot, win, "5+5")
    _submit(qtbot, win, "6+6")
    win._history_action("delete", 0)
    assert win.model.rowCount() == 1
    assert _disk_lines(stored.store) == 5  # was 1: the four hidden entries went too
    win.close()
    again = stored()
    assert [e.expression for e in again.model.entries] == ["1+1", "2+2", "3+3", "4+4", "6+6"]


def test_ctrl_l_toast_does_not_promise_clear_wipes_variables(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window._clear_history_view()
    assert "wipe" not in window.preview.text()


def test_persisted_settings_reach_widgets_built_before_they_loaded(qtbot, stored) -> None:  # type: ignore[no-untyped-def]
    win = stored(decimal_mode="comma")
    _submit(qtbot, win, "255")
    win._toggle_decimal_mode()  # -> period
    win._cycle_int_base()  # -> hex
    win.close()
    again = stored(decimal_mode="comma")  # the app's entry-point default
    assert again.session.decimal_mode == "period" and again.session.int_base == "hex"
    assert again.highlighter.syntax.decimal == "."  # was still the comma grammar
    assert again.model.entries[-1].result == "0xFF"  # was "255" under a HEX chip
    assert again.result_label.text() == "0xFF"


# -- the RESULT readout and the preview line ---------------------------------------------


def test_result_readout_wraps_a_value_wider_than_the_window(qtbot, styled) -> None:  # type: ignore[no-untyped-def]
    win = styled()
    one_line = QFontMetrics(win.result_label.font()).height()
    _submit(qtbot, win, "1+1")
    qtbot.wait(20)
    assert win.result_label.height() < 2 * one_line + 16
    _submit(qtbot, win, "2**200")  # 61 digits: was cut at the edge mid-number
    qtbot.wait(20)
    assert win.result_label.text() == str(2**200)
    assert win.result_label.height() >= 2 * one_line


def test_preview_keeps_the_result_when_the_echo_is_too_long(qtbot, styled) -> None:  # type: ignore[no-untyped-def]
    win = styled()
    _type(
        qtbot,
        win,
        "(0xDEADBEEF << 4 | 0xF0F0F0F0 & ~mask(12)) ^ (revbits(0x1234, 16) + popcount(0xFFFF))",
    )
    shown = win.preview.text()
    assert "…" in shown
    value = win.session.preview(win.input.text()).value
    assert value is not None
    assert shown.endswith("= " + win.session.format_value(value))


def test_preview_does_not_echo_a_bare_literal_back_at_itself(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _type(qtbot, window, "4294967290")
    assert window.preview.text() == "= 4294967290"  # was "4294967290 = 4294967290"
    _type(qtbot, window, "0xFF")
    assert window.preview.text() == "= 255"
    _type(qtbot, window, "4.7k")
    assert window.preview.text() == "= 4700"
    _type(qtbot, window, "0xFF + 1")
    assert window.preview.text() == "255 + 1 = 256"


@pytest.mark.parametrize("text", ["cl", "clog", "sin(cl", "1 + rev", "si"])
def test_a_name_still_being_typed_is_not_an_error(qtbot, window: MainWindow, text: str) -> None:  # type: ignore[no-untyped-def]
    # Typing `cl` on the way to `clog2(` flashed a red "undefined variable 'cl'"
    # with a wavy underline, while the completer was offering exactly that.
    _type(qtbot, window, text)
    assert window.preview.property("state") == "ok"
    assert window.preview.text() == "…"
    assert window.highlighter.error_span is None


@pytest.mark.parametrize("text", ["zz", "cl + 1", "clog2(zz)", "nope"])
def test_a_name_that_completes_to_nothing_is_an_error(qtbot, window: MainWindow, text: str) -> None:  # type: ignore[no-untyped-def]
    _type(qtbot, window, text)
    assert window.preview.property("state") == "error"


# -- keyboard --------------------------------------------------------------------------------


def test_history_recall_gives_the_half_typed_line_back(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "1+1")
    _submit(qtbot, window, "2+2")
    window.input.setText("0xDEAD & mask(")
    qtbot.keyClick(window.input, Qt.Key.Key_Up)
    assert window.input.text() == "2+2"
    qtbot.keyClick(window.input, Qt.Key.Key_Up)
    assert window.input.text() == "1+1"
    qtbot.keyClick(window.input, Qt.Key.Key_Down)
    qtbot.keyClick(window.input, Qt.Key.Key_Down)
    assert window.input.text() == "0xDEAD & mask("  # was "": the draft was gone


def test_page_keys_scroll_the_history(qtbot, styled) -> None:  # type: ignore[no-untyped-def]
    win = styled()
    for i in range(30):
        _submit(qtbot, win, f"{i}+1")
    qtbot.wait(30)
    bar = win.history_view.verticalScrollBar()
    assert bar.maximum() > 0 and bar.value() == bar.maximum()
    qtbot.keyClick(win.input, Qt.Key.Key_PageUp)
    assert bar.value() < bar.maximum()  # was a no-op: history had no keyboard scroll
    qtbot.keyClick(win.input, Qt.Key.Key_PageDown)
    assert bar.value() == bar.maximum()


def test_shift_page_keys_scroll_the_inspector(qtbot, styled) -> None:  # type: ignore[no-untyped-def]
    win = styled(640, 700, word_size=64)
    _submit(qtbot, win, "0xDEADBEEFCAFEF00D")
    win._pin_last_result()
    qtbot.wait(30)
    bar = win.inspector_scroll.verticalScrollBar()
    assert bar.maximum() > 0  # the grid and the rack do not fit: something is below the fold
    qtbot.keyClick(win.input, Qt.Key.Key_PageDown, SHIFT)
    assert bar.value() > 0
    qtbot.keyClick(win.input, Qt.Key.Key_PageUp, SHIFT)
    assert bar.value() == 0


def test_help_names_the_scroll_keys(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from radix.ui_qt.main_window import SHORTCUT_HELP

    assert "PageUp" in SHORTCUT_HELP and "Shift+PageUp" in SHORTCUT_HELP


def test_completing_a_help_topic_inserts_the_name_not_a_call(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.show()
    qtbot.keyClicks(window.input, "help si")
    assert window.completer.active
    qtbot.keyClick(window.input, Qt.Key.Key_Tab)
    assert window.input.text() == "help sin"  # was "help sin(": "no help for 'sin('"


# -- copying ---------------------------------------------------------------------------------


def test_copy_as_dec_is_the_integer_whatever_the_notation(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "255")
    window._cycle_notation()  # auto -> sci: the row now reads 2.55e+2
    window._history_action("copy_dec", 0)
    assert QApplication.clipboard().text() == "255"


@pytest.mark.parametrize(
    ("action", "want"),
    [("copy_c", "0xDEADBEEF"), ("copy_verilog", "32'hDEAD_BEEF"), ("copy_vhdl", 'x"DEAD_BEEF"')],
)
def test_history_copies_an_integer_as_source_literals(
    qtbot, window: MainWindow, action: str, want: str
) -> None:  # type: ignore[no-untyped-def]
    # The HEX lane copies 0xDEAD_BEEF, which C rejects and Verilog wants sized.
    _submit(qtbot, window, "0xDEADBEEF")
    window._history_action(action, 0)
    assert QApplication.clipboard().text() == want


def test_source_literals_use_the_declared_width(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "12'hABC")
    window._history_action("copy_verilog", 0)
    assert QApplication.clipboard().text() == "12'hABC"
    window._history_action("copy_vhdl", 0)
    assert QApplication.clipboard().text() == 'x"ABC"'


# -- status bar ------------------------------------------------------------------------------


def test_sign_chip_tooltip_describes_what_the_toggle_does(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    tip = window.status_items["sign"].toolTip()
    assert "SGN" not in tip  # that row only exists in the float view, and shows its sign
    assert ">>" in tip


# -- float view and settings -----------------------------------------------------------------


def test_float_off_removes_the_float_view_even_while_typing(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window._toggle_float_view()  # on
    _submit(qtbot, window, "1/3")
    assert window.intview.float_mode is not None
    _type(qtbot, window, "1 +")  # incomplete: the panel holds steady
    window._toggle_float_view()  # off
    assert window.intview.float_mode is None  # was left showing under a FLOAT OFF chip


def test_word_size_change_reforms_the_float_view_while_typing(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window._toggle_float_view()
    _submit(qtbot, window, "1/3")
    assert window.intview.float_mode is not None and window.intview.float_mode.width == 32
    _type(qtbot, window, "1 +")
    window._cycle_word_size()  # 32 -> 64
    assert window.intview.float_mode is not None and window.intview.float_mode.width == 64


# -- first run -------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["comma", "period"])
def test_every_first_run_example_works_as_typed(qtbot, mode: str) -> None:  # type: ignore[no-untyped-def]
    # The hint is the first thing a new user reads; in the shipped comma mode
    # it offered `clkdiv(50M, 115200)`, which that mode rejects.
    win = MainWindow(Session(decimal_mode=mode), LIGHT)
    qtbot.addWidget(win)
    rows = win.history_view.hint_rows()
    assert len(rows) >= 3
    for example, _note in rows:
        win.session.evaluate(example, commit=False)  # raises CalcError if it would not work


def test_first_run_examples_follow_a_decimal_mode_change(qtbot) -> None:  # type: ignore[no-untyped-def]
    win = MainWindow(Session(decimal_mode="comma"), LIGHT)
    qtbot.addWidget(win)
    assert any(";" in example for example, _ in win.history_view.hint_rows())
    win._toggle_decimal_mode()
    assert not any(";" in example for example, _ in win.history_view.hint_rows())


def test_help_overview_needs_no_sideways_scrolling_at_the_default_width(qtbot, styled) -> None:  # type: ignore[no-untyped-def]
    # The intro and shortcut blocks were <pre>: at 640px, 246px of them were
    # off to the right with no keyboard way to reach it.
    win = styled()
    _submit(qtbot, win, "help")
    qtbot.wait(30)
    assert win.help_pane.horizontalScrollBar().maximum() == 0


def test_help_overview_fits_the_minimum_width(qtbot, styled) -> None:  # type: ignore[no-untyped-def]
    win = styled(520, 600)
    _submit(qtbot, win, "help")
    qtbot.wait(30)
    assert win.help_pane.horizontalScrollBar().maximum() == 0


# -- bit grid --------------------------------------------------------------------------------


def test_one_bit_selection_is_singular(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF")
    window.intview.grid_widget.set_selection((5, 5))
    assert window.intview.slice_label.text() == "[5:5] = 0x1 = 1 (1 bit)"
    window.intview.grid_widget.set_selection((7, 4))
    assert window.intview.slice_label.text().endswith("(4 bits)")


def test_right_click_does_not_toggle_a_bit(qtbot, styled) -> None:  # type: ignore[no-untyped-def]
    win = styled()
    _submit(qtbot, win, "0xFF")
    grid = win.intview.grid_widget
    centre = grid._cell_rect(0).center().toPoint()
    qtbot.mouseClick(grid, Qt.MouseButton.RightButton, pos=centre)
    assert win.intview.scratch == 0xFF
    qtbot.mouseClick(grid, Qt.MouseButton.LeftButton, pos=centre)
    assert win.intview.scratch == 0xFE


def test_bit_cursor_stays_inside_a_narrower_word(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    while window.session.word_size != 64:
        window._cycle_word_size()
    _submit(qtbot, window, "0xFF")
    window._toggle_grid_cursor()  # lands on bit 63
    assert window.intview.cursor_bit == 63
    window._cycle_word_size()  # 64 -> 8
    assert window.intview.cursor_bit is not None and window.intview.cursor_bit <= 7
    window.intview.toggle_cursor_bit()
    assert window.intview.scratch < 0x100 * 2  # the toggled bit is one that is on screen


def _bin_rows(win: MainWindow) -> list[str]:
    markup = win.intview.rows["BIN"][1].text()
    plain = re.sub(r"<(?!br)[^>]+>", "", markup).replace("&nbsp;", " ")
    return [row.strip() for row in plain.split("<br>")]


@pytest.mark.parametrize(("width", "per_row"), [(640, 8), (520, 4)])
def test_64_bit_binary_readout_breaks_into_equal_rows(
    qtbot, styled, width: int, per_row: int
) -> None:  # type: ignore[no-untyped-def]
    # It wrapped wherever the label ran out: 6, 7 and 3 nibbles at 520px.
    win = styled(width, 880, word_size=64)
    _submit(qtbot, win, "0xDEADBEEFCAFEF00D")
    qtbot.wait(30)
    rows = _bin_rows(win)
    assert len(rows) == 16 // per_row
    assert [len(row.removeprefix("0b").split()) for row in rows] == [per_row] * len(rows)


def test_32_bit_binary_readout_is_one_row_when_it_fits(qtbot, styled) -> None:  # type: ignore[no-untyped-def]
    win = styled()
    _submit(qtbot, win, "0xDEADBEEF")
    qtbot.wait(30)
    assert _bin_rows(win) == ["0b1101 1110 1010 1101 1011 1110 1110 1111"]


# -- TRACE cards -----------------------------------------------------------------------------


def _card(win: MainWindow, payload: object) -> list[tuple[str, float, float]]:
    """(text, left, right) of everything the card would draw."""
    win.inspector.show_viz_payload(payload)  # type: ignore[arg-type]
    QApplication.processEvents()
    return [(text, rect.left(), rect.right()) for text, rect in win.vizpanel.text_layout()]


CLOCK = ClockViz(
    freq_text="100M", period_text="10n", divisor=3, target_text="33M",
    achieved_text="33.3333333333M", error_text="+1.01%", error_ppm=10101.0,
    wave_high=4, wave_low=2, duty_text="66.7%",
)
MEM = MemViz(
    depth=4096, width=36, addr_bits=12, total_bits=147456, bytes_text="18 KiB",
    addressable=4096, utilization=1.0, util_text="100%",
)


@pytest.mark.parametrize("width", [520, 640])
@pytest.mark.parametrize("payload", [CLOCK, MEM], ids=["clkdiv", "mem"])
def test_trace_card_draws_all_of_its_text_inside_the_card(
    qtbot, styled, width: int, payload: object
) -> None:  # type: ignore[no-untyped-def]
    # At 520px the clock card lost "err +64 ppm" off the right edge; at 640 the
    # memory card lost "power of two"; the waveform label lost its unit.
    win = styled(width, 700)
    items = _card(win, payload)
    drawn = " ".join(text for text, _l, _r in items)
    for text, left, right in items:
        assert left >= 0 and right <= win.vizpanel.width(), text
        assert "…" not in text, text
    if payload is CLOCK:
        assert "err +1.01%" in drawn and "33.3333333333MHz" in drawn
    else:
        assert "power of two" in drawn


# -- theme -----------------------------------------------------------------------------------


def _luminance(colour: str) -> float:
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
def test_number_and_warning_colours_are_legible_as_text(palette: theme.Palette) -> None:
    # Dark theme: number literals and lit bits were #0078FF on slate, 2.3:1 on
    # the input bar — the dimmest text on screen. Light: the amber truncation
    # warning was 3.3:1 at 11px. WCAG AA for text is 4.5:1.
    for ground in (palette.background, palette.surface):
        assert _contrast(palette.syn_number, ground) >= 4.5
        assert _contrast(palette.bit_on, ground) >= 4.5  # the lit digits of the BIN lane
        assert _contrast(palette.warn, ground) >= 4.5
        assert _contrast(palette.syn_operator, ground) >= 4.5


def test_lit_cells_still_stand_out_from_unlit_ones() -> None:
    for palette in (LIGHT, DARK):
        assert _contrast(palette.bit_on, palette.bit_off) >= 3.0
