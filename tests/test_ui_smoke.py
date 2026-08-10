"""pytest-qt smoke tests for the main window (offscreen-safe)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFontMetrics  # noqa: E402

from radix.engine.values import Value  # noqa: E402
from radix.session import Session  # noqa: E402
from radix.ui_qt.main_window import MainWindow  # noqa: E402
from radix.ui_qt.theme import LIGHT  # noqa: E402


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    win = MainWindow(Session(), LIGHT)
    qtbot.addWidget(win)
    return win


@pytest.fixture
def styled_window(qtbot, qapp):  # type: ignore[no-untyped-def]
    """A window carrying the real application stylesheet, like `app.run_gui`.

    Every other test here runs bare, where the default system font is small
    enough that the panels always fit. Layout defects only show up at the
    stylesheet's actual type sizes, so anything asserting geometry has to pay
    for the real thing — that gap is why a full green suite still shipped a
    bit grid with the row below it painted across it.
    """
    from PySide6.QtWidgets import QApplication

    from radix.ui_qt import theme

    mono, label = theme.load_bundled_font()
    previous_sheet = qapp.styleSheet()
    previous_style = qapp.style().objectName()
    qapp.setStyle("Fusion")  # widget metrics differ per style; match run_gui
    qapp.setStyleSheet(theme.stylesheet(LIGHT, mono, label))
    win = MainWindow(Session(), LIGHT)
    qtbot.addWidget(win)
    yield win
    qapp.setStyleSheet(previous_sheet)
    QApplication.setStyle(previous_style)


def _submit(qtbot, window: MainWindow, text: str) -> None:  # type: ignore[no-untyped-def]
    window.input.setText(text)
    qtbot.keyClick(window.input, Qt.Key.Key_Return)


def test_evaluate_appends_history_and_updates_panel(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF << 2")
    assert window.model.entries[-1].result == "1020"
    assert window.intview.active
    assert window.intview.rows["HEX"][1].text().endswith("03FC")


def test_float_result_greys_panel_by_default(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "2.5")
    assert window.intview.float_mode is None
    assert not window.intview.active
    assert "EXP" not in window.intview.rows  # float-only lanes hidden by default


def test_float_result_shows_ieee754_view(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.session.show_float_view = True
    _submit(qtbot, window, "2.5")
    assert not window.intview.active  # no integer scratch
    assert window.intview.float_mode is not None
    assert window.intview.rows["HEX"][1].text() == "0x4020_0000"  # float32: default word size
    assert window.intview.rows["EXP"][0].text() == "EXP"
    assert window.intview.rows["EXP"][1].text() == "128 - bias 127 = 2^1"
    assert "SGN" in window.intview.rows
    # 8/16-bit words have no float format: panel greys as before.
    window.session.word_size = 8
    window._update_preview()
    _submit(qtbot, window, "sin(1)")
    assert window.intview.float_mode is None
    assert not window.intview.active
    assert "EXP" not in window.intview.rows  # float-only lanes gone
    assert "DEC" in window.intview.rows  # integer lanes restored


def test_float_result_shows_float64_at_64bit_word_size(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.session.show_float_view = True
    window.session.word_size = 64
    window._update_preview()
    _submit(qtbot, window, "2.5")
    assert window.intview.float_mode is not None
    assert window.intview.rows["HEX"][1].text() == "0x4004_0000_0000_0000"
    assert window.intview.rows["EXP"][1].text() == "1024 - bias 1023 = 2^1"
    assert window.intview.grid_widget.bands is not None
    assert window.intview.grid_widget.bands.low_width == 52


def test_float_view_is_read_only(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.session.show_float_view = True
    _submit(qtbot, window, "0xFF")
    _submit(qtbot, window, "2.5")
    assert window.intview.float_mode is not None
    grid = window.intview.grid_widget
    assert grid.bands is not None and grid.bands.low_width == 23  # float32: default word size
    # Toggling/selecting is disabled in float mode; scratch keeps the last int.
    assert window.intview.scratch == 0xFF


def test_assignment_and_recall(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "x = 0xFF")
    assert window.model.entries[-1].result == "x ← 255"
    _submit(qtbot, window, "x << 2")
    assert window.model.entries[-1].result == "1020"
    qtbot.keyClick(window.input, Qt.Key.Key_Up)
    assert window.input.text() == "x << 2"
    qtbot.keyClick(window.input, Qt.Key.Key_Up)
    assert window.input.text() == "x = 0xFF"


def test_result_readout_shows_placeholder_before_first_result(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    assert window.result_label.text() == "—"
    assert window.result_label.property("dimmed") == "true"


def test_result_readout_tracks_last_evaluated_result(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF << 2")
    assert window.result_label.text() == "1020"
    assert window.result_label.property("dimmed") == "false"
    _submit(qtbot, window, "x = 5")
    assert window.result_label.text() == "x ← 5"


def test_result_readout_reformats_on_base_change(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF << 2")
    assert window.result_label.text() == "1020"
    window._cycle_int_base()  # dec -> hex
    assert window.result_label.text() == window.model.entries[-1].result
    assert window.result_label.text() != "1020"


def test_result_readout_seeded_from_persisted_history(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from radix.history.store import HistoryStore

    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    store = HistoryStore(tmp_path / "history.jsonl")

    win1 = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win1)
    _submit(qtbot, win1, "x = 0xFF")
    win1.close()

    win2 = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win2)
    assert win2.result_label.text() == "x ← 255"
    assert win2.result_label.property("dimmed") == "false"


def test_variables_and_csrs_persist_across_restart(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from radix.history.store import HistoryStore

    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    store = HistoryStore(tmp_path / "history.jsonl")

    win1 = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win1)
    _submit(qtbot, win1, "csr CTRL = EN[31] ADDR[27:8]")
    _submit(qtbot, win1, "x = CTRL(0x8C01A0F3)")
    win1.close()

    win2 = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win2)
    assert set(win2.session.csrs) == {"CTRL"}
    assert win2.session.variables["x"].number == 0x8C01A0F3
    assert win2.session.variables["x"].csr is not None
    assert win2.session.variables["x"].csr.name == "CTRL"
    assert win2.session.ans is not None
    assert win2.session.ans.number == 0x8C01A0F3


def test_clear_keeps_persisted_variables(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from radix.history.store import HistoryStore

    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    store = HistoryStore(tmp_path / "history.jsonl")

    win1 = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win1)
    _submit(qtbot, win1, "x = 5")
    _submit(qtbot, win1, "clear")  # clears history only — named variables stay
    win1.close()

    win2 = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win2)
    assert set(win2.session.variables) == {"x"}


def test_live_preview_shows_xor_and_result(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.input.setText("2^10")
    window._update_preview()
    assert window.preview.text() == "2 XOR 10 = 8"


def test_preview_is_side_effect_free(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.input.setText("y = 42")
    window._update_preview()
    assert "y" not in window.session.variables
    assert window.session.ans is None


def test_preview_error_underlines_span(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.input.setText("1 + )")
    window._update_preview()
    assert window.preview.property("state") == "error"
    assert window.highlighter.error_span == (4, 5)  # the `)` token
    window.input.setText("1 + 1")
    window._update_preview()
    assert window.preview.property("state") == "ok"
    assert window.highlighter.error_span is None


def test_fix_renders_in_the_register_frame(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "fix(0.7071, 1, 15)")
    assert not window.vizpanel.isVisibleTo(window)  # no second bit bar in TRACE
    intview = window.intview
    assert intview.fixed_view is not None and intview.fixed_view.raw == 0x5A82
    grid = intview.grid_widget
    assert grid.word_size == 16  # the Q word, not the session word size
    assert grid.bands is not None
    assert grid.bands.low_width == 15 and grid.bands.point_bit == 14
    assert intview.rows["HEX"][1].text() == "0x5A82"
    assert intview.rows["Q1.15"][1].text().startswith("0.7071 → 0.70709")
    assert intview.register_caption.text() == "REGISTER · Q1.15"
    assert intview.error_meter.isVisibleTo(intview)
    _submit(qtbot, window, "1 + 1")
    assert intview.fixed_view is None and intview.active
    assert intview.register_caption.text() == "REGISTER"
    assert not intview.error_meter.isVisibleTo(intview)
    # The live preview drives it too, and unfix() returns a real carrying the
    # same payload -- it has to reach REGISTER by the same route.
    window.input.setText("unfix(0x4000, 1, 15)")
    window._update_preview()
    assert window.intview.fixed_view is not None
    assert window.intview.rows["Q1.15"][1].text() == "0.5  (exact)"


def test_fixed_view_is_read_only_and_survives_a_word_size_cycle(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF")
    _submit(qtbot, window, "fix(1.5, 8, 4)")
    intview = window.intview
    assert not intview.active and intview.scratch == 0xFF  # scratch untouched
    assert intview.start_cursor() is False
    grid = intview.grid_widget
    grid.mousePressEvent(_press(grid._cell_rect(4).center()))
    grid.mouseReleaseEvent(_press(grid._cell_rect(4).center()))
    assert intview.scratch == 0xFF  # cells refuse edits in a packed layout
    window._cycle_word_size()
    assert intview.fixed_view is not None and grid.word_size == 12


def test_bit_grid_geometry_unchanged_for_standard_word_sizes(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    # Nibble gaps are now derived per row rather than from the column index, so
    # every session word size has to land exactly where it did before.
    from radix.ui_qt.bit_panel import CELL, GAP, NIBBLE_GAP

    grid = window.intview.grid_widget
    for word_size in (8, 16, 32, 64):
        grid.set_state(0, word_size, True)
        per_row = grid._bits_per_row()
        for bit in range(word_size):
            row, col = divmod(word_size - 1 - bit, per_row)
            assert grid._cell_rect(bit).left() == 4 + col * (CELL + GAP) + col // 4 * NIBBLE_GAP


def test_fixed_view_handles_an_odd_width(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from radix.ui_qt.bit_panel import CELL

    _submit(qtbot, window, "fix(0.1, 2, 3)")
    grid = window.intview.grid_widget
    assert grid.word_size == 5
    # The leading partial group must still get its own cell column and gap.
    assert grid._cell_rect(4).left() < grid._cell_rect(3).left() - CELL
    assert window.intview.rows["HEX"][1].text() == "0x01"


def test_only_result_readout_has_sunken_background(qtbot) -> None:  # type: ignore[no-untyped-def]
    # Only the RESULT readout should stand out with the darker surface_sunken
    # fill -- TRACE/READOUT/REGISTER all match the plain chassis background.
    from radix.ui_qt import theme
    from radix.ui_qt.theme import DARK

    mono, label = theme.load_bundled_font()
    qss = theme.stylesheet(DARK, mono, label)
    result_block = qss.split("QLabel#resultValue {")[1].split("}")[0]
    vizpanel_block = qss.split("QWidget#vizPanel {")[1].split("}")[0]
    intview_block = qss.split("QWidget#intview {")[1].split("}")[0]
    assert "background" in result_block
    assert "background" not in vizpanel_block
    assert "background" not in intview_block


def test_theme_mode_icon_renders_for_every_mode(qtbot) -> None:  # type: ignore[no-untyped-def]
    from radix.ui_qt.theme import THEME_MODES, theme_mode_icon

    for mode in THEME_MODES:
        icon = theme_mode_icon(mode, "#A9B7C6")
        pixmap = icon.pixmap(16, 16)
        assert not pixmap.isNull()


def test_version_shown_in_status_bar_not_title(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from radix import __version__

    assert window.windowTitle() == "Radix"
    assert __version__ not in window.windowTitle()
    assert window.version_label.text() == f"v{__version__}"


def test_zone_captions_have_expected_text(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    assert window.inspector.trace_caption.text() == "TRACE"
    assert window.intview.readout_caption.text() == "READOUT"
    assert window.intview.register_caption.text() == "REGISTER"


def test_trace_caption_visibility_tracks_vizpanel(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from radix.engine.viz import ClockViz

    _submit(qtbot, window, "clkdiv(50M, 115200)")
    assert window.inspector.trace_caption.isVisibleTo(window)
    assert isinstance(window.vizpanel.payload, ClockViz)
    _submit(qtbot, window, "1 + 1")
    assert not window.inspector.trace_caption.isVisibleTo(window)
    # The live preview drives it too.
    window.input.setText("mem(3000, 8)")
    window._update_preview()
    assert window.inspector.trace_caption.isVisibleTo(window)


def test_trace_stays_hidden_for_bit_layout_payloads(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    # Qm.n and IEEE-754 describe a word: REGISTER renders them, TRACE stays out
    # of it rather than drawing the same bits a second time.
    for expr in ("fix(0.7071, 1, 15)", "unfix(0x4000, 1, 15)", "float32(1.5)"):
        _submit(qtbot, window, expr)
        assert not window.inspector.trace_caption.isVisibleTo(window), expr
        assert not window.vizpanel.isVisibleTo(window), expr


def test_trace_caption_hidden_on_launch(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    assert not window.inspector.trace_caption.isVisibleTo(window.inspector)


def test_zone_caption_heights_match_constant(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from radix.ui_qt.zones import ZONE_CAPTION_H

    assert window.inspector.trace_caption.height() == ZONE_CAPTION_H
    assert window.intview.readout_caption.height() == ZONE_CAPTION_H
    assert window.intview.register_caption.height() == ZONE_CAPTION_H


def test_viz_panel_clock_card(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from radix.engine.viz import ClockViz

    _submit(qtbot, window, "clkdiv(50M, 115200)")
    assert window.vizpanel.isVisibleTo(window)
    payload = window.vizpanel.payload
    assert isinstance(payload, ClockViz)
    assert payload.divisor == 434
    _submit(qtbot, window, "period(100M)")
    payload = window.vizpanel.payload
    assert isinstance(payload, ClockViz)
    assert payload.divisor is None and payload.period_text == "10n"


def test_viz_panel_clock_wave_heights(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from radix.ui_qt.viz_panel import LINE_H, WAVE_STRIP_H

    _submit(qtbot, window, "clkdiv(96M, 12M)")  # divisor 8: waveform drawn
    assert window.vizpanel.height() == 8 + 2 * LINE_H + WAVE_STRIP_H + 10
    _submit(qtbot, window, "clkdiv(50M, 115200)")  # divisor 434: text lines only
    assert window.vizpanel.height() == 8 + 2 * LINE_H + 10


def test_viz_panel_mem_card(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from radix.engine.viz import MemViz

    _submit(qtbot, window, "mem(3000, 8)")
    assert window.vizpanel.isVisibleTo(window)
    payload = window.vizpanel.payload
    assert isinstance(payload, MemViz)
    assert payload.addressable == 4096


def test_float32_renders_in_the_register_frame(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "float32(1.5)")
    assert not window.vizpanel.isVisibleTo(window)
    intview = window.intview
    assert intview.float_bits is not None and intview.float_bits.bits == 0x3FC00000
    assert not intview.active  # a packed pattern is read-only, like the FLOAT ON view
    assert intview.rows["HEX"][1].text() == "0x3FC0_0000"
    assert intview.rows["VAL"][1].text() == "1.5"
    assert intview.rows["EXP"][1].text() == "127 - bias 127 = 2^0"
    assert intview.register_caption.text() == "REGISTER · float32"
    grid = intview.grid_widget
    assert grid.word_size == 32 and grid.bands is not None and grid.bands.low_width == 23
    assert not intview.error_meter.isVisibleTo(intview)  # no quantization error here
    _submit(qtbot, window, "float32(1.1)")
    assert "rounded from 1.1" in intview.rows["VAL"][1].text()
    # FLOAT ON/OFF is a display preference; a float32() result is not.
    window._toggle_float_view()
    assert intview.float_bits is not None
    assert intview.register_caption.text() == "REGISTER · float32"


def test_unfloat32_uses_the_payload_width_not_the_word_size(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.session.word_size = 64
    _submit(qtbot, window, "unfloat32(0x3FC00000)")
    assert window.intview.grid_widget.word_size == 32
    assert window.intview.rows["VAL"][1].text() == "1.5"


def _press(pos):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent

    return QMouseEvent(
        QEvent.Type.MouseButtonPress, pos, pos, pos,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )


def _move(widget, pos):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent

    widget.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, pos, pos, pos,
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
    ))


def test_fixed_bit_hover_tooltip(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QPointF

    _submit(qtbot, window, "fix(0.7071, 1, 15)")
    grid = window.intview.grid_widget
    _move(grid, grid._cell_rect(15).center())  # MSB: the two's-complement sign
    assert "sign" in grid.toolTip() and "weight -2^0" in grid.toolTip()
    _move(grid, grid._cell_rect(0).center())
    assert "fraction" in grid.toolTip() and "weight 2^-15" in grid.toolTip()
    # Moving off the cells clears the tooltip.
    _move(grid, QPointF(1, 1))
    assert grid.toolTip() == ""


def test_float_bit_hover_tooltip(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "float32(1.5)")
    grid = window.intview.grid_widget
    _move(grid, grid._cell_rect(31).center())
    assert grid.toolTip() == "bit 31 = 0    sign"
    _move(grid, grid._cell_rect(0).center())
    assert grid.toolTip() == "bit 0 = 0    mantissa"


def test_viz_panel_clock_wave_hover_tooltip(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QPointF

    from radix.ui_qt.viz_panel import LINE_H, WAVE_GAP, WAVE_ROW_H

    _submit(qtbot, window, "clkdiv(96M, 12M)")  # divisor small enough to draw the wave
    panel = window.vizpanel
    payload = panel.payload
    x0, strip_w, half_units = panel._wave_geometry(payload)
    ref_y = 8 + 2 * LINE_H + WAVE_ROW_H // 2
    div_y = 8 + 2 * LINE_H + (WAVE_ROW_H + WAVE_GAP) + WAVE_ROW_H // 2
    _move(panel, QPointF(x0 + 2, ref_y))
    assert panel.toolTip().startswith("reference clock — ")
    _move(panel, QPointF(x0 + 2, div_y))
    assert panel.toolTip().startswith("divided output (")


def test_viz_panel_clock_error_hover_tooltip(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "clkdiv(50M, 115200)")
    panel = window.vizpanel
    payload = panel.payload
    rect = panel._clock_err_rect(payload)
    _move(panel, rect.center())
    tip = panel.toolTip()
    assert "typical UART tolerance" in tip
    assert tip.startswith("ok:") or tip.startswith("warn:") or tip.startswith("bad:")


def test_history_context_actions(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QApplication

    _submit(qtbot, window, "x = 0xFF")
    _submit(qtbot, window, "sin(1)")
    window._history_action("copy_hex", 0)
    assert QApplication.clipboard().text() == "0xFF"
    window._history_action("copy_result", 0)
    assert QApplication.clipboard().text() == "255"  # assignment prefix stripped
    window._history_action("copy_expression", 1)
    assert QApplication.clipboard().text() == "sin(1)"
    window._history_action("recall", 1)
    assert window.input.text() == "sin(1)"
    window._history_action("delete", 0)
    assert len(window.model.entries) == 1
    assert window.model.entries[0].expression == "sin(1)"


def test_history_delete_rewrites_store(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from radix.history.store import HistoryStore

    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings")
    )
    store = HistoryStore(tmp_path / "history.jsonl")
    win = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win)
    _submit(qtbot, win, "1 + 1")
    _submit(qtbot, win, "2 + 2")
    win._history_action("delete", 0)
    remaining = store.load()
    assert [e.expression for e in remaining] == ["2 + 2"]
    assert remaining[0].timestamp > 0


def test_int_history_reformats_across_restart(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from radix.history.store import HistoryStore

    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    store = HistoryStore(tmp_path / "history.jsonl")

    win1 = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win1)
    _submit(qtbot, win1, "0xFF")
    _submit(qtbot, win1, "y = 10")
    win1.close()

    win2 = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win2)
    assert all(e.value is not None for e in win2.model.entries)
    before = [e.result for e in win2.model.entries]
    win2._cycle_int_base()  # dec -> hex
    after = [e.result for e in win2.model.entries]
    assert after != before
    assert after[1].startswith("y ← ")


def test_float_history_reformats_across_restart(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    # Regression: a real result kept its (bit-exact) value across a restart,
    # so cycling notation reformats it in the history panel just like it does
    # in the live session.
    from PySide6.QtCore import QSettings

    from radix.history.store import HistoryStore

    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    store = HistoryStore(tmp_path / "history.jsonl")

    win1 = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win1)
    _submit(qtbot, win1, "73.5k*0.0272")
    win1.close()

    win2 = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win2)
    assert win2.model.entries[0].value is not None
    before = win2.model.entries[0].result
    win2._cycle_notation()  # auto -> sci
    assert win2.model.entries[0].result != before


def test_int_history_survives_delete_rewrite_and_restart(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from radix.history.store import HistoryStore

    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    store = HistoryStore(tmp_path / "history.jsonl")

    win1 = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win1)
    _submit(qtbot, win1, "0xFF")
    _submit(qtbot, win1, "1 + 1")
    win1._history_action("delete", 1)  # delete the "1 + 1" entry, rewriting the store
    win1.close()

    win2 = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win2)
    assert len(win2.model.entries) == 1
    assert win2.model.entries[0].value is not None
    before = win2.model.entries[0].result
    win2._cycle_int_base()
    assert win2.model.entries[0].result != before


def test_history_scrolls_to_bottom_on_first_show(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from radix.history.store import HistoryStore

    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    store = HistoryStore(tmp_path / "history.jsonl")
    for i in range(40):
        store.append(f"{i} + 1", str(i + 1), "", value=Value(i + 1))

    win = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win)
    scrollbar = win.history_view.verticalScrollBar()
    # Item heights (word-wrap) depend on the real, polished viewport width,
    # which isn't final until the window is actually shown.
    win.show()
    qtbot.waitExposed(win)
    assert scrollbar.value() == scrollbar.maximum()


def test_history_stays_pinned_to_bottom_after_late_resize(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from radix.history.store import HistoryStore

    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    store = HistoryStore(tmp_path / "history.jsonl")
    for i in range(40):
        store.append(f"{i} + 1", str(i + 1), "", value=Value(i + 1))

    win = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    scrollbar = win.history_view.verticalScrollBar()
    assert scrollbar.value() == scrollbar.maximum()

    # A window manager can resize the view again after our initial
    # scrollToBottom() (e.g. Wayland settling final geometry a beat after
    # the window is mapped), which used to leave the scrollbar frozen one
    # row short of the new bottom.
    win.resize(win.width(), win.height() - 80)
    qtbot.waitUntil(lambda: scrollbar.value() == scrollbar.maximum(), timeout=1000)


def test_history_resize_does_not_yank_scrolled_up_view(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QAbstractItemView

    from radix.history.store import HistoryStore

    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    store = HistoryStore(tmp_path / "history.jsonl")
    for i in range(40):
        store.append(f"{i} + 1", str(i + 1), "", value=Value(i + 1))

    win = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    scrollbar = win.history_view.verticalScrollBar()
    # Go through the view's own scrollTo (as a real click/wheel/keyboard
    # scroll would), not a bare scrollbar.setValue() — the latter bypasses
    # QAbstractItemView's internal position bookkeeping and its own next
    # layout pass snaps back to the bottom regardless of our fix.
    win.history_view.scrollTo(win.model.index(0), QAbstractItemView.ScrollHint.PositionAtTop)
    assert scrollbar.value() == 0

    win.resize(win.width(), win.height() - 80)
    qtbot.wait(200)
    assert scrollbar.value() == 0


def test_history_no_horizontal_scrollbar_after_resize(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from radix.history.store import HistoryStore

    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    store = HistoryStore(tmp_path / "history.jsonl")
    for i in range(40):
        store.append(f"{i} + 1", str(i + 1), "", value=Value(i + 1))

    win = MainWindow(Session(), LIGHT, store=store)
    qtbot.addWidget(win)
    win.resize(640, 700)
    win.show()
    qtbot.waitExposed(win)
    hbar = win.history_view.horizontalScrollBar()
    assert not hbar.isVisible()

    # QListView.ResizeMode.Fixed (Qt's default) only lays rows out the first
    # time the view is shown; narrowing the window afterwards changes the
    # viewport width without re-syncing existing row rects to it, so a bogus
    # horizontal scrollbar can appear even though no entry's text is
    # anywhere near this wide.
    win.resize(520, 700)  # app's own declared minimum (setMinimumSize)
    assert not hbar.isVisible()


def test_vars_pane_lists_and_inserts(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "x = 0xFF")
    _submit(qtbot, window, "vars")
    assert window.vars_pane.isVisibleTo(window)
    assert not window.history_view.isVisibleTo(window)
    assert window.vars_pane.item(0).text() == "x = 255"
    window._insert_var_name(window.vars_pane.item(0))
    assert window.input.text() == "x"
    qtbot.keyClick(window.input, Qt.Key.Key_Escape)
    assert not window.vars_pane.isVisibleTo(window)
    assert window.history_view.isVisibleTo(window)


def test_vars_pane_honors_display_base(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "x = 0xFF")
    window._toggle_vars()  # Alt+V path
    assert window.vars_pane.isVisibleTo(window)
    window._cycle_int_base()  # dec -> hex
    assert window.vars_pane.item(0).text() == "x = 0xFF"
    window._toggle_vars()
    assert not window.vars_pane.isVisibleTo(window)


def test_del_command(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "x = 1")
    # Preview must be side-effect free.
    window.input.setText("del x")
    window._update_preview()
    assert "delete x" in window.preview.text()
    assert "x" in window.session.variables
    qtbot.keyClick(window.input, Qt.Key.Key_Return)
    assert "x" not in window.session.variables
    # Unknown names error with a span.
    window.input.setText("del nope")
    window._update_preview()
    assert window.preview.property("state") == "error"


def test_help_command_shows_pane(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "help")
    assert window.help_pane.isVisibleTo(window)
    assert "Operators" in window.help_pane.toPlainText()
    qtbot.keyClick(window.input, Qt.Key.Key_Escape)
    assert not window.help_pane.isVisibleTo(window)


def test_completer_pops_and_tab_inserts(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    qtbot.keyClicks(window.input, "cl")
    assert window.completer.active
    names = [
        window.completer.popup.item(i).data(Qt.ItemDataRole.UserRole + 1).name
        for i in range(window.completer.popup.count())
    ]
    assert names == ["clog2", "clkdiv", "clear"]
    qtbot.keyClick(window.input, Qt.Key.Key_Tab)
    assert window.input.text() == "clog2("
    assert not window.completer.active


def test_completer_plain_enter_still_evaluates(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    qtbot.keyClicks(window.input, "1+sqrt")  # popup open on the "sqrt" prefix? no: exact match
    qtbot.keyClicks(window.input, "(9)")
    qtbot.keyClick(window.input, Qt.Key.Key_Return)
    assert window.model.entries[-1].result == "4"


def test_completer_enter_inserts_only_after_navigation(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    qtbot.keyClicks(window.input, "cl")
    qtbot.keyClick(window.input, Qt.Key.Key_Down)  # highlight "clog2"
    qtbot.keyClick(window.input, Qt.Key.Key_Down)  # highlight "clear"
    qtbot.keyClick(window.input, Qt.Key.Key_Return)
    assert window.input.text() == "clear"
    assert not window.model.entries  # nothing was evaluated


def test_completer_ctrl_space_and_escape(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    qtbot.keyClick(window.input, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    assert window.completer.active
    assert window.completer.popup.count() >= 30  # the full list
    qtbot.keyClick(window.input, Qt.Key.Key_Escape)
    assert not window.completer.active
    assert window.history_view.isVisibleTo(window)  # help pane untouched


def test_completer_ignores_recall_and_suffix_positions(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "sin(1) + 2")
    qtbot.keyClick(window.input, Qt.Key.Key_Up)  # recall must not pop completions
    assert window.input.text() == "sin(1) + 2"
    assert not window.completer.active
    window.input.clear()
    qtbot.keyClicks(window.input, "2p")  # SI-suffix territory, not an identifier
    assert not window.completer.active


def test_bit_toggle_updates_scratch(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "8")
    window.intview.toggle_bit(0)
    assert window.intview.scratch == 9
    assert window.intview.rows["DEC"][1].text() == "9"


def test_bit_toggle_writes_input(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "8")
    window.intview.toggle_bit(0)
    assert window.input.text() == "0x9"
    window.intview.toggle_bit(4)
    assert window.input.text() == "0x19"
    window._update_preview()  # the input round-trip must not disturb the scratch
    assert window.intview.scratch == 0x19


def test_changed_bits_diff_against_previous_value(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF")
    assert window.intview.changed == 0  # first value after grey: nothing to diff
    window.input.setText("ans << 1")
    window._update_preview()
    assert window.intview.changed == 0xFF ^ 0x1FE  # bits 0 and 8 flipped


def test_bit_toggle_marks_single_changed_bit(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "8")
    window.intview.toggle_bit(0)
    assert window.intview.changed == 1


def test_bin_lane_highlights_set_bits_but_copies_plain(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.session.word_size = 8
    _submit(qtbot, window, "0b1010")
    bin_text = window.intview.rows["BIN"][1].text()
    assert "<span" in bin_text  # set bits colored, but...
    assert window.intview._copy_texts["BIN"] == "0b0000_1010"  # ...copy is plain text


def test_dec_lane_shows_signed_when_differs(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.session.word_size = 8
    window._update_preview()
    _submit(qtbot, window, "0xFF")
    dec_text = window.intview.rows["DEC"][1].text()
    assert "255" in dec_text
    assert "-1" in dec_text


def test_bit_range_selection_readout_and_to_input(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xABCD")
    window.intview.grid_widget.set_selection((15, 8))
    assert window.intview.slice_label.text() == "[15:8] = 0xAB = 171 (8 bits)"
    window.intview._emit_to_input()
    assert window.input.text() == "0xABCD[15:8]"


def test_bit_range_selection_esc_clears(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xABCD")
    window.intview.grid_widget.set_selection((7, 4))
    qtbot.keyClick(window.input, Qt.Key.Key_Escape)
    assert window.intview.grid_widget.selection is None
    assert window.intview.slice_label.text() == ""


def test_bit_range_drag_selects_without_toggling(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent

    _submit(qtbot, window, "0xFF")
    grid = window.intview.grid_widget
    grid.resize(600, 400)

    def mouse(kind: QEvent.Type, bit: int, buttons: Qt.MouseButton) -> QMouseEvent:
        pos = grid._cell_rect(bit).center()
        return QMouseEvent(
            kind, pos, pos, pos,
            Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier,
        )

    grid.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, 4, Qt.MouseButton.LeftButton))
    grid.mouseMoveEvent(mouse(QEvent.Type.MouseMove, 1, Qt.MouseButton.LeftButton))
    grid.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, 1, Qt.MouseButton.NoButton))
    assert grid.selection == (4, 1)
    assert window.intview.scratch == 0xFF  # a drag never toggles bits
    # A plain click still toggles (and drops the selection).
    grid.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, 0, Qt.MouseButton.LeftButton))
    grid.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, 0, Qt.MouseButton.NoButton))
    assert grid.selection is None
    assert window.intview.scratch == 0xFE


def test_toggling_upper_bit_updates_input(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.session.word_size = 64
    window._update_preview()
    _submit(qtbot, window, "0xFF")
    window.intview.toggle_bit(40)
    expected = 0xFF | (1 << 40)
    assert window.intview.scratch == expected
    assert window.input.text() == f"0x{expected:X}"


def test_word_size_cycle_never_masks_scratch(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF")
    window._cycle_word_size()  # 32 -> 64: display only
    assert window.intview.scratch == 0xFF
    window._cycle_word_size()  # 64 -> 8
    assert window.intview.scratch == 0xFF


def test_copy_result_shortcut(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QApplication

    _submit(qtbot, window, "6*7")
    window._copy_result()
    assert QApplication.clipboard().text() == "42"


def test_status_bar_cycles_word_size(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    assert window.status_items["word"].text() == "32-bit"
    window._cycle_word_size()
    assert window.session.word_size == 64
    assert window.status_items["word"].text() == "64-bit"


def test_word_size_cycling_is_display_only(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFFFF")
    window._cycle_word_size()  # 32 -> 64
    window._cycle_word_size()  # 64 -> 8: shows 0xFF
    assert window.intview.rows["HEX"][1].text() == "0xFF"
    window._cycle_word_size()  # 8 -> 16: upper bits must reappear
    assert window.intview.rows["HEX"][1].text() == "0xFFFF"


def test_result_base_applies_to_history_and_preview(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "1020")
    _submit(qtbot, window, "q = 255")
    _submit(qtbot, window, "sin(1)")
    float_text = window.model.entries[-1].result

    window._cycle_int_base()  # dec -> hex
    assert window.status_items["base"].text() == "HEX"
    assert window.model.entries[-3].result == "0x3FC"
    assert window.model.entries[-2].result == "q ← 0xFF"
    assert window.model.entries[-1].result == float_text  # floats untouched

    window.input.setText("128 + 2")
    window._update_preview()
    assert window.preview.text().endswith("= 0x82")

    window._cycle_int_base()  # hex -> bin
    assert window.model.entries[-3].result == "0b11_1111_1100"
    window._cycle_int_base()  # bin -> dec restores the recorded text
    assert window.status_items["base"].text() == "DEC"
    assert window.model.entries[-3].result == "1020"
    assert window.model.entries[-2].result == "q ← 255"


def test_notation_change_rerenders_history(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "10000000")
    _submit(qtbot, window, "sin(1)")
    float_text = window.model.entries[-1].result

    window._cycle_notation()  # auto -> sci
    assert window.model.entries[-2].result == "1e+7"
    assert window.model.entries[-1].result == "8.41470984808e-1"  # floats too
    window._cycle_notation()  # sci -> eng
    assert window.model.entries[-2].result == "10e+6"
    window._cycle_notation()  # eng -> eng_si
    assert window.model.entries[-2].result == "10M"
    window._cycle_notation()  # eng_si -> auto
    assert window.model.entries[-2].result == "10000000"
    assert window.model.entries[-1].result == float_text


def test_panel_follows_input_live(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.input.setText("0xAB << 4")
    window._update_preview()
    assert window.intview.active
    assert window.intview.rows["HEX"][1].text().endswith("0AB0")  # before Enter

    window.input.setText("sin(1)")
    window._update_preview()
    assert not window.intview.active  # float greys the panel

    window.input.setText("0xAB <<")  # incomplete: panel holds its last state
    window._update_preview()
    assert not window.intview.active

    _submit(qtbot, window, "0xFF")
    window.input.setText("")
    window._update_preview()
    assert window.intview.rows["HEX"][1].text().endswith("00FF")  # falls back to ans


def test_history_click_inspects_without_touching_input(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF")  # row 0
    _submit(qtbot, window, "0x10")  # row 1, becomes ans
    window._inspect_from_view(window.model.index(0))
    assert window.intview.rows["HEX"][1].text().endswith("00FF")  # row 0's value, not ans
    assert window.input.text() == ""
    assert window._inspect_locked is True


def test_history_inspect_lock_survives_empty_preview(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF")  # row 0
    _submit(qtbot, window, "0x10")  # row 1, becomes ans
    window._inspect_from_view(window.model.index(0))
    window.input.setText("")
    window._update_preview()
    assert window.intview.rows["HEX"][1].text().endswith("00FF")  # still the inspected entry


def test_history_typing_clears_inspect_lock(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF")  # row 0
    _submit(qtbot, window, "0x10")  # row 1, becomes ans
    window._inspect_from_view(window.model.index(0))
    window.input.setText("0x1")
    window._update_preview()
    assert window._inspect_locked is False
    window.input.setText("")
    window._update_preview()
    assert window.intview.rows["HEX"][1].text().endswith("0010")  # back to ans


def test_esc_prefers_bit_selection_then_inspect_lock(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF")  # row 0
    _submit(qtbot, window, "0x10")  # row 1, becomes ans
    window._inspect_from_view(window.model.index(0))
    window.intview.grid_widget.set_selection((7, 4))
    qtbot.keyClick(window.input, Qt.Key.Key_Escape)
    assert window.intview.grid_widget.selection is None
    assert window._inspect_locked is True  # first Esc only cleared the bit selection
    qtbot.keyClick(window.input, Qt.Key.Key_Escape)
    assert window._inspect_locked is False
    assert window.intview.rows["HEX"][1].text().endswith("0010")  # falls back to ans


def test_history_click_ignores_disk_loaded_entries(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from radix.ui_qt.history_model import HistoryEntry

    window.model.append(HistoryEntry("1 + 1", "2", value=None))
    before = window.intview.rows["HEX"][1].text()
    window._inspect_from_view(window.model.index(0))
    assert window._inspect_locked is False
    assert window.intview.rows["HEX"][1].text() == before


def test_history_click_selects_row(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF")
    window._inspect_from_view(window.model.index(0))
    assert window.history_view.currentIndex().row() == 0
    assert window.history_view.selectionModel().isSelected(window.model.index(0))


def test_settings_persist_across_windows(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from radix.history.store import HistoryStore

    # Redirect the INI file into the sandbox so the test never touches the
    # user's real settings.
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))

    win1 = MainWindow(Session(), LIGHT, store=HistoryStore(tmp_path / "history.jsonl"))
    qtbot.addWidget(win1)
    win1._cycle_word_size()  # 32 -> 64
    win1._toggle_signed()
    win1._toggle_angle()
    win1._cycle_notation()  # auto -> sci
    win1._cycle_int_base()  # dec -> hex
    win1.resize(640, 700)  # fits the offscreen virtual screen (restore clamps)
    win1.close()

    win2 = MainWindow(Session(), LIGHT, store=HistoryStore(tmp_path / "history.jsonl"))
    qtbot.addWidget(win2)
    assert win2.session.word_size == 64
    assert win2.session.signed is True
    assert win2.session.angle_deg is True
    assert win2.session.notation == "sci"
    assert win2.session.int_base == "hex"
    assert win2.status_items["base"].text() == "HEX"
    assert (win2.width(), win2.height()) == (640, 700)

    win3 = MainWindow(Session(), LIGHT)  # store=None: defaults, settings untouched
    qtbot.addWidget(win3)
    assert win3.session.word_size == 32
    assert win3.session.int_base == "dec"


def test_toggle_inspector_shows_and_hides(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    assert window.inspector.isVisibleTo(window)
    window._toggle_inspector()
    assert not window.inspector.isVisibleTo(window)
    window._toggle_inspector()
    assert window.inspector.isVisibleTo(window)


def test_inspector_visibility_persists_across_windows(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from radix.history.store import HistoryStore

    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))

    win1 = MainWindow(Session(), LIGHT, store=HistoryStore(tmp_path / "history.jsonl"))
    qtbot.addWidget(win1)
    win1._toggle_inspector()  # hide it
    win1.close()

    win2 = MainWindow(Session(), LIGHT, store=HistoryStore(tmp_path / "history.jsonl"))
    qtbot.addWidget(win2)
    assert not win2.inspector.isVisibleTo(win2)

    win3 = MainWindow(Session(), LIGHT)  # store=None: defaults, settings untouched
    qtbot.addWidget(win3)
    assert win3.inspector.isVisibleTo(win3)


def test_theme_mode_cycles_auto_light_dark(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    assert window.theme_mode == "auto"
    window._cycle_theme_mode()
    assert window.theme_mode == "light"
    window._cycle_theme_mode()
    assert window.theme_mode == "dark"
    window._cycle_theme_mode()
    assert window.theme_mode == "auto"


def test_theme_mode_change_invokes_callback(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    calls = []
    window.on_theme_mode_changed = lambda: calls.append(window.theme_mode)
    window._cycle_theme_mode()
    assert calls == ["light"]


def test_theme_mode_persists_across_windows(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from radix.history.store import HistoryStore

    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))

    win1 = MainWindow(Session(), LIGHT, store=HistoryStore(tmp_path / "history.jsonl"))
    qtbot.addWidget(win1)
    win1._cycle_theme_mode()  # auto -> light
    win1._cycle_theme_mode()  # light -> dark
    win1.close()

    win2 = MainWindow(Session(), LIGHT, store=HistoryStore(tmp_path / "history.jsonl"))
    qtbot.addWidget(win2)
    assert win2.theme_mode == "dark"

    win3 = MainWindow(Session(), LIGHT)  # store=None: defaults, settings untouched
    qtbot.addWidget(win3)
    assert win3.theme_mode == "auto"


def test_bit_grid_wraps_to_window_width(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from radix.ui_qt.bit_panel import BYTE_WIDTH

    grid = window.intview.grid_widget
    narrow = BYTE_WIDTH + 12  # fits exactly one byte group per row
    grid.resize(narrow, 100)
    grid.set_state(0, 32, True)
    assert grid._bits_per_row() == 8
    assert grid._rows() == 4
    assert all(grid._cell_rect(b).right() <= narrow for b in range(32))
    wide = 4 * BYTE_WIDTH + 12  # fits all four byte groups on one row
    grid.resize(wide, 100)
    assert grid._bits_per_row() == 32
    assert grid._rows() == 1
    assert all(grid._cell_rect(b).right() <= wide for b in range(32))


def test_empty_rack_shows_hint(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    assert window.channels.channels == []
    assert not window.channels.hint_label.isHidden()
    assert window.channels.hint_label.text() == "nothing pinned -- Alt+P pins the last result"


def test_pin_via_history_context_menu(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF + 1")
    window._history_action("pin", 0)
    assert len(window.channels.channels) == 1
    assert window.channels.channels[0].label == "C1"
    assert window.channels.hint_label.isHidden()


def test_pin_assignment_uses_variable_name(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "x = 5")
    window._history_action("pin", 0)
    assert window.channels.channels[0].label == "x"


def test_repinning_a_name_updates_its_strip(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    # Two strips under one label are indistinguishable in the rack.
    _submit(qtbot, window, "x = 5")
    window._history_action("pin", 0)
    _submit(qtbot, window, "x = 9")
    window._history_action("pin", 1)
    assert [c.label for c in window.channels.channels] == ["x"]
    assert window.channels.channels[0].text == "9"


def test_channel_restore_tolerates_a_stale_ref_index(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    # A ref pointing past the restored channels used to raise IndexError, which
    # MainWindow's suppress() does not cover — the app then failed to start.
    window.channels.restore(
        {"ref": 3, "channels": []}, window.session.format_value, window.session.word_size
    )
    assert window.channels.ref_index is None
    window._on_ref_changed()


def test_channel_restore_skips_corrupt_entries(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.channels.restore(
        {
            "ref": 0,
            "channels": [
                {"label": "C1", "kind": "int", "int": 255},
                {"label": "C2", "kind": "int", "int": "not an int"},
            ],
        },
        window.session.format_value,
        window.session.word_size,
    )
    assert [c.label for c in window.channels.channels] == ["C1"]
    assert window.channels.ref_index == 0


def test_wide_int_result_reaches_history_and_readout(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    # This used to raise out of _evaluate mid-way: the value was committed, but
    # no history entry, result label or toast ever appeared — a silent no-op.
    _submit(qtbot, window, "2**20000")
    assert window.model.entries[-1].result == "3.98027684034e+6020"
    assert window.result_label.text() == "3.98027684034e+6020"
    assert window.input.text() == ""


def test_out_of_range_result_shows_an_error(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.input.setText("exp(2**20000)")
    window._update_preview()
    assert window.preview.text() == "result is out of range"
    assert window.preview.property("state") == "error"


def test_alt_p_pins_last_result(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    assert window.session.ans is None
    window._pin_last_result()
    assert window.channels.channels == []
    assert window.preview.text() == "nothing to pin"

    _submit(qtbot, window, "3 + 4")
    window._pin_last_result()
    assert len(window.channels.channels) == 1
    assert window.channels.channels[0].label == "C1"
    assert window.preview.text() == "pinned C1"


def test_channel_rack_caps_at_max_channels(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from radix.engine.values import Value

    for i in range(8):
        window._pin_value(Value(i), None)
    assert len(window.channels.channels) == 8
    window._pin_value(Value(99), None)
    assert len(window.channels.channels) == 8
    assert window.preview.text() == "pinned rack full -- unpin one"


def test_base_cycle_reformats_pinned_channel(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from radix.engine.values import Value

    window._pin_value(Value(255), None)
    before = window.channels.channels[0].text
    window._cycle_int_base()  # dec -> hex
    after = window.channels.channels[0].text
    assert before != after


def test_channel_to_input_inserts_masked_hex(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from radix.engine.values import Value

    window._pin_value(Value(255), None)
    strip = window.channels._strips[0]
    strip._send_to_input()
    assert window.input.text() == "0xFF"


def test_channel_strip_click_arms_and_disarms_ref(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF")
    window._pin_last_result()  # int channel "C1"
    strip = window.channels._strips[0]
    strip.clicked.emit()
    assert window.channels.ref_index == 0
    strip.clicked.emit()
    assert window.channels.ref_index is None


def test_ref_diff_does_not_reach_bit_grid(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF")
    window._pin_last_result()
    window.channels._toggle_ref(0)
    _submit(qtbot, window, "0xF0")
    # The REF-vs text is presentation only -- the grid keeps outlining the
    # vs-previous diff exactly as it did before REF existed.
    mask = (1 << window.session.word_size) - 1
    assert window.intview.changed == 0xFF ^ 0xF0
    assert window.intview.grid_widget.changed == window.intview.changed & mask


def test_ref_channel_shows_xor_readout(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF")
    window._pin_last_result()
    window.channels._toggle_ref(0)
    _submit(qtbot, window, "0xF0")
    xor = 0xF0 ^ 0xFF
    strip = window.channels._strips[0]
    assert strip.xor_label.text() == f"XOR 0x{xor:X}"
    assert strip.xor_label.isVisibleTo(window)
    assert strip.diff_strip.isVisibleTo(window)


def test_ref_disarm_hides_the_xor_readout(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF")
    window._pin_last_result()
    window.channels._toggle_ref(0)
    _submit(qtbot, window, "0xF0")
    window.channels._toggle_ref(0)  # disarm
    _submit(qtbot, window, "0x0F")
    strip = window.channels._strips[0]
    assert not strip.xor_label.isVisibleTo(window)
    assert not strip.diff_strip.isVisibleTo(window)


def test_ref_extras_hidden_for_float_live_value(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF")
    window._pin_last_result()
    window.channels._toggle_ref(0)
    _submit(qtbot, window, "sin(1)")  # panel's live value is now a float
    strip = window.channels._strips[0]
    assert not strip.xor_label.isVisibleTo(window)
    assert not strip.diff_strip.isVisibleTo(window)


def test_ref_survives_persistence(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from radix.history.store import HistoryStore

    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))

    win1 = MainWindow(Session(), LIGHT, store=HistoryStore(tmp_path / "history.jsonl"))
    qtbot.addWidget(win1)
    _submit(qtbot, win1, "0xFF")
    win1._pin_last_result()  # int channel "C1"
    win1.channels._toggle_ref(0)
    win1.close()

    win2 = MainWindow(Session(), LIGHT, store=HistoryStore(tmp_path / "history.jsonl"))
    qtbot.addWidget(win2)
    assert win2.channels.ref_index == 0
    strip = win2.channels._strips[0]
    assert strip.is_ref and strip.ref_tag.isVisibleTo(strip)


def test_unpin_frees_slot(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from radix.engine.values import Value

    window._pin_value(Value(1), None)
    window._pin_value(Value(2), None)
    assert len(window.channels.channels) == 2
    window.channels.unpin(0)
    assert len(window.channels.channels) == 1
    assert window.channels.channels[0].label == "C2"  # not renumbered


def test_channels_persist_across_windows(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from radix.history.store import HistoryStore

    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))

    win1 = MainWindow(Session(), LIGHT, store=HistoryStore(tmp_path / "history.jsonl"))
    qtbot.addWidget(win1)
    _submit(qtbot, win1, "0xFF + 1")
    win1._pin_last_result()  # int channel "C1"
    _submit(qtbot, win1, "sin(1)")
    win1._pin_last_result()  # text-only float channel "C2"
    assert len(win1.channels.channels) == 2
    win1.close()

    win2 = MainWindow(Session(), LIGHT, store=HistoryStore(tmp_path / "history.jsonl"))
    qtbot.addWidget(win2)
    assert len(win2.channels.channels) == 2
    int_chan = win2.channels.channels[0]
    text_chan = win2.channels.channels[1]
    assert int_chan.label == "C1"
    assert int_chan.value is not None
    assert int_chan.value.number == 256
    assert text_chan.label == "C2"
    assert text_chan.value is None
    assert text_chan.text == win1.channels.channels[1].text
    # A restored int channel reformats on a subsequent base cycle.
    before = win2.channels.channels[0].text
    win2._cycle_int_base()
    assert win2.channels.channels[0].text != before

    # A fresh settings file with no prior "channels" key constructs an empty rack.
    empty_settings = tmp_path / "empty"
    empty_settings.mkdir()
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(empty_settings))
    win3 = MainWindow(Session(), LIGHT, store=HistoryStore(tmp_path / "history3.jsonl"))
    qtbot.addWidget(win3)
    assert win3.channels.channels == []


def test_corrupt_channels_blob_falls_back_to_empty_rack(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings

    from radix.history.store import HistoryStore
    from radix.ui_qt.settings import app_settings

    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    # Valid JSON, but a channel entry missing its required "kind" key -- the
    # kind of corruption a hand-edited or truncated settings file could
    # produce. restore() must reject this atomically, not partially apply it.
    app_settings().setValue("channels", '{"channels": [{"label": "C1"}]}')

    window = MainWindow(Session(), LIGHT, store=HistoryStore(tmp_path / "history.jsonl"))
    qtbot.addWidget(window)
    assert window.channels.channels == []


def test_ctrl_b_f_move_cursor_by_char(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.input.setText("12345")
    qtbot.keyClick(window.input, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyClick(window.input, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
    assert window.input.textCursor().position() == 3
    qtbot.keyClick(window.input, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert window.input.textCursor().position() == 4


def test_ctrl_e_moves_to_end_of_line(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.input.setText("12345")
    cursor = window.input.textCursor()
    cursor.movePosition(cursor.MoveOperation.Start)
    window.input.setTextCursor(cursor)
    qtbot.keyClick(window.input, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    assert window.input.textCursor().position() == len("12345")


def test_ctrl_d_h_delete_char_forward_and_backward(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.input.setText("12345")
    cursor = window.input.textCursor()
    cursor.setPosition(2)
    window.input.setTextCursor(cursor)
    qtbot.keyClick(window.input, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert window.input.text() == "1245"
    qtbot.keyClick(window.input, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier)
    assert window.input.text() == "145"


def test_ctrl_w_deletes_word_backward(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.input.setText("12 + 34")
    qtbot.keyClick(window.input, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier)
    assert window.input.text() == "12 + "


def test_alt_b_f_move_cursor_by_word(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window.input.setText("12 + 34")
    qtbot.keyClick(window.input, Qt.Key.Key_B, Qt.KeyboardModifier.AltModifier)
    assert window.input.textCursor().position() == 5  # start of "34"
    qtbot.keyClick(window.input, Qt.Key.Key_B, Qt.KeyboardModifier.AltModifier)
    assert window.input.textCursor().position() == 3  # start of "+"
    qtbot.keyClick(window.input, Qt.Key.Key_F, Qt.KeyboardModifier.AltModifier)
    assert window.input.textCursor().position() == 5


def test_int_base_and_float_view_shortcuts_use_alt_shift(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    # Alt+B/Alt+F were reassigned to bash-style word-jump in the input field,
    # so the app-level toggles moved to Alt+Shift+B/F.
    shortcuts = {action.shortcut().toString() for action in window.actions()}
    assert "Alt+Shift+B" in shortcuts
    assert "Alt+Shift+F" in shortcuts
    assert "Alt+B" not in shortcuts
    assert "Alt+F" not in shortcuts


def _define_ctrl_csr(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "csr CTRL = EN[31] IRQ[30:28] ADDR[27:8] CMD[7:0]")


def test_register_csr_shows_grid_overlay_matching_fields(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from radix.ui_qt.bit_panel import FIELD_H

    grid = window.intview.grid_widget
    no_csr_rows = grid._rows()
    no_csr_min_h = grid.minimumHeight()

    _define_ctrl_csr(qtbot, window)
    _submit(qtbot, window, "CTRL(0x8C01A0F3)")

    assert grid.named_fields == (
        ("EN", 31, 31),
        ("IRQ", 30, 28),
        ("ADDR", 27, 8),
        ("CMD", 7, 0),
    )
    rows = grid._rows()
    assert rows == no_csr_rows  # same word size -> same row count
    assert grid.minimumHeight() == no_csr_min_h + rows * FIELD_H


def test_register_csr_field_table_visible_with_values(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _define_ctrl_csr(qtbot, window)
    _submit(qtbot, window, "CTRL(0x8C01A0F3)")

    assert window.intview.field_table.isVisibleTo(window)
    # Entries are glued with &nbsp; so a wrap can only fall between fields,
    # never between a name and its bracket; normalise that back for reading.
    text = window.intview.field_table.text().replace("&nbsp;", " ")
    assert "EN" in text
    assert "CMD" in text
    assert "0xF3" in text  # CMD = 0xF3, matching decode_note's own formatting
    assert "</a> [31] = 1" in text  # single-bit field: collapsed range, not [31:31]
    assert "[31:31]" not in text


def test_register_csr_field_table_updates_on_bit_toggle(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _define_ctrl_csr(qtbot, window)
    _submit(qtbot, window, "CTRL(0x8C01A0F3)")
    assert "0xF3" in window.intview.field_table.text()

    window.intview.toggle_bit(0)  # inside CMD[7:0]: 0xF3 -> 0xF2
    assert "0xF2" in window.intview.field_table.text()
    assert "0xF3" not in window.intview.field_table.text()


def test_register_csr_field_link_selects_range(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _define_ctrl_csr(qtbot, window)
    _submit(qtbot, window, "CTRL(0x8C01A0F3)")

    window.intview._on_field_link("CMD")
    assert window.intview.grid_widget.selection == (7, 0)
    assert window.intview.slice_label.text().startswith("[7:0]")


def test_register_csr_survives_word_size_cycle(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _define_ctrl_csr(qtbot, window)
    _submit(qtbot, window, "CTRL(0x8C01A0F3)")

    window.session.cycle_word_size()  # 32 -> 64
    window._after_setting_change()
    assert window.intview.grid_widget.named_fields is not None  # overlay survives

    window.session.cycle_word_size()  # 64 -> 8: clips the csr's top field (EN, bit 31)
    window._after_setting_change()
    assert window.intview.grid_widget.named_fields is not None  # overlay still not wiped
    assert window.intview.grid_widget._field_index_of(7) == 3  # CMD (top byte) still active
    clipped = window.intview.field_table.text().replace("&nbsp;", " ")
    assert "= -" in clipped  # EN reported as clipped


def test_register_csr_cleared_by_plain_number(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _define_ctrl_csr(qtbot, window)
    _submit(qtbot, window, "CTRL(0x8C01A0F3)")
    assert window.intview.grid_widget.named_fields is not None

    _submit(qtbot, window, "1 + 1")
    assert window.intview.grid_widget.named_fields is None
    assert not window.intview.field_table.isVisibleTo(window)


def test_csr_command_toasts_and_refreshes_vars_pane(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _define_ctrl_csr(qtbot, window)
    assert "CTRL" in window.preview.text()
    window._show_vars()
    texts = [window.vars_pane.item(i).text() for i in range(window.vars_pane.count())]
    assert any("CTRL" in t for t in texts)


def test_bare_csr_command_shows_vars_pane(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _define_ctrl_csr(qtbot, window)
    _submit(qtbot, window, "csr")
    assert window.vars_pane.isVisibleTo(window)


def test_vars_pane_csr_row_click_inserts_call_paren(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _define_ctrl_csr(qtbot, window)
    window._show_vars()
    item = next(
        window.vars_pane.item(i)
        for i in range(window.vars_pane.count())
        if "CTRL" in window.vars_pane.item(i).text()
    )
    window._insert_var_name(item)
    assert window.input.text() == "CTRL("


def test_register_csr_cells_stay_clickable_and_draggable(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    # Named-fields mode is explicitly NOT read-only, unlike float mode: a
    # click still toggles bits and a drag still selects a range.
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent

    _define_ctrl_csr(qtbot, window)
    _submit(qtbot, window, "CTRL(0x8C01A0F3)")
    grid = window.intview.grid_widget
    grid.resize(600, 400)
    assert grid.named_fields is not None

    def mouse(kind: QEvent.Type, bit: int, buttons: Qt.MouseButton) -> QMouseEvent:
        pos = grid._cell_rect(bit).center()
        return QMouseEvent(
            kind, pos, pos, pos,
            Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier,
        )

    grid.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, 4, Qt.MouseButton.LeftButton))
    grid.mouseMoveEvent(mouse(QEvent.Type.MouseMove, 1, Qt.MouseButton.LeftButton))
    grid.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, 1, Qt.MouseButton.NoButton))
    assert grid.selection == (4, 1)  # drag-select still works

    before = window.intview.scratch
    grid.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, 0, Qt.MouseButton.LeftButton))
    grid.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, 0, Qt.MouseButton.NoButton))
    assert window.intview.scratch == before ^ 1  # plain click still toggles


# -- inspector layout: never squeeze, scroll instead ---------------------------
#
# These assert widget geometry rather than constants: the failure they guard
# against was Qt shrinking the integer panel past its minimum until `pin
# result` painted on top of the bit grid and the wrapped BIN lane was clipped.
# Every check derives from the widgets themselves, so they stay honest if the
# panel's contents change.


def _settle(qtbot, window: MainWindow, size: tuple[int, int], word_size: int) -> None:  # type: ignore[no-untyped-def]
    """Drive the window to a steady state at `size` showing a `word_size` word.

    A word-size change resizes the bit grid, which posts a LayoutRequest that
    the inspector's scroll host forwards to the window layout — so the geometry
    these tests read is only final once those posted events have been
    delivered. Spin the loop until it stops moving instead of guessing a delay.
    """
    from PySide6.QtWidgets import QApplication

    window.resize(*size)
    window.show()
    qtbot.waitExposed(window)
    _submit(qtbot, window, "0xDEADBEEFCAFEBABE")
    while window.session.word_size != word_size:
        window._cycle_word_size()
    previous = None
    for _ in range(10):
        QApplication.processEvents()
        current = window.intview.grid_widget.geometry()
        if current == previous:
            return
        previous = current
    raise AssertionError("inspector layout never settled")


@pytest.mark.parametrize("size", [(520, 600), (600, 800), (640, 880), (900, 700)])
@pytest.mark.parametrize("word_size", [8, 32, 64])
def test_the_zone_below_never_overlaps_the_bit_grid(  # type: ignore[no-untyped-def]
    qtbot, styled_window: MainWindow, size: tuple[int, int], word_size: int
) -> None:
    """A squeezed inspector used to paint the row under the grid across it.

    The PINNED caption is the first always-visible thing below the grid, so it
    is what a squeeze would collide with now that the actions row holds only
    conditional widgets.
    """
    _settle(qtbot, styled_window, size, word_size)
    inspector = styled_window.inspector
    grid = styled_window.intview.grid_widget
    caption = inspector.channels_caption
    grid_bottom = grid.mapTo(inspector, grid.rect().bottomLeft()).y()
    caption_top = caption.mapTo(inspector, caption.rect().topLeft()).y()
    assert caption_top >= grid_bottom, (
        f"{size} at {word_size}-bit: the PINNED zone overlaps the bit grid by "
        f"{grid_bottom - caption_top}px"
    )


@pytest.mark.parametrize("word_size", [8, 16, 32, 64])
def test_the_row_below_the_grid_collapses_when_it_has_nothing_to_say(  # type: ignore[no-untyped-def]
    qtbot, styled_window: MainWindow, word_size: int
) -> None:
    """Both of that row's occupants are conditional, so idle it is pure margin.

    An empty-but-visible label used to reserve a full text line there at every
    word size, pushing PINNED down for no reason.
    """
    from PySide6.QtWidgets import QApplication

    _settle(qtbot, styled_window, (900, 700), word_size)
    intview = styled_window.intview
    actions = intview.layout().itemAt(intview.layout().count() - 1).layout()
    assert not intview.slice_label.isVisibleTo(intview)
    assert not intview.error_meter.isVisibleTo(intview)
    assert actions.geometry().height() == actions.contentsMargins().bottom()
    # ...and it comes back for the one thing it is there to show.
    intview.grid_widget.set_selection((3, 0))
    QApplication.processEvents()
    assert intview.slice_label.isVisibleTo(intview)
    assert actions.geometry().height() > actions.contentsMargins().bottom()


@pytest.mark.parametrize("size", [(520, 600), (640, 880)])
@pytest.mark.parametrize("word_size", [32, 64])
def test_bit_grid_shows_every_row_it_reports(  # type: ignore[no-untyped-def]
    qtbot, styled_window: MainWindow, size: tuple[int, int], word_size: int
) -> None:
    _settle(qtbot, styled_window, size, word_size)
    grid = styled_window.intview.grid_widget
    assert grid.height() >= grid.minimumHeight()  # all wrapped rows drawable


@pytest.mark.parametrize("size", [(520, 600), (640, 880)])
@pytest.mark.parametrize("word_size", [32, 64])
def test_wrapped_lanes_are_not_clipped(  # type: ignore[no-untyped-def]
    qtbot, styled_window: MainWindow, size: tuple[int, int], word_size: int
) -> None:
    """BIN wraps to four lines at 64-bit; the row has to grow to match."""
    _settle(qtbot, styled_window, size, word_size)
    for name, lane in styled_window.intview.rows.items():
        label = lane[1]
        assert label.height() >= label.heightForWidth(label.width()), (
            f"{name} lane clipped at {size} / {word_size}-bit"
        )


def test_inspector_scrolls_when_the_window_is_too_short(qtbot, styled_window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _settle(qtbot, styled_window, (520, 600), 64)
    scroll = styled_window.inspector_scroll
    assert scroll.verticalScrollBar().maximum() > 0  # reachable by scrolling
    assert styled_window.intview.height() >= styled_window.intview.minimumSizeHint().height()


@pytest.mark.parametrize("size", [(520, 600), (600, 800), (640, 880)])
def test_integer_panel_is_never_squeezed_below_its_minimum(  # type: ignore[no-untyped-def]
    qtbot, styled_window: MainWindow, size: tuple[int, int]
) -> None:
    """The invariant behind every overlap: the panel gets the height it asks for.

    Deliberately not asserting "no scrollbar at the default size" — whether the
    default fits depends on font DPI and widget style, so that would be a flaky
    proxy for this, which is the property that actually has to hold.
    """
    _settle(qtbot, styled_window, size, 64)
    intview = styled_window.intview
    assert intview.height() >= intview.minimumSizeHint().height()


# -- toasts are readable ---------------------------------------------------------


def test_toast_shows_on_the_preview_line_in_full(qtbot, styled_window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    """The status bar left the CSR confirmation ~50px; it rendered as `csr`."""
    styled_window.show()
    qtbot.waitExposed(styled_window)
    _submit(qtbot, styled_window, "csr CTRL = EN[31] IRQ[30:28] ADDR[27:8] CMD[7:0]")
    preview = styled_window.preview
    assert preview.text() == "csr CTRL = EN[31] IRQ[30:28] ADDR[27:8] CMD[7:0]"
    needed = preview.fontMetrics().horizontalAdvance(preview.text())
    assert needed <= preview.width(), f"toast needs {needed}px, has {preview.width()}px"


def test_toast_is_styled_apart_from_preview_and_error(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "x = 1")
    assert window.preview.property("state") == "ok"
    _submit(qtbot, window, "del x")
    assert window.preview.property("state") == "toast"


def test_toast_survives_the_debounced_preview_after_input_clears(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    """Commands clear the input, which schedules a preview that would erase it."""
    _submit(qtbot, window, "x = 1")
    _submit(qtbot, window, "del x")
    window._update_preview()  # what the debounce timer fires on an empty line
    assert window.preview.text() == "deleted x"


def test_typing_replaces_a_toast(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "x = 1")
    _submit(qtbot, window, "del x")
    window.input.setText("1 + 2")
    window._update_preview()
    assert window.preview.text() == "1 + 2 = 3"
    assert window.preview.property("state") == "ok"


# -- help and vars get the window; the input keeps driving them -------------------


def test_help_takes_the_inspector_space_and_gives_it_back(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    assert window.inspector.isVisibleTo(window)
    window._show_help()
    assert not window.inspector.isVisibleTo(window)
    window._hide_help()
    assert window.inspector.isVisibleTo(window)


def test_help_does_not_reopen_an_inspector_the_user_closed(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window._toggle_inspector()  # user hides it deliberately
    assert not window.inspector.isVisibleTo(window)
    window._show_help()
    window._hide_help()
    assert not window.inspector.isVisibleTo(window)  # stays as the user left it


def test_alt_i_while_help_is_showing_takes_over(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window._show_help()
    window._toggle_inspector()  # explicitly ask for it back over the help pane
    assert window.inspector.isVisibleTo(window)
    window._hide_help()
    assert window.inspector.isVisibleTo(window)  # not re-hidden by pane arbitration


def test_scroll_keys_drive_the_help_pane_not_history_recall(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    """The input keeps focus, so help had no keyboard scrolling at all."""
    for text in ("1+1", "2+2"):
        _submit(qtbot, window, text)
    window.resize(640, 880)
    window.show()
    qtbot.waitExposed(window)
    window._show_help()
    qtbot.wait(1)
    scrollbar = window.help_pane.verticalScrollBar()
    assert scrollbar.maximum() > 0  # taller than the pane, so scrolling matters
    qtbot.keyClick(window.input, Qt.Key.Key_PageDown)
    assert scrollbar.value() > 0
    assert window.input.text() == ""  # not swallowed into history recall


def test_scroll_keys_still_recall_history_on_the_history_pane(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "1+1")
    qtbot.keyClick(window.input, Qt.Key.Key_Up)
    assert window.input.text() == "1+1"


# -- controls that cannot act say so ---------------------------------------------


def test_copy_buttons_follow_the_lanes_they_copy(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    """Copy works in float view (there are lanes) but not on an empty panel."""
    first_copy = window.intview._row_widgets[0][2]
    assert not first_copy.isEnabled()
    window._toggle_float_view()
    _submit(qtbot, window, "2.5")
    assert window.intview.float_mode is not None
    assert first_copy.isEnabled()


# -- long results stay reachable ---------------------------------------------------


def test_long_result_is_available_in_full_via_tooltip(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    """The row elides at the edge, so the untruncated text needs a home."""
    _submit(qtbot, window, "2**200")
    tooltip = window.model.data(window.model.index(0), Qt.ItemDataRole.ToolTipRole)
    assert str(2**200) in tooltip
    assert "2**200" in tooltip


# -- status bar: chips readable, tooltips truthful --------------------------------


@pytest.mark.parametrize("size", [(520, 600), (640, 880)])
def test_mode_chips_never_elide_their_own_labels(  # type: ignore[no-untyped-def]
    qtbot, styled_window: MainWindow, size: tuple[int, int]
) -> None:
    """"FLOAT OFF" used to render as "FL…FF" and "unsigned" as "un…ed"."""
    from radix.ui_qt.main_window import CHIP_PAD_H

    styled_window.resize(*size)
    styled_window.show()
    qtbot.waitExposed(styled_window)
    for _ in range(4):  # every mode through every one of its states
        for toggle in (
            styled_window._cycle_word_size,
            styled_window._cycle_notation,
            styled_window._cycle_int_base,
            styled_window._toggle_signed,
            styled_window._toggle_float_view,
            styled_window._toggle_angle,
        ):
            toggle()
        qtbot.wait(1)
        for key, chip in styled_window.status_items.items():
            needed = chip.fontMetrics().horizontalAdvance(chip.text())
            assert needed <= chip.width() - 2 * CHIP_PAD_H, (
                f"{key} chip elides {chip.text()!r} at {size}"
            )


def test_every_chip_tooltip_names_a_shortcut_that_is_bound(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    """The base and float chips advertised Alt+B / Alt+F for two releases."""
    from radix.ui_qt.main_window import MODE_CHIPS

    bound = {action.shortcut().toString() for action in window.actions()}
    for key, shortcut, _description in MODE_CHIPS:
        tooltip = window.status_items[key].toolTip()
        assert shortcut in tooltip, f"{key} tooltip {tooltip!r} omits its shortcut"
        assert shortcut in bound, f"{key} tooltip advertises unbound {shortcut}"


def test_alt_b_and_alt_f_stay_with_the_input_line(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    """They are bash-style word-jump; the mode toggles must not reclaim them."""
    bound = {action.shortcut().toString() for action in window.actions()}
    assert "Alt+B" not in bound
    assert "Alt+F" not in bound


# -- pane identity ------------------------------------------------------------------


def test_pane_caption_names_whatever_the_stack_shows(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    assert window.pane_caption.text() == "HISTORY"
    window._show_vars()
    assert window.pane_caption.text() == "VARIABLES"
    window._show_help()
    assert window.pane_caption.text() == "HELP"
    window._show_help("topic text")
    assert window.pane_caption.text() == "HELP TOPIC"
    window._hide_help()
    assert window.pane_caption.text() == "HISTORY"


def test_short_history_sits_against_the_input(qtbot, styled_window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    """A REPL reads bottom-up; rows floated at the top of a tall empty pane."""
    styled_window.resize(640, 1100)
    styled_window.show()
    qtbot.waitExposed(styled_window)
    for text in ("1+1", "2+2"):
        _submit(qtbot, styled_window, text)
    qtbot.wait(10)
    view = styled_window.history_view
    content = sum(view.sizeHintForRow(row) for row in range(styled_window.model.rowCount()))
    assert view.viewportMargins().top() > 0  # padded down to meet the input
    assert view.viewport().height() >= content  # and still shows every row


def test_history_padding_never_hides_a_row(qtbot, styled_window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    """Bottom-padding must not outlive the height it was computed against.

    A CSR decode adds a three-line row *and* grows the inspector (its field
    table wraps), which shrinks the history pane without resizing the view
    itself. Stale padding then clipped the row with the scrollbar still at
    zero — the content was on screen nowhere and unreachable.
    """
    styled_window.resize(560, 880)
    styled_window.show()
    qtbot.waitExposed(styled_window)
    _submit(qtbot, styled_window, "csr CTRL = EN[31] IRQ[30:28] ADDR[27:8] CMD[7:0]")
    _submit(qtbot, styled_window, "CTRL(0x8C01A0F3)")
    qtbot.wait(20)
    view = styled_window.history_view
    content = sum(view.sizeHintForRow(row) for row in range(styled_window.model.rowCount()))
    reachable = view.viewport().height() + view.verticalScrollBar().maximum()
    assert reachable >= content, (
        f"{content - reachable}px of history is unreachable "
        f"(viewport {view.viewport().height()}, scroll {view.verticalScrollBar().maximum()})"
    )


def test_overflowing_history_gets_no_padding(qtbot, styled_window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    """Once the rows overflow, scrolling behaves exactly as it always did."""
    styled_window.resize(640, 600)
    styled_window.show()
    qtbot.waitExposed(styled_window)
    for i in range(40):
        _submit(qtbot, styled_window, f"{i}+{i}")
    qtbot.wait(10)
    assert styled_window.history_view.viewportMargins().top() == 0
    assert styled_window.history_view.verticalScrollBar().maximum() > 0


def test_overflowing_history_pins_newest_row_to_bottom(qtbot, styled_window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    """Scrolled to the bottom, the newest entry meets the bottom edge.

    Per-item scrolling (Qt's default for a list view) snaps the topmost visible
    row to the top of the viewport, leaving whatever doesn't divide evenly —
    measured at up to 77px, more than a full row — as blank space below the
    newest entry that no amount of scrolling could remove.
    """
    styled_window.resize(640, 820)
    styled_window.show()
    qtbot.waitExposed(styled_window)
    for i in range(40):
        _submit(qtbot, styled_window, f"{i}+{i}")
    qtbot.wait(10)
    view = styled_window.history_view
    assert view.verticalScrollBar().maximum() > 0  # the case this is about
    last = view.visualRect(styled_window.model.index(styled_window.model.rowCount() - 1, 0))
    dead = view.viewport().height() - 1 - last.bottom()
    assert dead <= 1, f"{dead}px of dead space under the newest entry"


# -- pinned rack ---------------------------------------------------------------------


def test_pinning_the_same_value_twice_reuses_the_channel(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    """Eight slots exist to compare values, not to hold four copies of one."""
    _submit(qtbot, window, "0xABCD")
    for _ in range(4):
        window._pin_last_result()
    assert [c.label for c in window.channels.channels] == ["C1"]
    assert window.preview.text() == "already pinned as C1"
    _submit(qtbot, window, "0x1234")
    window._pin_last_result()
    assert [c.label for c in window.channels.channels] == ["C1", "C2"]


# -- csr field table ------------------------------------------------------------------


def test_csr_field_entries_never_wrap_mid_field(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    """A break between "CMD" and "[7:0]" reads as two separate things."""
    _define_ctrl_csr(qtbot, window)
    _submit(qtbot, window, "CTRL(0x8C01A0F3)")
    markup = window.intview.field_table.text()
    for name in ("EN", "IRQ", "ADDR", "CMD"):
        assert f"{name}</a>&nbsp;[" in markup, f"{name} can wrap from its bracket"
    # No breakable space anywhere inside an entry: every plain space left in
    # the markup belongs to an HTML attribute, never to "NAME [msb:lsb] = v".
    assert " [" not in markup
    assert " = " not in markup


# -- keyboard access to the bit grid ---------------------------------------------------


def test_alt_g_cursor_moves_toggles_and_selects(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    """The grid was mouse-only in an app whose contract is keyboard-first."""
    window.show()
    qtbot.waitExposed(window)
    _submit(qtbot, window, "0xF0F0")
    window._toggle_grid_cursor()
    assert window.intview.cursor_bit == 31  # starts on the MSB

    qtbot.keyClick(window.input, Qt.Key.Key_Right)
    assert window.intview.cursor_bit == 30
    qtbot.keyClick(window.input, Qt.Key.Key_Down)
    assert window.intview.cursor_bit == 30 - window.intview.bits_per_row()
    qtbot.keyClick(window.input, Qt.Key.Key_End)
    assert window.intview.cursor_bit == 0

    before = window.intview.scratch
    qtbot.keyClick(window.input, Qt.Key.Key_Space)
    assert window.intview.scratch == before ^ 1
    assert window.input.text() == "0xF0F1"  # edits flow back to the input line

    qtbot.keyClick(window.input, Qt.Key.Key_Home)
    for _ in range(4):
        qtbot.keyClick(window.input, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert window.intview.grid_widget.selection == (31, 27)
    assert "[31:27]" in window.intview.slice_label.text()


def test_grid_cursor_releases_the_arrow_keys_on_escape(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xF0F0")
    window._toggle_grid_cursor()
    qtbot.keyClick(window.input, Qt.Key.Key_Escape)
    assert window.intview.cursor_bit is None
    qtbot.keyClick(window.input, Qt.Key.Key_Up)
    assert window.input.text() == "0xF0F0"  # history recall again


def test_grid_cursor_declines_when_there_is_no_register(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    window._toggle_grid_cursor()  # empty panel
    assert window.intview.cursor_bit is None
    window._toggle_float_view()
    _submit(qtbot, window, "2.5")  # read-only IEEE-754 view
    window._toggle_grid_cursor()
    assert window.intview.cursor_bit is None


def test_grid_cursor_clears_when_the_panel_greys(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xF0F0")
    window._toggle_grid_cursor()
    assert window.intview.cursor_bit is not None
    _submit(qtbot, window, "2.5")  # float result greys the panel
    assert window.intview.cursor_bit is None


# -- the preview line never cuts text silently -------------------------------------


def test_overlong_preview_text_elides_with_a_tooltip(qtbot, styled_window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    styled_window.resize(520, 600)
    styled_window.show()
    qtbot.waitExposed(styled_window)
    styled_window._toast("x" * 300)
    assert styled_window.preview.text().endswith("…")
    assert styled_window.preview.toolTip() == "x" * 300
    needed = styled_window.preview.fontMetrics().horizontalAdvance(styled_window.preview.text())
    assert needed <= styled_window.preview.width()


# -- cold start ----------------------------------------------------------------------


def test_placeholder_fits_the_minimum_window(qtbot, styled_window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    """The old wording ran ~70px past the input's right edge and was just cut."""
    styled_window.resize(520, 600)
    styled_window.show()
    qtbot.waitExposed(styled_window)
    edit = styled_window.input
    needed = edit.fontMetrics().horizontalAdvance(edit.placeholderText())
    assert needed <= edit.viewport().width(), (
        f"placeholder needs {needed}px, input viewport is {edit.viewport().width()}px"
    )


def test_empty_history_pane_shows_worked_examples(qtbot, styled_window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    from radix.ui_qt.history_model import EMPTY_HINT

    styled_window.show()
    qtbot.waitExposed(styled_window)
    qtbot.wait(10)  # let the deferred padding resync actually run
    view = styled_window.history_view
    assert view._is_empty()
    # The hint is painted, so assert the state it paints from plus the room to
    # do it: a zero-height viewport silently skips paintEvent altogether.
    assert view.viewport().height() > 0
    assert view.viewportMargins().top() == 0  # no bottom-padding with no rows
    assert len(EMPTY_HINT) >= 3

    _submit(qtbot, styled_window, "1+1")
    assert not view._is_empty()  # real entries take over


def test_empty_history_hint_fits_the_minimum_window(qtbot, styled_window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    """Both hint columns have to fit, or the descriptions run off the edge."""
    from radix.ui_qt.history_model import EMPTY_HINT, HINT_GAP, _scaled

    styled_window.resize(520, 600)
    styled_window.show()
    qtbot.waitExposed(styled_window)
    view = styled_window.history_view
    example_metrics = view.fontMetrics()
    note_metrics = QFontMetrics(_scaled(view.font(), 0.85))
    column = max(example_metrics.horizontalAdvance(text) for text, _ in EMPTY_HINT)
    widest_note = max(note_metrics.horizontalAdvance(note) for _, note in EMPTY_HINT)
    assert column + HINT_GAP + widest_note <= view.viewport().width()


def test_pinned_strips_share_the_inspector_gutter(qtbot, styled_window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    """The strips ran flush to the window edge while every caption was inset."""
    from radix.ui_qt.channels import RACK_GUTTER

    styled_window.show()
    qtbot.waitExposed(styled_window)
    _submit(qtbot, styled_window, "0xABCD")
    styled_window._pin_last_result()
    qtbot.wait(1)
    margins = styled_window.channels.layout_.contentsMargins()
    assert (margins.left(), margins.right()) == (RACK_GUTTER, RACK_GUTTER)


# -- word-size truncation is never silent --------------------------------------


def test_truncation_note_appears_when_value_outgrows_word(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "2**200")
    assert window.intview.rows["HEX"][1].text() == "0x0000_0000"  # the misleading part
    assert window.intview.trunc_note.isVisibleTo(window.intview)
    assert window.intview.trunc_note.text() == "truncated — low 32 bits of a 201-bit value"


def test_truncation_note_hidden_when_the_value_fits(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xFF << 2")
    assert not window.intview.trunc_note.isVisibleTo(window.intview)


def test_truncation_note_follows_the_word_size(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "0xDEADBEEF")
    assert not window.intview.trunc_note.isVisibleTo(window.intview)  # fits 32 bits
    window._cycle_word_size()  # 32 -> 64: still fits
    assert not window.intview.trunc_note.isVisibleTo(window.intview)
    window._cycle_word_size()  # 64 -> 8: no longer fits
    assert window.intview.trunc_note.isVisibleTo(window.intview)
    assert "low 8 bits of a 32-bit value" in window.intview.trunc_note.text()


def test_truncation_note_hidden_in_float_view(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    """An IEEE-754 pattern is the whole value, never a masked slice of one."""
    _submit(qtbot, window, "2**200")
    assert window.intview.trunc_note.isVisibleTo(window.intview)
    window._toggle_float_view()
    _submit(qtbot, window, "2.5")
    assert window.intview.float_mode is not None
    assert not window.intview.trunc_note.isVisibleTo(window.intview)


def test_truncation_note_hidden_on_the_empty_panel(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _submit(qtbot, window, "2**200")
    assert window.intview.trunc_note.isVisibleTo(window.intview)
    _submit(qtbot, window, "clear")
    assert not window.intview.trunc_note.isVisibleTo(window.intview)


def test_vars_pane_csr_row_right_click_deletes(qtbot, window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    _define_ctrl_csr(qtbot, window)
    assert "CTRL" in window.session.csrs
    window._show_vars()
    item = next(
        window.vars_pane.item(i)
        for i in range(window.vars_pane.count())
        if "CTRL" in window.vars_pane.item(i).text()
    )
    name = item.data(Qt.ItemDataRole.UserRole)
    assert name == "CTRL"
    del window.session.csrs[name]
    window._refresh_vars_pane()
    assert "CTRL" not in window.session.csrs
