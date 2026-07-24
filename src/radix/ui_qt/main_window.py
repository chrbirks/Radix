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

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractSlider,
    QApplication,
    QFrame,
    QLabel,
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

from radix import __version__
from radix.engine.errors import CalcError, IncompleteError
from radix.engine.help import general_help_html
from radix.engine.values import Value
from radix.history.store import HistoryStore, StoredEntry
from radix.session import Session
from radix.ui_qt.completer import Completer
from radix.ui_qt.highlight import ExprHighlighter
from radix.ui_qt.history_model import HistoryDelegate, HistoryEntry, HistoryModel
from radix.ui_qt.input_edit import InputBar
from radix.ui_qt.inspector import Inspector
from radix.ui_qt.settings import app_settings, load_session, load_state, save_session, save_state
from radix.ui_qt.theme import LABEL_FAMILY, THEME_MODES, Palette, theme_mode_icon
from radix.ui_qt.zones import ZoneCaption, margin_wrap

PREVIEW_DEBOUNCE_MS = 100
INSPECTOR_MIN_H = 160  # scrolls below this rather than squeezing its contents
PANE_MIN_H = 120  # history/help/vars never collapse to nothing


class InspectorScroll(QScrollArea):
    """Scroll host that asks for the inspector's natural height.

    A bare QScrollArea reports a tiny sizeHint, so the layout would shrink the
    inspector to a permanent scrolling stub; deferring to the child keeps the
    panel at full size whenever the window has room. What the scroll area buys
    is the floor: below `INSPECTOR_MIN_H` the content scrolls instead of being
    squeezed past its minimum, which is what used to paint `pin result` on top
    of the bit grid at 64-bit word sizes.
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

SHORTCUT_HELP = """Keyboard shortcuts
  Enter        evaluate          Up / Down    recall history
  Tab          insert completion Ctrl+Space   open completions
  Ctrl+L       clear history     Ctrl+Shift+C copy last result
  F1 or help   this help         Esc          dismiss help
  Up/Down      scroll help/vars  PageUp/Down  page help/vars
  Alt+W        cycle word size   Alt+S        toggle signed/unsigned
  Alt+D        toggle deg/rad    Alt+N        cycle notation
  Alt+Shift+B  result base       Alt+T        always on top
  Alt+V        variables pane    del <name>   remove a variable
  Alt+Shift+F  show/hide float view (READOUT/REGISTER)
  Alt+P        pin last result as a channel
  Alt+I        show/hide inspector panel
  Alt+M        cycle theme (auto/light/dark)

  Line editing (input field)
  Ctrl+B/F     move char back/fwd  Alt+B/F      move word back/fwd
  Ctrl+E       end of line         Ctrl+W       delete word back
  Ctrl+D/H     delete char fwd/back"""


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
        self._pane_hid_inspector = False
        self._help_overview_shown = False
        self._did_initial_show = False
        self.last_result_text = ""
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
        self.history_view = QListView()
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

        self.help_pane = QTextEdit()
        self.help_pane.setObjectName("helpPane")
        self.help_pane.setReadOnly(True)
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

        self.result_caption = ZoneCaption("RESULT")
        self.result_caption.set_palette(palette)
        self.result_label = QLabel("—")
        self.result_label.setObjectName("resultValue")
        self.result_label.setProperty("dimmed", "true")
        self.result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.result_label.setWordWrap(True)

        self.input_bar = InputBar()
        self.input = self.input_bar.input
        self.preview = self.input_bar.preview
        self.input.setPlaceholderText("type an expression — help for the basics")
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
        self.highlighter = ExprHighlighter(self.input.document(), palette)
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
        self.intview.copied.connect(self._toast)
        self.intview.pin_requested.connect(lambda n: self._pin_value(Value(n), None))
        self.channels.to_input.connect(self._set_input)
        self.channels.copied.connect(self._toast)
        self.channels.ref_changed.connect(self._on_ref_changed)

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
            if geometry is not None:
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

        self.intview.show_value(None, session.word_size, session.signed)
        self.input.setFocus()

    # -- construction helpers ---------------------------------------------------

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        self.status_items: dict[str, QToolButton] = {}
        for key, handler in (
            ("angle", self._toggle_angle),
            ("word", self._cycle_word_size),
            ("sign", self._toggle_signed),
            ("base", self._cycle_int_base),
            ("notation", self._cycle_notation),
            ("float", self._toggle_float_view),
        ):
            chip = QToolButton()
            chip.setProperty("class", "modeChip")
            chip.setAutoRaise(True)
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # chips never steal focus
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(handler)
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
        self.version_label = QLabel(f"v{__version__}")
        self.version_label.setProperty("class", "statusItem")
        self.version_label.setToolTip("Radix version")
        bar.addPermanentWidget(self.version_label)
        self._refresh_status()

    def _build_shortcuts(self) -> None:
        for keys, handler in (
            ("Ctrl+L", self._clear_history_view),
            ("Ctrl+Shift+C", self._copy_result),
            ("F1", self._show_help),
            ("Alt+W", self._cycle_word_size),
            ("Alt+S", self._toggle_signed),
            ("Alt+D", self._toggle_angle),
            ("Alt+N", self._cycle_notation),
            ("Alt+Shift+B", self._cycle_int_base),
            ("Alt+Shift+F", self._toggle_float_view),
            ("Alt+T", self._toggle_always_on_top),
            ("Alt+V", self._toggle_vars),
            ("Alt+P", self._pin_last_result),
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
            self._toast(f"deleted {outcome.target}")
            self._refresh_vars_pane()
            if self.store is not None:
                save_state(self.session)
            return
        if outcome.kind == "csr":
            self.input.clear()
            if outcome.target is not None:
                self._toast(outcome.help_text or f"defined csr {outcome.target}")
                self._refresh_vars_pane()
                if self.store is not None:
                    save_state(self.session)
            else:
                self._show_vars()
            return
        if outcome.kind == "clear":
            self.model.clear()
            if self.store is not None:
                self.store.clear()
            self.input.clear()
            self._toast("cleared")
            self.intview.show_value(None, self.session.word_size, self.session.signed)
            self.inspector.show_viz_payload(None)
            self._refresh_vars_pane()
            if self.store is not None:
                save_state(self.session)
            return
        if outcome.value is None:
            return
        primary = self.session.format_value(outcome.value)
        prefix = f"{outcome.target} ← " if outcome.kind == "assign" else ""
        display = prefix + primary
        self.last_result_text = primary
        self.result_label.setText(display)
        self.result_label.setProperty("dimmed", "false")
        style = self.result_label.style()
        style.unpolish(self.result_label)
        style.polish(self.result_label)
        self.model.append(
            HistoryEntry(
                text.strip(),
                display,
                outcome.value.note or "",
                value=outcome.value,
                prefix=prefix,
                timestamp=time.time(),
            )
        )
        if self.store is not None:
            self.store.append(
                text.strip(),
                display,
                outcome.value.note or "",
                prefix=prefix,
                value=outcome.value,
            )
            save_state(self.session)
        self.history_view.scrollToBottom()
        self.recall_index = None
        self.input.clear()
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
            self._set_preview("press Enter to clear variables and history", "ok")
            return
        if outcome.value is None:
            self._set_preview(" ", "ok")
            return
        result = self.session.format_value(outcome.value)
        if outcome.kind == "assign":
            self._set_preview(outcome.normalized, "ok")
        else:
            self._set_preview(f"{outcome.normalized} = {result}", "ok")
        self._panel_follow(outcome.value)

    def _panel_follow(self, value: Value | None) -> None:
        """Point the integer panel at a previewed/committed value.

        Integers drive the editable bit grid; reals show the read-only
        IEEE-754 view (word size 32/64) or grey the panel (8/16).
        """
        self.inspector.show_viz_payload(value.viz if value is not None else None)
        number = value.number if value is not None else None
        self.channels.set_live(number if isinstance(number, int) else None)
        if isinstance(number, int):
            assert value is not None
            self.intview.show_value(
                number, self.session.word_size, self.session.signed, csr=value.csr
            )
            return
        float_views = (
            self.session.float_views_for(value)
            if value is not None and self.session.show_float_view
            else None
        )
        self.intview.show_value(
            None, self.session.word_size, self.session.signed, float_views=float_views
        )

    def _on_ref_changed(self) -> None:
        """Sync the armed channel (if any) into the integer panel's REF diff."""
        ref_index = self.channels.ref_index
        if ref_index is None:
            self.intview.set_reference(None, None)
        else:
            channel = self.channels.channels[ref_index]
            value = channel.value
            if value is not None and isinstance(value.number, int):
                self.intview.set_reference(channel.label, value.number)
            else:
                self.intview.set_reference(None, None)
        self.channels.set_live(self.intview.scratch if self.intview.active else None)

    def _set_preview(self, text: str, state: str) -> None:
        """Write the line under the input. `state` is "ok" | "error" | "toast"."""
        self._toast_active = state == "toast"  # a real preview supersedes a toast
        self.preview.setText(text)
        self.preview.setProperty("state", state)
        style = self.preview.style()
        style.unpolish(self.preview)
        style.polish(self.preview)

    def _show_error(self, exc: CalcError) -> None:
        # The offending span gets a wavy underline in the input itself (a
        # text caret under a differently-sized preview font never lines up).
        self.highlighter.set_error_span((exc.span.start, exc.span.end))
        self._set_preview(exc.message, "error")

    def _on_history_scroll_changed(self, value: int) -> None:
        self._history_follow_bottom = value >= self.history_view.verticalScrollBar().maximum()

    def _resync_history_scroll(self) -> None:
        # Re-checked here rather than at schedule time: a resize's layout
        # settles on the next event-loop tick, and by then the user may
        # already have scrolled away from the bottom.
        if self._history_follow_bottom:
            self.history_view.scrollToBottom()

    # -- history recall ---------------------------------------------------------

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.history_view and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._resync_history_scroll)
        if obj is self.input and event.type() == QEvent.Type.FocusOut:
            self.completer.hide()
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if self.completer.handle_key(event):
                return True
            if self._scroll_overlay_pane(event.key()):
                return True  # help/vars showing: these scroll it, not history
            if event.key() == Qt.Key.Key_Up:
                self._recall(-1)
                return True
            if event.key() == Qt.Key.Key_Down:
                self._recall(+1)
                return True
            if event.key() == Qt.Key.Key_Escape:
                if self.intview.clear_selection():  # bit-range selection first
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
            self.recall_index = len(entries) - 1
        else:
            self.recall_index += direction
        if self.recall_index < 0:
            self.recall_index = 0
        if self.recall_index >= len(entries):
            self.recall_index = None
            self.input.clear()
            return
        self.completer.suppress_next()  # recalled text must not pop completions
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
            text = entry.result[len(entry.prefix):] if entry.prefix else entry.result
            clipboard.setText(text)
            self._toast(f"copied {text}")
        elif action == "copy_expression":
            clipboard.setText(entry.expression)
            self._toast("expression copied")
        elif action in ("copy_hex", "copy_dec", "copy_bin") and entry.value is not None:
            text = self.session.format_value(entry.value, base=action.removeprefix("copy_"))
            clipboard.setText(text)
            self._toast(f"copied {text}")
        elif action == "recall":
            self._set_input(entry.expression)
        elif action == "delete":
            self.model.remove(row)
            self._persist_history()
            self._toast("entry deleted")
        elif action == "pin" and entry.value is not None:
            label = entry.prefix.partition(" ←")[0] if entry.prefix else None
            self._pin_value(entry.value, label)

    def _persist_history(self) -> None:
        if self.store is None:
            return
        self.store.rewrite(
            [
                StoredEntry(
                    e.expression,
                    e.result,
                    e.note,
                    e.timestamp,
                    value=e.value,
                    prefix=e.prefix,
                )
                for e in self.model.entries
            ]
        )

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
        self.history_view.setCurrentIndex(index)  # type: ignore[arg-type]
        self._panel_follow(entry.value)

    def _clear_inspect_lock(self, follow_ans: bool) -> None:
        self._inspect_locked = False
        self.history_view.clearSelection()
        if follow_ans:
            self._panel_follow(self.session.ans)

    def _set_input(self, text: str) -> None:
        self.completer.suppress_next()
        self.input.setText(text)
        self.input.setFocus()

    # -- channels rack ------------------------------------------------------------

    def _pin_value(self, value: Value, label: str | None) -> None:
        text = self.session.format_value(value)
        assigned = self.channels.pin(value, text, label)
        if assigned is None:
            self._toast("pinned rack full -- unpin one")
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

    def _after_setting_change(self) -> None:
        self._refresh_status()
        self._reformat_history()
        self._refresh_result_label()
        self.channels.refresh(self.session.format_value, self.session.word_size)
        if self.vars_pane.isVisibleTo(self):
            self._refresh_vars_pane()  # values honor the new base/notation
        if self.store is not None:
            save_session(self.session)
        # Re-render the current panel value under the new settings; never re-evaluate.
        self.intview.show_value(
            self.intview.scratch if self.intview.active else None,
            self.session.word_size,
            self.session.signed,
            csr=self.intview.csr,
        )
        self._update_preview()

    def _reformat_history(self) -> None:
        """Re-render history results under the current display settings."""
        self.model.reformat(self.session.format_value)

    def _refresh_result_label(self) -> None:
        """Sync the RESULT readout with the (possibly just-reformatted) last entry."""
        if not self.model.entries:
            return
        last = self.model.entries[-1]
        self.result_label.setText(last.result)
        self.result_label.setProperty("dimmed", "false")

    def _refresh_status(self) -> None:
        session = self.session
        texts = {
            "angle": "DEG" if session.angle_deg else "RAD",
            "word": f"{session.word_size}-bit",
            "sign": "signed" if session.signed else "unsigned",
            "base": session.int_base.upper(),
            "notation": session.notation.replace("eng_si", "eng·si").upper(),
            "float": "FLOAT ON" if session.show_float_view else "FLOAT OFF",
        }
        tips = {
            "angle": "angle unit — click or Alt+D",
            "word": "word size for bit ops — click or Alt+W",
            "sign": "signedness of >> and SGN row — click or Alt+S",
            "base": "integer result base for history & preview — click or Alt+B",
            "notation": "result notation — click or Alt+N",
            "float": "show IEEE-754 breakdown for real results — click or Alt+F",
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
        overlay = pane is not self.history_view
        if overlay and not self._pane_hid_inspector and self.inspector.isVisibleTo(self):
            self.inspector_scroll.setVisible(False)
            self._pane_hid_inspector = True
        elif not overlay and self._pane_hid_inspector:
            self.inspector_scroll.setVisible(True)
            self._pane_hid_inspector = False
        self.pane_stack.setCurrentWidget(pane)

    def _scroll_overlay_pane(self, key: int) -> bool:
        """Route scroll keys to help/vars, which never take focus themselves.

        The input line keeps focus at all times, so without this the help pane
        had no keyboard scrolling at all and Up/Down went to history recall —
        useless while reading a document taller than the screen.
        """
        pane = self.pane_stack.currentWidget()
        if pane is self.history_view:
            return False
        actions: dict[int, QAbstractSlider.SliderAction] = {
            Qt.Key.Key_Up: QAbstractSlider.SliderAction.SliderSingleStepSub,
            Qt.Key.Key_Down: QAbstractSlider.SliderAction.SliderSingleStepAdd,
            Qt.Key.Key_PageUp: QAbstractSlider.SliderAction.SliderPageStepSub,
            Qt.Key.Key_PageDown: QAbstractSlider.SliderAction.SliderPageStepAdd,
        }
        action = actions.get(key)
        if action is None:
            return False
        scrollbar = pane.verticalScrollBar()  # type: ignore[attr-defined]
        scrollbar.triggerAction(action)
        return True

    def _show_help(self, text: str | None = None) -> None:
        self._help_overview_shown = text is None
        if text is None:
            self._style_help_pane(self.palette_tokens)
            self.help_pane.setHtml(general_help_html(SHORTCUT_HELP))
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
            placeholder = QListWidgetItem("no variables -- assign with  x = 42")
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
        self.completer.suppress_next()
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
            if name in self.session.variables:
                del self.session.variables[name]
            else:
                del self.session.csrs[name]
            self._refresh_vars_pane()
            self._toast(f"deleted {name}")

    def _clear_history_view(self) -> None:
        self.model.clear()
        self._toast("history view cleared (variables kept — type clear to wipe)")

    def _copy_result(self) -> None:
        if self.last_result_text:
            QApplication.clipboard().setText(self.last_result_text)
            self._toast(f"copied {self.last_result_text}")

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
        self._update_theme_chip()
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
        super().resizeEvent(event)  # type: ignore[arg-type]
