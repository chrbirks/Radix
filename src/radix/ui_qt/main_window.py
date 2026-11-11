"""The single-window UI: one column, always.

History/help/vars pane (stretches) / input bar / inspector, stacked
top-to-bottom regardless of window size. Keyboard-first: the input line is
always focused; Up/Down recall history; `help` and `clear` are typed
commands. All math goes through Session — the UI never computes anything
itself.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Callable

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QFont, QFontMetrics, QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractSlider,
    QApplication,
    QFrame,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from radix.engine.errors import CalcError, EvalError, IncompleteError
from radix.engine.formatter import bits_needed, group_digits
from radix.engine.help import general_help_html
from radix.engine.values import Value
from radix.engine.viz import ClockViz, FixedPointViz, FloatBitsViz, MemViz, TimeViz
from radix.history.store import HistoryStore, StoredEntry
from radix.session import INT_BASES, NOTATIONS, WORD_SIZES, Session
from radix.ui_qt.completer import Completer, completions
from radix.ui_qt.highlight import ExprHighlighter
from radix.ui_qt.history_model import (
    HistoryDelegate,
    HistoryEntry,
    HistoryModel,
    HistoryView,
    split_assignment,
)
from radix.ui_qt.input_edit import InputBar
from radix.ui_qt.inspector import Inspector
from radix.ui_qt.settings import app_settings, load_session, load_state, save_session, save_state
from radix.ui_qt.theme import (
    FONT_MICRO,
    LABEL_FAMILY,
    THEME_MODES,
    Palette,
    theme_mode_icon,
)
from radix.ui_qt.zones import WrapAnywhereLabel, ZoneCaption, margin_wrap

PREVIEW_DEBOUNCE_MS = 100
INSPECTOR_MIN_H = 160  # scrolls below this rather than squeezing its contents
PANE_MIN_H = 120  # history/help/vars never collapse to nothing
CHIP_PAD_H = 10  # matches the modeChip QSS horizontal padding
PREVIEW_PAD_H = 12  # matches the QLabel#preview QSS horizontal padding

# (chip key, shortcut, what it controls). One source for the key binding and
# the status-bar tooltip: these were hand-written in two places and drifted, so
# the base and float chips advertised Alt+B / Alt+F long after those keys were
# reassigned to bash-style word-jump in the input line. `test_ui_smoke` asserts
# every shortcut named in a tooltip is really bound.
MODE_CHIPS: tuple[tuple[str, str, str], ...] = (
    ("angle", "Alt+D", "angle unit"),
    ("word", "Alt+W", "word size for bit ops"),
    ("sign", "Alt+S", "signedness: >> is arithmetic when signed, logical when unsigned"),
    ("base", "Alt+Shift+B", "integer result base for history & preview"),
    ("notation", "Alt+N", "result notation"),
    ("float", "Alt+Shift+F", "IEEE-754 breakdown for real results"),
    ("decimal", "Alt+Shift+D", "decimal separator (comma , vs period .)"),
)


class InspectorScroll(QScrollArea):
    """Scroll host that asks for the inspector's natural height.

    A bare QScrollArea reports a tiny sizeHint, so the layout would shrink the
    inspector to a permanent scrolling stub; deferring to the child keeps the
    panel at full size whenever the window has room. What the scroll area buys
    is the floor: below `INSPECTOR_MIN_H` the content scrolls instead of being
    squeezed past its minimum, which is what used to paint the zone below the
    bit grid on top of it at 64-bit word sizes.
    """

    def sizeHint(self) -> QSize:
        inner = self.widget()
        if inner is None:
            return super().sizeHint()
        frame = 2 * self.frameWidth()
        # max(): a word-size change can leave the inspector's minimum above its
        # own hint, and asking for less than the minimum would strand the panel
        # permanently a few pixels scrolled.
        height = max(inner.sizeHint().height(), inner.minimumSizeHint().height())
        return QSize(inner.sizeHint().width() + frame, height + frame)

    def minimumSizeHint(self) -> QSize:
        return QSize(super().minimumSizeHint().width(), INSPECTOR_MIN_H)

    def event(self, event: QEvent) -> bool:
        # A scroll area normally absorbs its child's layout changes — it can
        # always scroll instead. Here the child's height is what we ask the
        # window layout for, so the request has to be forwarded upward or the
        # parent keeps negotiating against a stale hint (e.g. the taller grid
        # after Alt+W switches to a 64-bit word).
        if event.type() == QEvent.Type.LayoutRequest:
            self.updateGeometry()
        return super().event(event)

# One row per shortcut, so the help pane can lay them out as a table that
# wraps (the old hand-aligned two-column block needed 886px of window).
SHORTCUT_SECTIONS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Keyboard shortcuts",
        (
            ("Enter", "evaluate"),
            ("Up / Down", "recall history; the line you were typing comes back"),
            ("Tab", "insert the highlighted completion"),
            ("Ctrl+Space", "open completions"),
            ("PageUp / PageDown", "scroll the history, help or variables pane"),
            ("Shift+PageUp / Shift+PageDown", "scroll the inspector panel"),
            ("Up / Down", "scroll help or variables while one is showing"),
            ("Ctrl+L", "clear the history view (saved history and variables stay)"),
            ("Ctrl+Shift+C", "copy the last result"),
            ("F1 or help", "this help; Esc dismisses"),
            ("Alt+W", "cycle word size"),
            ("Alt+S", "toggle signed / unsigned"),
            ("Alt+D", "toggle deg / rad"),
            ("Alt+N", "cycle notation"),
            ("Alt+Shift+B", "result base (dec / hex / bin)"),
            ("Alt+Shift+D", "decimal separator (comma / period)"),
            ("Alt+Shift+F", "show / hide the float view (READOUT, REGISTER)"),
            ("Alt+V", "variables pane; del <name> removes one"),
            ("Alt+P", "pin the last result as a channel"),
            ("Alt+G", "bit cursor: arrows move, Shift+arrows select, Space toggles"),
            ("Alt+I", "show / hide the inspector panel"),
            ("Alt+T", "always on top"),
            ("Alt+M", "cycle theme (auto / light / dark)"),
        ),
    ),
    (
        "Line editing",
        (
            ("Ctrl+B / Ctrl+F", "move one character back / forward"),
            ("Alt+B / Alt+F", "move one word back / forward"),
            ("Ctrl+E", "end of line"),
            ("Ctrl+W", "delete the word before the cursor"),
            ("Ctrl+D / Ctrl+H", "delete the character after / before the cursor"),
        ),
    ),
)
SHORTCUT_HELP = "\n\n".join(
    title + "\n" + "\n".join(f"  {keys:<30} {action}" for keys, action in rows)
    for title, rows in SHORTCUT_SECTIONS
)


class MainWindow(QMainWindow):
    def __init__(
        self, session: Session, palette: Palette, store: HistoryStore | None = None
    ) -> None:
        super().__init__()
        self.session = session
        self.palette_tokens = palette
        self.store = store  # None = no persistence (tests)
        self.recall_index: int | None = None
        self._inspect_locked = False
        self._toast_active = False
        self._preview_full = " "
        self._pane_hid_inspector = False
        self._help_overview_shown = False
        self._did_initial_show = False
        self._locked_value: Value | None = None  # the entry the inspector is locked on
        self._recall_draft = ""  # what was on the line when Up first left it
        self._panel_real: Value | None = None  # the real the panel shows, for the float view
        self._preview_head = ""  # preview echo: gives way first when the line is short
        self._preview_tail = " "  # ...so this, the result or message, stays whole
        self.theme_mode = "auto"  # "auto" | "light" | "dark"
        self.on_theme_mode_changed: Callable[[], None] | None = None

        self.setWindowTitle("Radix")
        self.setMinimumSize(520, 600)

        root = QWidget()
        root.setObjectName("root")
        self.root_layout = QVBoxLayout(root)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        self.model = HistoryModel()
        self.delegate = HistoryDelegate(palette)
        self.history_view = HistoryView(palette)
        self.history_view.setObjectName("history")
        self.history_view.setModel(self.model)
        self.history_view.setItemDelegate(self.delegate)
        self.history_view.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.history_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.history_view.doubleClicked.connect(self._recall_from_view)
        self.history_view.clicked.connect(self._inspect_from_view)
        self.history_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_view.customContextMenuRequested.connect(self._history_context_menu)
        # Tracks whether the view is "following" the latest entry, so a
        # window-manager-driven resize (see eventFilter) knows whether to
        # re-pin to the bottom afterwards or leave a manually-scrolled-up
        # view alone. Driven by valueChanged (fires only on a real value
        # change) rather than sampled at resize time, since ResizeMode.Adjust
        # can deliver Resize events with a transient, not-yet-settled range.
        self._history_follow_bottom = True
        self.history_view.verticalScrollBar().valueChanged.connect(
            self._on_history_scroll_changed
        )
        # Any change to how many rows there are changes how much bottom-padding
        # the view needs; deferred so the row heights are settled when we ask.
        for signal in (
            self.model.rowsInserted,
            self.model.rowsRemoved,
            self.model.modelReset,
        ):
            signal.connect(lambda *_: QTimer.singleShot(0, self._resync_history_scroll))
        # Row width comes from the viewport at layout time (the delegate
        # draws unwrapped text straight into option.rect, never measuring
        # content) — Fixed (Qt's default) only lays that out once, so a
        # later viewport-width change (the vertical scrollbar popping in as
        # entries accumulate, or a window resize) leaves stale, too-wide
        # rows behind and produces a bogus horizontal scrollbar. Adjust
        # keeps widths synced; AlwaysOff is belt-and-suspenders since this
        # list never legitimately needs horizontal scrolling.
        self.history_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.history_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Per-item scrolling (Qt's default) measures the scrollbar in rows, so
        # scrollToBottom() aligns the *top* of the topmost visible row and
        # leaves the remainder — up to more than a full row — as dead space
        # under the newest entry, unreachable with the scrollbar already at its
        # maximum. Per-pixel puts the last row flush against the bottom edge,
        # which is the whole point of a pane that reads bottom-up.
        self.history_view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)

        self.help_pane = QTextEdit()
        self.help_pane.setObjectName("helpPane")
        self.help_pane.setReadOnly(True)
        # Read-only still takes focus by default (for its own scrolling); a
        # Tab or a click into the text then swallowed everything typed. The
        # input line scrolls it instead (_scroll_key).
        self.help_pane.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Wrap to the viewport. The bulk of the document is HTML tables, whose
        # columns stay aligned while the summary cell wraps — so wrapping costs
        # nothing there and saves the reader ~400px of horizontal scrolling.
        # The two <pre> blocks (basics, shortcuts) still can't wrap and keep
        # their hand-aligned columns, so a narrow window can still scroll
        # sideways for those — the original trade, now limited to them.
        self.help_pane.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)

        self.vars_pane = QListWidget()
        self.vars_pane.setObjectName("varsPane")
        self.vars_pane.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.vars_pane.itemClicked.connect(self._insert_var_name)
        self.vars_pane.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.vars_pane.customContextMenuRequested.connect(self._vars_context_menu)

        self.pane_stack = QStackedWidget()
        self.pane_stack.addWidget(self.history_view)
        self.pane_stack.addWidget(self.help_pane)
        self.pane_stack.addWidget(self.vars_pane)
        self.pane_stack.setCurrentWidget(self.history_view)
        # This is the elastic zone: it already scrolls, so it should absorb
        # every pixel of slack in either direction and let the fixed-content
        # zones below have exactly what they ask for. Ignored (rather than a
        # stretch factor alone) drops its own height hint from the negotiation,
        # so a long history can no longer shave pixels off the inspector.
        self.pane_stack.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored
        )
        self.pane_stack.setMinimumHeight(PANE_MIN_H)

        # The pane stack was the one zone with no silkscreen caption, so
        # switching to vars or a help topic swapped in a similar-looking list
        # with nothing naming it. Tracks whatever the stack is showing.
        self.pane_caption = ZoneCaption("HISTORY")
        self.pane_caption.set_palette(palette)

        self.result_caption = ZoneCaption("RESULT")
        self.result_caption.set_palette(palette)
        # Wraps a value wider than the window instead of cutting it at the edge.
        self.result_label = WrapAnywhereLabel("—")
        self.result_label.setObjectName("resultValue")
        self.result_label.setProperty("dimmed", "true")
        self.result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # Selectable text silently switches a QLabel to ClickFocus, so a click
        # to copy the readout left the input line deaf until clicked back.
        self.result_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.result_label.setWordWrap(True)

        self.input_bar = InputBar()
        self.input = self.input_bar.input
        self.preview = self.input_bar.preview
        # Fits the 520px minimum window; the old wording ran 70px past the
        # input's right edge there and simply got cut. The empty history pane
        # carries the longer "here's what this thing does" version.
        self.input.setPlaceholderText("type an expression — try help")
        self.input.submitted.connect(self._evaluate)
        self.input.textChanged.connect(self._schedule_preview)
        self.input.installEventFilter(self)
        # The window manager can still resize the history view after our
        # initial scrollToBottom() (showEvent) — e.g. Wayland settling final
        # geometry a beat after the window is mapped — which otherwise
        # leaves the scrollbar frozen one row short of the new bottom.
        # Re-pin only if we were already at the bottom pre-resize, so a
        # resize while reviewing older entries doesn't yank the view down.
        self.history_view.installEventFilter(self)
        self.history_view.viewport().installEventFilter(self)
        self.highlighter = ExprHighlighter(
            self.input.document(), palette, session.decimal_syntax
        )
        self.completer = Completer(self.input, session, palette)

        self.inspector = Inspector(palette, lambda text: QApplication.clipboard().setText(text))
        self.inspector_scroll = InspectorScroll()
        self.inspector_scroll.setObjectName("inspectorScroll")
        self.inspector_scroll.setWidget(self.inspector)
        self.inspector_scroll.setWidgetResizable(True)  # reflow the bit grid by width
        self.inspector_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.inspector_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # never steal focus
        # Horizontal never: every child already reflows to the viewport width,
        # so a horizontal bar would only ever mean a layout bug.
        self.inspector_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.vizpanel = self.inspector.vizpanel
        self.intview = self.inspector.intview
        self.channels = self.inspector.channels
        self.intview.value_to_input.connect(self._set_input)
        self.intview.arg_sep = lambda: self.session.decimal_syntax.arg_sep
        self.intview.copied.connect(self._toast)
        self.channels.to_input.connect(self._set_input)
        self.channels.copied.connect(self._toast)
        self.channels.ref_changed.connect(self._on_ref_changed)

        self.root_layout.addWidget(margin_wrap(self.pane_caption, 12))
        self.root_layout.addWidget(self.pane_stack, 1)
        self.root_layout.addWidget(margin_wrap(self.result_caption, 12))
        self.root_layout.addWidget(self.result_label)
        self.root_layout.addWidget(self.input_bar)
        self.root_layout.addWidget(self.inspector_scroll)
        self.setCentralWidget(root)

        self._build_status_bar()
        self._build_shortcuts()

        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(PREVIEW_DEBOUNCE_MS)
        self.preview_timer.timeout.connect(self._update_preview)

        self.toast_timer = QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.setInterval(1800)
        self.toast_timer.timeout.connect(self._clear_toast)

        # Default sized so the widest case — a 64-bit word, whose bit grid
        # wraps to four rows — fits without scrolling. Smaller windows are
        # still fine (the inspector scrolls), this just picks a first-run size
        # that doesn't start out scrolled. Replaced by restored geometry below.
        self.resize(640, 880)
        if self.store is not None:
            load_session(self.session)
            load_state(self.session)
            self._refresh_status()
            for old in self.store.load():
                self.model.append(
                    HistoryEntry(
                        old.expression,
                        old.result,
                        old.note,
                        value=old.value,
                        prefix=old.prefix,
                        timestamp=old.timestamp,
                    )
                )
            self._refresh_result_label()
            s = app_settings()
            geometry = s.value("geometry")
            if isinstance(geometry, (bytes, QByteArray)):  # a hand-edited INI can hold anything
                self.restoreGeometry(geometry)
            if s.value("always_on_top", False, type=bool):
                self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            if not s.value("inspector_visible", True, type=bool):
                self.inspector_scroll.hide()
            stored_mode = s.value("theme_mode", "auto", type=str)
            if stored_mode in THEME_MODES:
                self.theme_mode = stored_mode
                self._update_theme_chip()
            channels_blob = s.value("channels")
            if channels_blob is not None:
                with contextlib.suppress(ValueError, KeyError, TypeError):
                    self.channels.restore(
                        json.loads(channels_blob),
                        self.session.format_value,
                        self.session.word_size,
                    )
                    self._on_ref_changed()

        self._apply_session_to_widgets()
        self.intview.show_value(None, session.word_size, session.signed)
        self.input.setFocus()

    def _apply_session_to_widgets(self) -> None:
        """Bring the widgets in line with the session as it is *now*.

        They are constructed from the session as passed in; load_session then
        changes it. Nothing re-applied the difference, so a persisted period
        mode still highlighted with the comma grammar, stored rows kept their
        decimal text under a HEX chip, and the pin rack assumed a 64-bit word.
        """
        syntax = self.session.decimal_syntax
        self.highlighter.set_syntax(syntax)
        self.history_view.set_syntax(syntax)
        self._reformat_history()
        self._refresh_result_label()
        self.channels.refresh(self.session.format_value, self.session.word_size)

    # -- persistence -----------------------------------------------------------

    def _try_save(self, what: str, action: Callable[[], object]) -> str | None:
        """Run one persistence write; a failure becomes a message, not an abort.

        These run in the middle of a UI action. An exception out of one used to
        skip the rest of the slot — the input was never cleared and every later
        Enter re-ran the same failure — with the traceback going to a console
        the frozen build does not have.
        """
        if self.store is None:
            return None
        try:
            action()
        except (OSError, ValueError) as exc:
            reason = getattr(exc, "strerror", None) or str(exc)
            return f"{what} not saved: {reason}"
        return None

    def _save_state(self) -> str | None:
        return self._try_save("variables", lambda: save_state(self.session))

    # -- construction helpers ---------------------------------------------------

    def _chip_handlers(self) -> dict[str, Callable[[], None]]:
        return {
            "angle": self._toggle_angle,
            "word": self._cycle_word_size,
            "sign": self._toggle_signed,
            "base": self._cycle_int_base,
            "notation": self._cycle_notation,
            "float": self._toggle_float_view,
            "decimal": self._toggle_decimal_mode,
        }

    @staticmethod
    def _chip_width(key: str) -> int:
        """Width of the widest label `key`'s chip can display, plus QSS padding.

        Measured against a QFont built here rather than the widget's own
        metrics: at construction time the chip has not been polished yet, so
        `chip.fontMetrics()` still reports the default face and under-measures
        the silkscreen label by enough to let "32-bit" elide at 520px.
        """
        labels = {
            "angle": ["DEG", "RAD"],
            "word": [f"{size}-bit" for size in WORD_SIZES],
            "sign": ["signed", "unsigned"],
            "base": [base.upper() for base in INT_BASES],
            "notation": [n.replace("eng_si", "eng·si").upper() for n in NOTATIONS],
            "float": ["FLOAT ON", "FLOAT OFF"],
            "decimal": ["1,2", "1.2"],
        }[key]
        font = QFont(LABEL_FAMILY)
        font.setPixelSize(FONT_MICRO)
        metrics = QFontMetrics(font)
        return max(metrics.horizontalAdvance(text) for text in labels) + 2 * CHIP_PAD_H

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        # The default corner grip draws dotted texture into the chip row;
        # window edges still resize without it.
        bar.setSizeGripEnabled(False)
        self.status_items: dict[str, QToolButton] = {}
        for key, _shortcut, _description in MODE_CHIPS:
            chip = QToolButton()
            chip.setProperty("class", "modeChip")
            chip.setAutoRaise(True)
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # chips never steal focus
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(self._chip_handlers()[key])
            # Sized for the widest label the chip can ever hold, so a narrow
            # window can't elide "unsigned" to "un…ed" and toggling a mode
            # doesn't shuffle the whole status bar sideways.
            chip.setMinimumWidth(self._chip_width(key))
            bar.addPermanentWidget(chip)
            self.status_items[key] = chip
        self.theme_chip = QToolButton()
        self.theme_chip.setProperty("class", "modeChip")
        self.theme_chip.setAutoRaise(True)
        self.theme_chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.theme_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_chip.clicked.connect(self._cycle_theme_mode)
        bar.addPermanentWidget(self.theme_chip)
        self._update_theme_chip()
        help_hint = QToolButton()
        help_hint.setText("?")
        help_hint.setProperty("class", "modeChip")
        help_hint.setAutoRaise(True)
        help_hint.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        help_hint.setCursor(Qt.CursorShape.PointingHandCursor)
        help_hint.setToolTip("help  (F1)")
        help_hint.clicked.connect(lambda _=False: self._show_help())
        bar.addPermanentWidget(help_hint)
        self._refresh_status()

    def _build_shortcuts(self) -> None:
        handlers = self._chip_handlers()
        chip_shortcuts = tuple(
            (shortcut, handlers[key]) for key, shortcut, _description in MODE_CHIPS
        )
        for keys, handler in chip_shortcuts + (
            ("Ctrl+L", self._clear_history_view),
            ("Ctrl+Shift+C", self._copy_result),
            ("F1", self._show_help),
            ("Alt+T", self._toggle_always_on_top),
            ("Alt+V", self._toggle_vars),
            ("Alt+P", self._pin_last_result),
            ("Alt+G", self._toggle_grid_cursor),
            ("Alt+I", self._toggle_inspector),
            ("Alt+M", self._cycle_theme_mode),
        ):
            action = QAction(self)
            action.setShortcut(QKeySequence(keys))
            action.triggered.connect(handler)
            self.addAction(action)

    # -- evaluate / preview -------------------------------------------------------

    def _evaluate(self) -> None:
        text = self.input.text()
        if not text.strip():
            return
        self._clear_inspect_lock(follow_ans=False)
        self._hide_help()
        try:
            outcome = self.session.evaluate(text)
        except CalcError as exc:
            self._show_error(exc)
            return
        if outcome.kind == "help":
            # Bare `help` gets the rich overview; `help <name>` the topic text.
            self._show_help(outcome.help_text if outcome.target else None)
            self.input.clear()
            return
        if outcome.kind == "vars":
            self._show_vars()
            self.input.clear()
            return
        if outcome.kind == "del":
            self.input.clear()
            assert outcome.target is not None
            self._after_delete(outcome.target)
            return
        if outcome.kind == "csr":
            self.input.clear()
            if outcome.target is not None:
                failed = self._save_state()
                self._toast(failed or outcome.help_text or f"defined csr {outcome.target}")
                self._refresh_vars_pane()
            else:
                self._show_vars()
            return
        if outcome.kind == "clear":
            self.model.clear()
            self._refresh_result_label()
            store = self.store
            failed = (
                self._try_save("history", store.clear) if store is not None else None
            ) or self._save_state()
            self.input.clear()
            self._toast(failed or "history cleared (variables & csrs kept)")
            self._panel_real = None
            self.intview.show_value(None, self.session.word_size, self.session.signed)
            self.inspector.show_viz_payload(None)
            self._refresh_vars_pane()
            return
        if outcome.value is None:
            return
        primary = self.session.format_value(outcome.value)
        prefix = f"{outcome.target} ← " if outcome.kind == "assign" else ""
        display = prefix + primary
        entry = HistoryEntry(
            text.strip(),
            display,
            outcome.value.note or "",
            value=outcome.value,
            prefix=prefix,
            timestamp=time.time(),  # shared with the stored line: delete matches on it
        )
        self.model.append(entry)
        self._refresh_result_label()
        store = self.store
        failed = None
        if store is not None:
            failed = self._try_save(
                "history",
                lambda: store.append(
                    entry.expression,
                    entry.result,
                    entry.note,
                    prefix=entry.prefix,
                    value=entry.value,
                    timestamp=entry.timestamp,
                ),
            ) or self._save_state()
        self.history_view.scrollToBottom()
        self.recall_index = None
        self._recall_draft = ""
        self.input.clear()
        if failed:
            self._toast(failed)
        else:
            self._set_preview(" ", "ok")
        self._panel_follow(outcome.value)
        if outcome.kind == "assign":
            self._refresh_vars_pane()

    def _schedule_preview(self) -> None:
        self.preview_timer.start()

    def _update_preview(self) -> None:
        text = self.input.text()
        if not text.strip():
            self.highlighter.set_error_span(None)
            # A command that clears the input (`clear`, `del x`, a csr
            # definition) toasts and *then* trips the debounced preview, so an
            # empty line must leave a live toast standing — otherwise the
            # confirmation would blink out ~100ms after appearing.
            if not self._toast_active:
                self._set_preview(" ", "ok")
            if not self._inspect_locked:
                self._panel_follow(self.session.ans)  # back to the last result
            return
        self._clear_inspect_lock(follow_ans=False)  # typing resumes live-follow
        try:
            outcome = self.session.preview(text)
        except IncompleteError:
            self.highlighter.set_error_span(None)
            self._set_preview("…", "ok")
            return  # keep the panel steady while typing continues
        except CalcError as exc:
            if self._is_partial_name(text, exc):
                # `cl` on the way to `clog2(`: a name still being typed, which
                # the completer is offering right now, is not an error yet.
                self.highlighter.set_error_span(None)
                self._set_preview("…", "ok")
                return
            self._show_error(exc)
            return
        self.highlighter.set_error_span(None)
        if outcome.kind == "help":
            self._set_preview("press Enter for help", "ok")
            return
        if outcome.kind == "vars":
            self._set_preview("press Enter to list variables", "ok")
            return
        if outcome.kind == "del":
            self._set_preview(f"press Enter to delete {outcome.target}", "ok")
            return
        if outcome.kind == "csr":
            if outcome.target is not None:
                self._set_preview(f"press Enter to define csr {outcome.target}", "ok")
            else:
                self._set_preview("press Enter to list csrs", "ok")
            return
        if outcome.kind == "clear":
            self._set_preview("press Enter to clear history (variables & csrs kept)", "ok")
            return
        if outcome.value is None:
            self._set_preview(" ", "ok")
            return
        result = self.session.format_value(outcome.value)
        if outcome.kind == "assign":
            self._set_preview(outcome.normalized, "ok")
        else:
            # A bare literal echoes as itself (`255 = 255`): show the result once.
            echo = "" if outcome.normalized == result else outcome.normalized
            self._set_preview(f"= {result}", "ok", head=echo)
        self._panel_follow(outcome.value)

    def _is_partial_name(self, text: str, exc: CalcError) -> bool:
        """True if `exc` is only about an identifier still being typed.

        That is: the offending span is a name, it is the last thing on the
        line, and it is a proper prefix of something the completer would offer.
        `zz` (completes to nothing) and `cl + 1` (already moved on) stay errors.
        """
        if not isinstance(exc, EvalError) or exc.span.end != len(text.rstrip()):
            return False
        name = text[exc.span.start : exc.span.end]
        if not name.isidentifier():
            return False
        return any(
            c.name != name and c.name.startswith(name) for c in completions(self.session)
        )

    def _panel_follow(self, value: Value | None) -> None:
        """Point the integer panel at a previewed/committed value.

        A packed layout (Qm.n, IEEE-754) takes the panel over read-only,
        whichever way round its function returned it — fix() yields the raw
        integer, unfix() the real, and both describe the same word. Otherwise
        integers drive the editable bit grid, and reals show the FLOAT ON view
        (word size 32/64) or grey the panel (8/16).
        """
        viz = value.viz if value is not None else None
        self._panel_real = None
        # TRACE is now only the card-shaped payloads; bit layouts live in REGISTER.
        self.inspector.show_viz_payload(
            viz if isinstance(viz, (ClockViz, MemViz, TimeViz)) else None
        )
        number = value.number if value is not None else None
        self.channels.set_live(number if isinstance(number, int) else None)
        if isinstance(viz, FixedPointViz):
            self.intview.show_value(
                None, self.session.word_size, self.session.signed, fixed_view=viz
            )
            return
        if isinstance(viz, FloatBitsViz):
            self.intview.show_value(
                None, self.session.word_size, self.session.signed, float_bits=viz
            )
            return
        if isinstance(number, int):
            assert value is not None
            self.intview.show_value(
                number, self.session.word_size, self.session.signed, csr=value.csr
            )
            return
        self._panel_real = value  # None, or the real this branch is showing
        float_views = (
            self.session.float_views_for(value)
            if value is not None and self.session.show_float_view
            else None
        )
        self.intview.show_value(
            None, self.session.word_size, self.session.signed, float_views=float_views
        )

    def _on_ref_changed(self) -> None:
        """Re-feed the live value so the armed channel can redraw its XOR diff."""
        self.channels.set_live(self.intview.scratch if self.intview.active else None)

    def _set_preview(self, text: str, state: str, head: str = "") -> None:
        """Write the line under the input. `state` is "ok" | "error" | "toast".

        `head` is an optional lead-in (the echoed expression) shown before
        `text`; when the line is too narrow for both, it is `head` that elides.
        """
        self._toast_active = state == "toast"  # a real preview supersedes a toast
        self._preview_head = head
        self._preview_tail = text
        self._preview_full = f"{head} {text}" if head else text
        self._render_preview()
        self.preview.setProperty("state", state)
        style = self.preview.style()
        style.unpolish(self.preview)
        style.polish(self.preview)

    def _render_preview(self) -> None:
        """Fit the current preview text to the label, eliding rather than cutting.

        Long previews (a wide normalized expression plus its result) and long
        confirmations both outrun the line at narrow widths; without this they
        just stop at the edge with no sign anything is missing.
        """
        metrics = QFontMetrics(self.preview.font())
        available = self.preview.width() - 2 * PREVIEW_PAD_H
        full, head, tail = self._preview_full, self._preview_head, self._preview_tail
        if metrics.horizontalAdvance(full) <= available or not head:
            shown = metrics.elidedText(full, Qt.TextElideMode.ElideRight, available)
        else:
            # Keep the answer. Eliding the whole line on the right kept the echo
            # and dropped `= result` — the one part the line exists to show.
            room = available - metrics.horizontalAdvance(" " + tail)
            if room > metrics.horizontalAdvance("…"):
                shown = metrics.elidedText(head, Qt.TextElideMode.ElideRight, room) + " " + tail
            else:
                shown = metrics.elidedText(tail, Qt.TextElideMode.ElideMiddle, available)
        self.preview.setText(shown)
        self.preview.setToolTip(full if shown != full else "")

    def _show_error(self, exc: CalcError) -> None:
        # The offending span gets a wavy underline in the input itself (a
        # text caret under a differently-sized preview font never lines up).
        self.highlighter.set_error_span((exc.span.start, exc.span.end))
        self._set_preview(exc.message, "error")

    def _on_history_scroll_changed(self, value: int) -> None:
        self._history_follow_bottom = value >= self.history_view.verticalScrollBar().maximum()

    def _resync_history_padding(self) -> None:
        """Push a short history down so it sits against the input line.

        A REPL reads bottom-up: the newest entry belongs next to where you
        type, not stranded at the top of a mostly empty pane (~400px of gap in
        a tall window). Once the rows overflow the viewport the padding is
        zero and everything below — scrollToBottom, the follow-the-bottom
        tracking — behaves exactly as it did.
        """
        view = self.history_view
        if self.model.rowCount() == 0:
            # Nothing to push down, and padding the whole pane away would leave
            # a zero-height viewport that never paints the empty-state hint.
            view.setViewportMargins(0, 0, 0, 0)
            return
        content = sum(view.sizeHintForRow(row) for row in range(self.model.rowCount()))
        # Measure against the height the viewport would have with no padding —
        # viewport() already excludes the margin we set last time, so using it
        # directly would feed back on itself and converge on half the slack.
        available = view.viewport().height() + view.viewportMargins().top()
        slack = max(0, available - content)
        if view.viewportMargins().top() != slack:
            view.setViewportMargins(0, slack, 0, 0)

    def _resync_history_scroll(self) -> None:
        # Re-checked here rather than at schedule time: a resize's layout
        # settles on the next event-loop tick, and by then the user may
        # already have scrolled away from the bottom.
        self._resync_history_padding()
        if self._history_follow_bottom:
            self.history_view.scrollToBottom()

    # -- history recall ---------------------------------------------------------

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if (
            obj in (self.history_view, self.history_view.viewport())
            and event.type() == QEvent.Type.Resize
        ):
            # The viewport too, not just the view: anything that changes the
            # pane's height without resizing the view itself (the inspector
            # growing a wrapped field table, say) would otherwise leave the
            # bottom-padding computed against a stale height — which clips the
            # last row *and* leaves no scrollbar to reach it.
            QTimer.singleShot(0, self._resync_history_scroll)
        if obj is self.input and event.type() == QEvent.Type.FocusOut:
            self.completer.hide()
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if self.completer.handle_key(event):
                return True
            if self._scroll_key(event):
                return True  # a pane or the inspector took it as a scroll
            if self._handle_grid_cursor_key(event):
                return True  # Alt+G cursor is up: arrows drive the bit grid
            if event.key() == Qt.Key.Key_Up:
                self._recall(-1)
                return True
            if event.key() == Qt.Key.Key_Down:
                self._recall(+1)
                return True
            if event.key() == Qt.Key.Key_Escape:
                if self.intview.cursor_bit is not None:  # leave grid mode first
                    self.intview.stop_cursor()
                elif self.intview.clear_selection():  # then a bit-range selection
                    pass
                elif self._inspect_locked:
                    self._clear_inspect_lock(follow_ans=True)
                else:
                    self._hide_help()
                return True
        return super().eventFilter(obj, event)

    def _recall(self, direction: int) -> None:
        entries = self.model.entries
        if not entries:
            return
        if self.recall_index is None:
            if direction > 0:
                return
            # Leaving the live line: keep what was on it. Up used to throw a
            # half-typed expression away with no way back.
            self._recall_draft = self.input.text()
            self.recall_index = len(entries) - 1
        else:
            self.recall_index += direction
        if self.recall_index < 0:
            self.recall_index = 0
        if self.recall_index >= len(entries):
            self.recall_index = None
            with self.completer.suppressed():
                self.input.setText(self._recall_draft)
            return
        with self.completer.suppressed():  # recalled text must not pop completions
            self.input.setText(entries[self.recall_index].expression)

    def _history_context_menu(self, pos: QPoint) -> None:
        index = self.history_view.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()
        entry = self.model.entries[row]
        menu = QMenu(self)
        actions: dict[QAction, str] = {}

        def add(label: str, action_id: str) -> None:
            actions[menu.addAction(label)] = action_id

        add("copy result", "copy_result")
        add("copy expression", "copy_expression")
        if entry.value is not None and isinstance(entry.value.number, int):
            menu.addSeparator()
            add("copy as hex", "copy_hex")
            add("copy as dec", "copy_dec")
            add("copy as bin", "copy_bin")
            menu.addSeparator()
            for label, action_id in (
                ("copy as C literal", "copy_c"),
                ("copy as Verilog literal", "copy_verilog"),
                ("copy as VHDL literal", "copy_vhdl"),
            ):
                add(f"{label}   {self._source_literal(entry.value, action_id)}", action_id)
        if entry.value is not None:
            menu.addSeparator()
            add("pin value", "pin")
        menu.addSeparator()
        add("recall", "recall")
        add("delete entry", "delete")
        chosen = menu.exec(self.history_view.viewport().mapToGlobal(pos))
        if chosen is not None:
            self._history_action(actions[chosen], row)

    def _history_action(self, action: str, row: int) -> None:
        entry = self.model.entries[row]
        clipboard = QApplication.clipboard()
        if action == "copy_result":
            _name, text = split_assignment(entry.result, entry.prefix)
            clipboard.setText(text)
            self._toast(f"copied {text}")
        elif action == "copy_expression":
            clipboard.setText(entry.expression)
            self._toast("expression copied")
        elif action == "copy_dec" and entry.value is not None:
            # The digits, whatever the notation chip says: "copy as dec" in SCI
            # mode used to copy `2.55e+2`.
            text = self._plain_decimal(entry.value)
            clipboard.setText(text)
            self._toast(f"copied {text}")
        elif action in ("copy_hex", "copy_bin") and entry.value is not None:
            text = self.session.format_value(entry.value, base=action.removeprefix("copy_"))
            clipboard.setText(text)
            self._toast(f"copied {text}")
        elif action in ("copy_c", "copy_verilog", "copy_vhdl") and entry.value is not None:
            text = self._source_literal(entry.value, action)
            clipboard.setText(text)
            self._toast(f"copied {text}")
        elif action == "recall":
            self._set_input(entry.expression)
        elif action == "delete":
            self.model.remove(row)
            self._refresh_result_label()
            store = self.store
            failed = None
            if store is not None:
                stored = StoredEntry(
                    entry.expression,
                    entry.result,
                    entry.note,
                    entry.timestamp,
                    value=entry.value,
                    prefix=entry.prefix,
                )
                # That one line: the file also holds whatever Ctrl+L hid and
                # whatever is older than the rows that were loaded.
                failed = self._try_save("history", lambda: store.remove(stored))
            self._toast(failed or "entry deleted")
        elif action == "pin" and entry.value is not None:
            label = entry.prefix.partition(" ←")[0] if entry.prefix else None
            self._pin_value(entry.value, label)

    def _plain_decimal(self, value: Value) -> str:
        number = value.number
        if isinstance(number, int):
            try:
                return str(number)
            except ValueError:  # past Python's int->str cap: the display form will do
                pass
        return self.session.format_value(value, base="dec")

    def _source_literal(self, value: Value, style: str) -> str:
        """An integer as a literal for C, Verilog or VHDL source.

        Sized to the value's declared width when it has one (`12'hABC`), else
        to the word size — widened if the value does not fit — and two's
        complement for a negative. The HEX lane's `0xDEAD_BEEF` is none of
        these: C has no `_` separator, Verilog wants a width.
        """
        number = value.number
        assert isinstance(number, int)
        width = max(value.declared_width or self.session.word_size, bits_needed(number))
        masked = number & ((1 << width) - 1)
        digits = group_digits(f"{masked:X}", 4, min_width=-(-width // 4), prefix="")
        if style == "copy_c":
            return f"0x{masked:X}"
        if style == "copy_verilog":
            return f"{width}'h{digits}"
        # VHDL: a bare x"..." is 4 bits per digit; other widths need VHDL-2008's count.
        return f'x"{digits}"' if width % 4 == 0 else f'{width}x"{digits}"'

    def _recall_from_view(self, index: object) -> None:
        # Qt fires `clicked` before `doubleClicked` on the same press, so a
        # recall briefly locks the inspector via `_inspect_from_view` first;
        # `_set_input` below fires `textChanged` -> `_update_preview`, which
        # immediately clears the lock again. Harmless, don't "fix" it.
        row = index.row()  # type: ignore[attr-defined]
        self._set_input(self.model.entries[row].expression)

    def _inspect_from_view(self, index: object) -> None:
        row = index.row()  # type: ignore[attr-defined]
        entry = self.model.entries[row]
        if entry.value is None:  # disk-loaded entry: nothing to inspect
            return
        self._inspect_locked = True
        self._locked_value = entry.value
        self.history_view.setCurrentIndex(index)  # type: ignore[arg-type]
        self._panel_follow(entry.value)

    def _clear_inspect_lock(self, follow_ans: bool) -> None:
        self._inspect_locked = False
        self._locked_value = None
        self.history_view.clearSelection()
        if follow_ans:
            self._panel_follow(self.session.ans)

    def _set_input(self, text: str) -> None:
        with self.completer.suppressed():
            self.input.setText(text)
        self.input.setFocus()

    # -- channels rack ------------------------------------------------------------

    def _pin_value(self, value: Value, label: str | None) -> None:
        text = self.session.format_value(value)
        already = self.channels.label_of(value) if label is None else None
        assigned = self.channels.pin(value, text, label)
        if assigned is None:
            self._toast("pinned rack full — unpin one")
        elif already is not None:
            self._toast(f"already pinned as {already}")
        else:
            self._toast(f"pinned {assigned}")

    def _pin_last_result(self) -> None:
        if self.session.ans is None:
            self._toast("nothing to pin")
            return
        self._pin_value(self.session.ans, None)

    # -- settings toggles --------------------------------------------------------

    def _cycle_word_size(self) -> None:
        self.session.cycle_word_size()
        self._after_setting_change()

    def _toggle_signed(self) -> None:
        self.session.signed = not self.session.signed
        self._after_setting_change()

    def _toggle_angle(self) -> None:
        self.session.angle_deg = not self.session.angle_deg
        self._after_setting_change()

    def _cycle_notation(self) -> None:
        self.session.cycle_notation()
        self._after_setting_change()

    def _cycle_int_base(self) -> None:
        self.session.cycle_int_base()
        self._after_setting_change()

    def _toggle_float_view(self) -> None:
        self.session.show_float_view = not self.session.show_float_view
        self._after_setting_change()

    def _toggle_decimal_mode(self) -> None:
        self.session.cycle_decimal_mode()
        self._after_setting_change()

    def _after_setting_change(self) -> None:
        self._refresh_status()
        # Re-tokenize the input under the (possibly new) decimal/arg grammar so
        # `3,14` colors as one number and `;` no longer trips a lex-error
        # underline. No-op unless the decimal mode actually changed.
        self.highlighter.set_syntax(self.session.decimal_syntax)
        self.history_view.set_syntax(self.session.decimal_syntax)
        self._reformat_history()
        self._refresh_result_label()
        self.channels.refresh(self.session.format_value, self.session.word_size)
        if self.vars_pane.isVisibleTo(self):
            self._refresh_vars_pane()  # values honor the new base/notation
        if self.store is not None:
            save_session(self.session)
        # Re-render the current panel value under the new settings; never
        # re-evaluate. The packed layouts have to be carried through: they are
        # function results, not display preferences, so a word-size cycle (or
        # Alt+F) must not drop the Qm.n / float32 view showing right now.
        # The float view is itself a display setting (FLOAT ON/OFF, and its
        # width follows the word size), so it is re-derived from the real it
        # shows rather than carried: carrying it left a 32-bit view under a
        # 64-bit chip, or any view under FLOAT OFF, whenever the input line
        # was mid-expression and the preview below did not re-follow.
        float_views = (
            self.session.float_views_for(self._panel_real)
            if self._panel_real is not None and self.session.show_float_view
            else None
        )
        self.intview.show_value(
            self.intview.scratch if self.intview.active else None,
            self.session.word_size,
            self.session.signed,
            float_views=float_views,
            fixed_view=self.intview.fixed_view,
            float_bits=self.intview.float_bits,
            csr=self.intview.csr,
        )
        self._update_preview()
        if self._inspect_locked:
            # The carry-through above kept a locked entry's *old* rendering
            # (a 32-bit float view under a 64-bit chip, a float view after
            # FLOAT OFF); the empty-input preview leaves a locked panel alone,
            # so re-derive it from the entry itself.
            self._panel_follow(self._locked_value)

    def _reformat_history(self) -> None:
        """Re-render history results under the current display settings."""
        self.model.reformat(self.session.format_value)

    def _refresh_result_label(self) -> None:
        """The RESULT readout is the last history entry, or the dimmed dash
        when there is none — the one place the readout text is decided."""
        if self.model.entries:
            self._set_readout(self.model.entries[-1].result, dimmed=False)
        else:
            self._set_readout("—", dimmed=True)

    def _set_readout(self, text: str, dimmed: bool) -> None:
        self.result_label.setText(text)
        self.result_label.setProperty("dimmed", "true" if dimmed else "false")
        style = self.result_label.style()
        style.unpolish(self.result_label)
        style.polish(self.result_label)

    def _last_result_text(self) -> str:
        """What Ctrl+Shift+C copies: the readout's value, minus any `x ← `."""
        if not self.model.entries:
            return ""
        last = self.model.entries[-1]
        _name, text = split_assignment(last.result, last.prefix)
        return text

    def _refresh_status(self) -> None:
        session = self.session
        texts = {
            "angle": "DEG" if session.angle_deg else "RAD",
            "word": f"{session.word_size}-bit",
            "sign": "signed" if session.signed else "unsigned",
            "base": session.int_base.upper(),
            "notation": session.notation.replace("eng_si", "eng·si").upper(),
            "float": "FLOAT ON" if session.show_float_view else "FLOAT OFF",
            "decimal": "1,2" if session.decimal_mode == "comma" else "1.2",
        }
        tips = {
            key: f"{description} — click or {shortcut}"
            for key, shortcut, description in MODE_CHIPS
        }
        for key, label in self.status_items.items():
            label.setText(texts[key])
            label.setToolTip(tips[key])

    # -- help / misc -----------------------------------------------------------------

    def _style_help_pane(self, palette: Palette) -> None:
        """Section headers in the silkscreen face — set before every setHtml,
        since Qt applies a document's default stylesheet at that call."""
        self.help_pane.document().setDefaultStyleSheet(
            f"h3 {{ color: {palette.accent}; font-family: '{LABEL_FAMILY}'; "
            f"letter-spacing: 1px; }}"
        )

    def _show_pane(self, pane: QWidget) -> None:
        """Switch the top pane, yielding the inspector's space to overlays.

        Help and variables are things you read, and both were being squeezed
        into whatever the inspector left over — the help overview is a ~2800px
        document that had a 244px window onto it. Neither is useful while
        reading, so they stand down until the history view is back. Restores
        only what this hid, so an inspector the user closed with Alt+I stays
        closed.
        """
        captions: dict[QWidget, str] = {
            self.history_view: "HISTORY",
            self.help_pane: "HELP" if self._help_overview_shown else "HELP TOPIC",
            self.vars_pane: "VARIABLES",
        }
        self.pane_caption.set_text(captions[pane])
        overlay = pane is not self.history_view
        if overlay and not self._pane_hid_inspector and self.inspector.isVisibleTo(self):
            self.inspector_scroll.setVisible(False)
            self._pane_hid_inspector = True
        elif not overlay and self._pane_hid_inspector:
            self.inspector_scroll.setVisible(True)
            self._pane_hid_inspector = False
        self.pane_stack.setCurrentWidget(pane)

    def _scroll_key(self, event: QKeyEvent) -> bool:
        """Route scroll keys to the panes, none of which ever takes focus.

        The input line keeps focus at all times, so every scrollable surface
        has to be driven from here or it is mouse-only:

        - PageUp/PageDown page whatever the top pane shows — history included,
          which had no keyboard scrolling at all;
        - Up/Down scroll help or variables while one is showing (over history
          they stay history recall);
        - Shift+PageUp/PageDown page the inspector, whose bit grid and pinned
          rack fall below the fold at 64-bit word sizes or in a small window.
        """
        key = event.key()
        paging: dict[int, QAbstractSlider.SliderAction] = {
            Qt.Key.Key_PageUp: QAbstractSlider.SliderAction.SliderPageStepSub,
            Qt.Key.Key_PageDown: QAbstractSlider.SliderAction.SliderPageStepAdd,
        }
        if key in paging and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.inspector_scroll.verticalScrollBar().triggerAction(paging[key])
            return True
        pane = self.pane_stack.currentWidget()
        actions = dict(paging)
        if pane is not self.history_view:
            actions[Qt.Key.Key_Up] = QAbstractSlider.SliderAction.SliderSingleStepSub
            actions[Qt.Key.Key_Down] = QAbstractSlider.SliderAction.SliderSingleStepAdd
        action = actions.get(key)
        if action is None:
            return False
        scrollbar = pane.verticalScrollBar()  # type: ignore[attr-defined]
        scrollbar.triggerAction(action)
        return True

    # -- bit-grid keyboard cursor ----------------------------------------------

    def _toggle_grid_cursor(self) -> None:
        if self.intview.cursor_bit is not None:
            self.intview.stop_cursor()
            self._toast("bit cursor off")
            return
        if not self.intview.start_cursor():
            self._toast("no editable register to move a cursor over")
            return
        self._toast("bit cursor: arrows move, space toggles, Esc exits")

    def _handle_grid_cursor_key(self, event: QKeyEvent) -> bool:
        """Drive the bit grid from the input line, which never gives up focus.

        Only active between Alt+G and Esc, so the keys it borrows (arrows for
        history recall, space for typing) behave normally the rest of the time.
        """
        if self.intview.cursor_bit is None:
            return False
        extend = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        per_row = self.intview.bits_per_row()
        steps: dict[int, int] = {
            Qt.Key.Key_Left: -1,
            Qt.Key.Key_Right: 1,
            Qt.Key.Key_Up: -per_row,
            Qt.Key.Key_Down: per_row,
        }
        key = event.key()
        if key in steps:
            self.intview.move_cursor(steps[key], extend)
            return True
        if key == Qt.Key.Key_Space:
            self.intview.toggle_cursor_bit()
            return True
        if key in (Qt.Key.Key_Home, Qt.Key.Key_End):
            # Home = MSB (top-left), End = bit 0 — the grid's own reading order.
            target = self.session.word_size - 1 if key == Qt.Key.Key_Home else 0
            self.intview.move_cursor(self.intview.cursor_bit - target, extend)
            return True
        return False

    def _show_help(self, text: str | None = None) -> None:
        self._help_overview_shown = text is None
        if text is None:
            self._style_help_pane(self.palette_tokens)
            arg_sep = self.session.decimal_syntax.arg_sep + " "
            self.help_pane.setHtml(general_help_html(SHORTCUT_SECTIONS, arg_sep))
        else:
            self.help_pane.setPlainText(text)
        self.help_pane.verticalScrollBar().setValue(0)  # always open at the top
        self._show_pane(self.help_pane)

    def _hide_help(self) -> None:
        self._show_pane(self.history_view)

    # -- variables pane ---------------------------------------------------------

    def _show_vars(self) -> None:
        self._refresh_vars_pane()
        self._show_pane(self.vars_pane)

    def _toggle_vars(self) -> None:
        if self.vars_pane.isVisibleTo(self):
            self._hide_help()
        else:
            self._show_vars()

    def _refresh_vars_pane(self) -> None:
        self.vars_pane.clear()
        if not self.session.variables and not self.session.csrs:
            placeholder = QListWidgetItem("no variables — assign with  x = 42")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.vars_pane.addItem(placeholder)
            return
        for name, value in self.session.variables.items():
            item = QListWidgetItem(f"{name} = {self.session.format_value(value)}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip("click to insert; right-click or `del <name>` to remove")
            self.vars_pane.addItem(item)
        for name, c in self.session.csrs.items():
            item = QListWidgetItem(f"{name} = csr {c.spec_text()}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip("click to insert a call; right-click or `del <name>` to remove")
            self.vars_pane.addItem(item)

    def _insert_var_name(self, item: QListWidgetItem) -> None:
        name = item.data(Qt.ItemDataRole.UserRole)
        if not name:
            return
        text = f"{name}(" if name in self.session.csrs else name
        with self.completer.suppressed():
            self.input.insertPlainText(text)
        self.input.setFocus()

    def _vars_context_menu(self, pos: QPoint) -> None:
        item = self.vars_pane.itemAt(pos)
        name = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not name:
            return
        menu = QMenu(self)
        delete = menu.addAction(f"delete {name}")
        if menu.exec(self.vars_pane.mapToGlobal(pos)) is delete:
            self._delete_name(name)

    def _delete_name(self, name: str) -> None:
        """Delete a variable or csr the same way a typed `del NAME` does."""
        try:
            self.session.evaluate(f"del {name}")
        except CalcError as exc:
            self._toast(exc.message)
            return
        self._after_delete(name)

    def _after_delete(self, name: str) -> None:
        self._toast(f"deleted {name}")
        self._refresh_vars_pane()
        shown = self.intview.csr
        if shown is not None and shown.name == name:
            # The layout on show no longer resolves by name: drop it so a
            # bit edit can't write back `NAME(0x..)` for a deleted csr.
            self.intview.show_value(
                self.intview.scratch if self.intview.active else None,
                self.session.word_size,
                self.session.signed,
                csr=None,
            )
        failed = self._save_state()
        if failed:
            self._toast(failed)

    def _clear_history_view(self) -> None:
        self.model.clear()
        self._refresh_result_label()
        # View only. (It used to add "type clear to wipe", but `clear` keeps
        # variables too, and has since Radix 5.)
        self._toast("history view cleared (saved history and variables are kept)")

    def _copy_result(self) -> None:
        text = self._last_result_text()
        if text:
            QApplication.clipboard().setText(text)
            self._toast(f"copied {text}")

    def _toggle_always_on_top(self) -> None:
        on_top = not bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on_top)
        self.show()
        if self.store is not None:
            app_settings().setValue("always_on_top", on_top)
        self._toast("always on top" if on_top else "normal stacking")

    def _toggle_inspector(self) -> None:
        # Toggles the scroll host, not the inspector inside it: hiding only the
        # inner widget would leave an empty scroll frame holding the space.
        visible = not self.inspector.isVisibleTo(self)
        self.inspector_scroll.setVisible(visible)
        self._pane_hid_inspector = False  # explicit choice outranks pane arbitration
        if self.store is not None:
            app_settings().setValue("inspector_visible", visible)
        self._toast("inspector shown" if visible else "inspector hidden")

    def _cycle_theme_mode(self) -> None:
        self.theme_mode = THEME_MODES[(THEME_MODES.index(self.theme_mode) + 1) % len(THEME_MODES)]
        self._update_theme_chip()
        if self.store is not None:
            app_settings().setValue("theme_mode", self.theme_mode)
        self._toast(f"theme: {self.theme_mode}")
        if self.on_theme_mode_changed is not None:
            self.on_theme_mode_changed()

    def _update_theme_chip(self) -> None:
        self.theme_chip.setIcon(theme_mode_icon(self.theme_mode, self.palette_tokens.muted))
        tips = {
            "auto": "theme: following the OS — click or Alt+M",
            "light": "theme: light (pinned) — click or Alt+M",
            "dark": "theme: dark (pinned) — click or Alt+M",
        }
        self.theme_chip.setToolTip(tips[self.theme_mode])

    def closeEvent(self, event: object) -> None:
        if self.store is not None:
            save_session(self.session)
            app_settings().setValue("geometry", self.saveGeometry())
            app_settings().setValue("channels", json.dumps(self.channels.to_json()))
        super().closeEvent(event)  # type: ignore[arg-type]

    def showEvent(self, event: object) -> None:
        # Item heights depend on the real (polished, visible) viewport width
        # for word-wrap — a scrollToBottom() called before the first show
        # lands short once layout settles, so defer it to here instead.
        super().showEvent(event)  # type: ignore[arg-type]
        if not self._did_initial_show:
            self._did_initial_show = True
            self.history_view.scrollToBottom()

    def _toast(self, message: str) -> None:
        """Transient confirmation, shown on the preview line under the input.

        It used to live in the status bar's message area, where the mode chips
        left it 46-58px — every message past about eight characters was cut,
        including the CSR-definition confirmation (`csr CTRL = EN[31]
        IRQ[30:28] ADDR[27:8] CMD[7:0]`, which rendered as `csr`). The preview
        line is full-width and already where the eye is after pressing Enter.
        """
        self._set_preview(message, "toast")
        self.toast_timer.start()

    def _clear_toast(self) -> None:
        if not self._toast_active:
            return  # something already replaced it; leave that alone
        self._toast_active = False
        self._update_preview()  # back to whatever the input line now says

    def apply_palette(self, palette: Palette) -> None:
        self.palette_tokens = palette
        self.delegate.set_palette(palette)
        self.history_view.set_palette(palette)
        self._update_theme_chip()
        self.pane_caption.set_palette(palette)
        self.result_caption.set_palette(palette)
        self.inspector.set_palette(palette)
        self.highlighter.set_palette(palette)
        self.completer.set_palette(palette)
        self.history_view.viewport().update()
        if self._help_overview_shown and self.help_pane.isVisibleTo(self):
            self._show_help()  # setHtml applies the stylesheet at parse time

    def resizeEvent(self, event: object) -> None:  # popup geometry would go stale
        if hasattr(self, "completer"):
            self.completer.hide()
        if hasattr(self, "preview"):
            self._render_preview()  # elision depends on the label's width
        super().resizeEvent(event)  # type: ignore[arg-type]
