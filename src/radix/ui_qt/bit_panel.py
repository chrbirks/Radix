"""Integer view: hex/dec/bin rows with per-base copy, plus clickable bit rows.

The panel shows a *scratch* value seeded from the latest integer result.
Clicking a bit cell toggles that bit of the scratch value, re-renders all
bases, and writes the new value into the input line as a hex literal. A new
result reseeds the scratch. Float results grey the panel.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPaintEvent, QPen, QResizeEvent
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from radix.engine.csr import Csr, format_field_value
from radix.engine.formatter import FloatViews, format_int_base, integer_views
from radix.ui_qt.theme import FONT_MICRO, Palette
from radix.ui_qt.zones import ZoneCaption, margin_wrap

CELL = 24
GAP = 4
NIBBLE_GAP = 10
HEX_H = 20  # strip above each cell row for per-nibble hex digits
INDEX_H = 18  # strip below each cell row for bit-index labels
FIELD_H = 20  # field-band strip above the hex strip, present only with a csr
FIELD_LABEL_GAP = 4  # breathing room between the field name and its bracket line
ROW_H = HEX_H + CELL + GAP + INDEX_H
BYTE_WIDTH = 8 * (CELL + GAP) + 2 * NIBBLE_GAP  # one byte group incl. nibble gaps
LANE_ROWS = 4  # max simultaneous lanes (HEX/DEC/BIN/ASC, or HEX/SGN/EXP/MAN)
TOP_MARGIN = 8  # above the first row, so tall hex-digit labels don't clip the widget edge
BOTTOM_MARGIN = 4


class BitGrid(QWidget):
    """Clickable bit cells, MSB top-left.

    The grid fills the available width and wraps at byte boundaries, so every
    bit stays visible at any window width and word size (no clipping from
    stale size hints).
    """

    bit_toggled = Signal(int)  # bit index
    selection_changed = Signal()  # read .selection for the current (hi, lo)

    def __init__(self, palette: Palette) -> None:
        super().__init__()
        self.palette_tokens = palette
        self.word_size = 64
        self.value = 0
        self.changed = 0  # bits that flipped vs. the previous value (outlined)
        self.enabled_look = True
        self.selection: tuple[int, int] | None = None  # (hi, lo) drag-selected range
        # (exp_width, man_width) when showing an IEEE-754 pattern: cells get
        # sign/exponent/mantissa band colors and become read-only.
        self.float_fields: tuple[int, int] | None = None
        # (name, msb, lsb) tuples, msb-descending, when a register field
        # layout is showing. Unlike float mode, cells stay clickable/editable.
        self.named_fields: tuple[tuple[str, int, int], ...] | None = None
        self._hover_bit: int | None = None
        self._press_bit: int | None = None
        self._dragging = False
        # Keyboard cursor cell. The grid never takes focus (the input line
        # keeps it, always), so MainWindow forwards navigation keys here and
        # this is what they move — outlined in paintEvent when set.
        self.cursor_bit: int | None = None
        self.setMouseTracking(True)
        self._apply_height()

    def set_state(
        self,
        value: int,
        word_size: int,
        enabled: bool,
        changed: int = 0,
        float_fields: tuple[int, int] | None = None,
        named_fields: tuple[tuple[str, int, int], ...] | None = None,
    ) -> None:
        self.value = value
        self.word_size = word_size
        self.enabled_look = enabled
        self.changed = changed
        self.float_fields = float_fields
        self.named_fields = named_fields
        self._apply_height()
        self.update()

    def _field_of(self, bit: int) -> str:
        """"sign" / "exponent" / "mantissa" for a bit in float mode."""
        assert self.float_fields is not None
        _, man_width = self.float_fields
        if bit == self.word_size - 1:
            return "sign"
        return "exponent" if bit >= man_width else "mantissa"

    def _field_index_of(self, bit: int) -> int | None:
        """Index into `self.named_fields` of the field containing `bit`, if any.

        A field clipped by the current word size (`msb >= word_size`) never
        tints cells, consistent with its bracket not being drawn either.
        """
        if self.named_fields is None:
            return None
        for i, (_name, msb, lsb) in enumerate(self.named_fields):
            if msb < self.word_size and lsb <= bit <= msb:
                return i
        return None

    def set_palette(self, palette: Palette) -> None:
        self.palette_tokens = palette
        self.update()

    def _bits_per_row(self) -> int:
        usable = max(self.width() - 8, BYTE_WIDTH)
        bytes_fit = max(1, (usable + NIBBLE_GAP) // BYTE_WIDTH)
        return min(self.word_size, 8 * bytes_fit)

    def _rows(self) -> int:
        per_row = self._bits_per_row()
        return (self.word_size + per_row - 1) // per_row

    def _row_h(self) -> int:
        return ROW_H + (FIELD_H if self.named_fields else 0)

    def _apply_height(self) -> None:
        self.setMinimumHeight(self._rows() * self._row_h() + TOP_MARGIN + BOTTOM_MARGIN)

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._apply_height()
        super().resizeEvent(event)

    def _cell_rect(self, bit: int) -> QRectF:
        """Rect for a bit index (0 = LSB). MSB is top-left."""
        per_row = self._bits_per_row()
        pos = self.word_size - 1 - bit  # 0 for MSB
        row, col = divmod(pos, per_row)
        nibble_gaps = col // 4
        x = 4 + col * (CELL + GAP) + nibble_gaps * NIBBLE_GAP
        field_offset = FIELD_H if self.named_fields else 0
        y = TOP_MARGIN + row * self._row_h() + field_offset + HEX_H
        return QRectF(x, y, CELL, CELL)

    def sizeHint(self) -> QSize:
        return QSize(2 * BYTE_WIDTH, self._rows() * self._row_h() + TOP_MARGIN + BOTTOM_MARGIN)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        p = self.palette_tokens
        on = QColor(p.bit_on if self.enabled_look else p.bit_off)
        off = QColor(p.bit_off)
        off.setAlphaF(0.6 if not self.enabled_look else 1.0)
        field_colors = {"sign": p.float_sign, "exponent": p.float_exp, "mantissa": p.float_man}
        for bit in range(self.word_size):
            rect = self._cell_rect(bit)
            set_ = (self.value >> bit) & 1
            if self.float_fields is not None and self.enabled_look:
                color = QColor(field_colors[self._field_of(bit)])
                if not set_:
                    color.setAlphaF(0.22)
                brush = color
            elif self.named_fields is not None and self.enabled_look:
                idx = self._field_index_of(bit)
                if idx is not None:
                    color = QColor(p.field_bands[idx % len(p.field_bands)])
                    if not set_:
                        color.setAlphaF(0.22)
                    brush = color
                else:
                    brush = on if set_ else off
            else:
                brush = on if set_ else off
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(brush)
            painter.drawRoundedRect(rect, 2, 2)
        # Drag-selected range: translucent cursor-amber band + text-color
        # outline (visible over both set and unset cells).
        if self.enabled_look and self.selection is not None:
            hi, lo = self.selection
            band = QColor(p.bit_changed)
            band.setAlphaF(0.25)
            painter.setBrush(band)
            painter.setPen(QPen(QColor(p.text), 1.5))
            for bit in range(lo, min(hi, self.word_size - 1) + 1):
                painter.drawRoundedRect(self._cell_rect(bit).adjusted(-1, -1, 1, 1), 3, 3)
        if self.cursor_bit is not None and self.enabled_look:
            # Accent = the interaction channel, so the keyboard cursor reads as
            # "you are here" and never as data (bit_on) or a measurement span
            # (bit_changed, the drag selection drawn just above).
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(p.accent), 2))
            painter.drawRoundedRect(self._cell_rect(self.cursor_bit).adjusted(-2, -2, 2, 2), 4, 4)
        if self.named_fields is not None:
            self._paint_field_bands(painter)
        label_font = painter.font()
        label_font.setPixelSize(16)
        painter.setFont(label_font)
        # Per-nibble hex digit above each 4-cell group (muted when zero,
        # phosphor trace color when set).
        for nibble in range(self.word_size // 4):
            digit = (self.value >> (4 * nibble)) & 0xF
            msb_cell = self._cell_rect(4 * nibble + 3)
            lsb_cell = self._cell_rect(4 * nibble)
            hex_rect = QRectF(
                msb_cell.left(),
                msb_cell.top() - HEX_H,
                lsb_cell.right() - msb_cell.left(),
                HEX_H - 2,
            )
            strong = self.enabled_look and digit != 0
            painter.setPen(QColor(p.bit_on if strong else p.muted))
            painter.drawText(
                hex_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                f"{digit:X}",
            )
        # Bit-index labels under each nibble's MSB cell (63, 59, … 3), plus bit 0.
        index_font = painter.font()
        index_font.setPixelSize(FONT_MICRO)
        painter.setFont(index_font)
        painter.setPen(QColor(self.palette_tokens.muted))
        for bit in range(self.word_size):
            if bit % 4 == 3 or bit == 0:
                cell = self._cell_rect(bit)
                label_rect = QRectF(cell.left() - GAP, cell.bottom() + 1, CELL + 2 * GAP, INDEX_H)
                painter.drawText(label_rect, Qt.AlignmentFlag.AlignHCenter, str(bit))
        painter.end()

    def _paint_field_bands(self, painter: QPainter) -> None:
        """Bracket + name over each row a field spans (dimension-line style).

        A field wrapping across rows draws its name once, on the row holding
        its MSB-most segment; other rows get only the bracket.
        """
        assert self.named_fields is not None
        p = self.palette_tokens
        per_row = self._bits_per_row()
        rows = self._rows()
        micro_font = QFont(painter.font())
        micro_font.setPixelSize(FONT_MICRO)
        for field_index, (name, msb, lsb) in enumerate(self.named_fields):
            if msb >= self.word_size:
                continue  # clipped by the current word size: not drawn
            color = QColor(p.field_bands[field_index % len(p.field_bands)])
            pos_start = self.word_size - 1 - msb
            pos_end = self.word_size - 1 - lsb
            for row in range(rows):
                row_start = row * per_row
                row_end = row_start + per_row - 1
                seg_start = max(pos_start, row_start)
                seg_end = min(pos_end, row_end)
                if seg_start > seg_end:
                    continue
                bit_left = self.word_size - 1 - seg_start
                bit_right = self.word_size - 1 - seg_end
                left_rect = self._cell_rect(bit_left)
                right_rect = self._cell_rect(bit_right)
                y_top = TOP_MARGIN + row * self._row_h()
                y_line = y_top + FIELD_H - 4
                x_left, x_right = left_rect.left(), right_rect.right()
                painter.setPen(QPen(color, 1.5))
                painter.drawLine(QPointF(x_left, y_line), QPointF(x_right, y_line))
                painter.drawLine(QPointF(x_left, y_line), QPointF(x_left, y_line + 3))
                painter.drawLine(QPointF(x_right, y_line), QPointF(x_right, y_line + 3))
                if seg_start == pos_start:
                    painter.setFont(micro_font)
                    painter.setPen(color)
                    label_rect = QRectF(
                        x_left, y_top, x_right - x_left, y_line - y_top - FIELD_LABEL_GAP
                    )
                    text = painter.fontMetrics().elidedText(
                        name, Qt.TextElideMode.ElideRight, int(label_rect.width())
                    )
                    painter.drawText(
                        label_rect,
                        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                        text,
                    )

    def _bit_at(self, pos: QPointF) -> int | None:
        for bit in range(self.word_size):
            if self._cell_rect(bit).contains(pos):
                return bit
        return None

    def set_selection(self, selection: tuple[int, int] | None) -> None:
        if selection == self.selection:
            return
        self.selection = selection
        self.selection_changed.emit()
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.enabled_look or self.float_fields is not None:  # float view: read-only
            return
        self._press_bit = self._bit_at(event.position())
        self._dragging = False
        if self._press_bit is None:
            self.set_selection(None)  # click outside the cells clears the range

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        bit = self._bit_at(event.position())
        # Drag with the left button held: extend the (hi, lo) selection.
        if (
            self.enabled_look
            and self._press_bit is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            if bit is not None and bit != self._press_bit:
                self._dragging = True
            if self._dragging and bit is not None:
                self.set_selection((max(bit, self._press_bit), min(bit, self._press_bit)))
        if bit == self._hover_bit:
            return
        self._hover_bit = bit
        if bit is None or not self.enabled_look:
            self.setToolTip("")
            return
        state = (self.value >> bit) & 1
        if self.float_fields is not None:
            self.setToolTip(f"bit {bit} = {state}    {self._field_of(bit)}")
        elif self.named_fields is not None and (idx := self._field_index_of(bit)) is not None:
            name, msb, lsb = self.named_fields[idx]
            self.setToolTip(f"bit {bit} = {state}    {name}[{msb}:{lsb}]")
        else:
            self.setToolTip(
                f"bit {bit} = {state}    2^{bit} = {1 << bit}    byte {bit // 8}, nibble {bit // 4}"
            )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self.enabled_look and self._press_bit is not None and not self._dragging:
            self.set_selection(None)  # a plain click both toggles and deselects
            self.bit_toggled.emit(self._press_bit)
        self._press_bit = None
        self._dragging = False


class IntegerView(QWidget):
    """The whole bottom panel: base rows + bit grid + actions."""

    value_to_input = Signal(str)
    copied = Signal(str)  # human description for the status-bar toast
    pin_requested = Signal(int)  # masked scratch value, to pin as a channel

    def __init__(self, palette: Palette, clipboard_setter: Callable[[str], None]) -> None:
        super().__init__()
        self.setObjectName("intview")
        self.palette_tokens = palette
        self._clipboard = clipboard_setter
        self.scratch = 0
        self.changed = 0  # bits that flipped vs. the previously shown value
        self.word_size = 64
        self.signed = False
        self.active = False
        self._ref: tuple[str, int] | None = None  # armed channel: (label, value)
        self._cursor_anchor: int | None = None  # Shift+arrow range origin
        self.float_mode: FloatViews | None = None  # read-only IEEE-754 display
        self.csr: Csr | None = None  # field layout for the shown value

        self.rows: dict[str, tuple[QLabel, QLabel]] = {}
        self._copy_texts: dict[str, str] = {}
        self._row_keys: list[str | None] = [None] * LANE_ROWS
        self._row_widgets: list[tuple[QLabel, QLabel, QPushButton]] = []
        self.readout_caption = ZoneCaption("READOUT")
        self.readout_caption.set_palette(palette)
        self.register_caption = ZoneCaption("REGISTER")
        self.register_caption.set_palette(palette)
        # Sits directly above the lanes it qualifies: every lane below masks to
        # the word size, so without this a value too wide for the word reads as
        # a complete answer that silently disagrees with RESULT.
        self.trunc_note = QLabel("")
        self.trunc_note.setProperty("class", "truncNote")
        self.trunc_note.setWordWrap(True)
        self.trunc_note.setVisible(False)
        grid = QGridLayout()
        grid.setContentsMargins(12, 8, 12, 4)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        for i in range(LANE_ROWS):
            name = QLabel("")
            name.setProperty("class", "laneName")
            value = QLabel("")
            value.setProperty("class", "laneValue")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setWordWrap(True)  # BIN at 64-bit is ~80 chars wide; wrap at nibble gaps
            copy_btn = QPushButton("copy")
            copy_btn.setProperty("class", "copyBtn")
            copy_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            copy_btn.clicked.connect(lambda _=False, row=i: self._copy_row(row))
            grid.addWidget(name, i, 0)
            grid.addWidget(value, i, 1)
            grid.addWidget(copy_btn, i, 2)
            grid.setColumnStretch(1, 1)
            self._row_widgets.append((name, value, copy_btn))

        self.grid_widget = BitGrid(palette)
        self.grid_widget.bit_toggled.connect(self.toggle_bit)
        self.grid_widget.selection_changed.connect(self._update_slice_label)

        self.field_table = QLabel("")
        self.field_table.setObjectName("fieldTable")
        self.field_table.setTextFormat(Qt.TextFormat.RichText)
        self.field_table.setWordWrap(True)  # long layouts must wrap, never clip at the edge
        self.field_table.linkActivated.connect(self._on_field_link)
        self.field_table.setVisible(False)

        actions = QHBoxLayout()
        actions.setContentsMargins(12, 0, 12, 8)
        self.pin_btn = QPushButton("pin result")
        self.pin_btn.setProperty("class", "copyBtn")
        self.pin_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pin_btn.clicked.connect(self._emit_pin_requested)
        actions.addWidget(self.pin_btn)
        self.delta_label = QLabel("")
        self.delta_label.setProperty("class", "deltaNote")
        self.delta_label.setToolTip("set bits gained/lost vs. the previous value")
        actions.addWidget(self.delta_label)
        actions.addStretch(1)
        self.slice_label = QLabel("")
        self.slice_label.setProperty("class", "sliceNote")
        self.slice_label.setToolTip("drag across bit cells to read a field; Esc clears")
        actions.addWidget(self.slice_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(margin_wrap(self.readout_caption, 12))
        layout.addWidget(margin_wrap(self.trunc_note, 12))
        layout.addLayout(grid)
        layout.addWidget(margin_wrap(self.register_caption, 12))
        layout.addWidget(self.grid_widget)
        layout.addWidget(margin_wrap(self.field_table, 12))
        layout.addLayout(actions)

    # -- state ---------------------------------------------------------------

    def show_value(
        self,
        value: int | None,
        word_size: int,
        signed: bool,
        float_views: FloatViews | None = None,
        csr: Csr | None = None,
    ) -> None:
        # scratch is kept unmasked: cycling the word size must only change how
        # the value is *displayed*, never destroy its upper bits.
        # A range selection only survives a same-value re-render (settings
        # cycling aside, positions and the readout would go stale).
        if word_size != self.word_size or value is None or value != self.scratch:
            self.grid_widget.set_selection(None)
        self.word_size = word_size
        self.signed = signed
        self.float_mode = float_views if value is None else None
        self.csr = csr
        if value is None:  # nothing editable left for the cursor to sit on
            self.stop_cursor()
        was_active = self.active
        self.active = value is not None
        if value is not None:
            if not was_active:
                self.changed = 0  # first value after a grey spell: no diff to show
            elif value != self.scratch:
                self.changed = value ^ self.scratch
            self.scratch = value
        self._refresh()

    def set_reference(self, label: str | None, value: int | None) -> None:
        if label is None:
            self._ref = None
        else:
            assert value is not None
            self._ref = (label, value)
        self._refresh()

    def toggle_bit(self, bit: int) -> None:
        self.grid_widget.set_selection(None)  # a bit edit invalidates the range readout
        self.scratch ^= 1 << bit
        self.changed = 1 << bit
        self._refresh()
        self._emit_to_input()  # the input line always reflects the edited value

    def clear_selection(self) -> bool:
        """Clear the drag-selected bit range; True if there was one (for Esc)."""
        had = self.grid_widget.selection is not None
        self.grid_widget.set_selection(None)
        return had

    # -- keyboard cursor ---------------------------------------------------------
    #
    # The bit grid was mouse-only: toggling a bit or reading a field out of a
    # range needed a click or a drag, in an app whose stated contract is that
    # everything is reachable from the keyboard. The input line keeps focus at
    # all times, so MainWindow forwards the navigation keys here rather than
    # making the grid a focus target.

    @property
    def cursor_bit(self) -> int | None:
        return self.grid_widget.cursor_bit

    def start_cursor(self) -> bool:
        """Place the cursor (on the MSB) if there is an editable grid. """
        if not self.active or self.float_mode is not None:
            return False
        if self.grid_widget.cursor_bit is None:
            self._set_cursor(self.word_size - 1)
        return True

    def stop_cursor(self) -> None:
        self._cursor_anchor = None
        self.grid_widget.cursor_bit = None
        self.grid_widget.update()

    def _set_cursor(self, bit: int) -> None:
        self.grid_widget.cursor_bit = max(0, min(bit, self.word_size - 1))
        self.grid_widget.update()

    def move_cursor(self, delta: int, extend: bool) -> None:
        """Step the cursor by `delta` bit positions (+1 = toward the LSB).

        With `extend`, the move drags a range out from the anchor, which is
        the keyboard equivalent of the mouse drag that reads out a field.
        """
        if self.grid_widget.cursor_bit is None:
            return
        if extend and self._cursor_anchor is None:
            self._cursor_anchor = self.grid_widget.cursor_bit
        target = self.grid_widget.cursor_bit - delta  # bit indices run right-to-left
        self._set_cursor(target)
        moved = self.grid_widget.cursor_bit
        if extend:
            assert self._cursor_anchor is not None
            self.grid_widget.set_selection(
                (max(moved, self._cursor_anchor), min(moved, self._cursor_anchor))
            )
            self._update_slice_label()
        else:
            self._cursor_anchor = None
            self.grid_widget.set_selection(None)
            self._update_slice_label()

    def bits_per_row(self) -> int:
        return self.grid_widget._bits_per_row()

    def toggle_cursor_bit(self) -> None:
        if self.grid_widget.cursor_bit is None:
            return
        bit = self.grid_widget.cursor_bit
        self.toggle_bit(bit)  # clears the selection, re-renders, updates the input
        self._set_cursor(bit)  # ...but the cursor stays where the user put it
        self._cursor_anchor = None

    @property
    def _masked_scratch(self) -> int:
        return self.scratch & ((1 << self.word_size) - 1)

    def _set_lanes(self, lanes: list[tuple[str, str]], dimmed: bool) -> None:
        """Rebuild `self.rows` from an ordered (key, value_text) list.

        Reuses the fixed pool of row widgets — extra rows beyond `len(lanes)`
        are hidden rather than destroyed.
        """
        self.rows = {}
        self._row_keys = [None] * LANE_ROWS
        for i, (name_label, value_label, copy_btn) in enumerate(self._row_widgets):
            if i >= len(lanes):
                name_label.hide()
                value_label.hide()
                copy_btn.hide()
                continue
            key, text = lanes[i]
            name_label.show()
            value_label.show()
            copy_btn.show()
            name_label.setText(key)
            value_label.setText(text)
            value_label.setToolTip(text)
            # `copy_base` refuses on a dimmed panel, so the button has to look
            # refused too — an enabled control that does nothing reads as a bug.
            copy_btn.setEnabled(not dimmed)
            for w in (name_label, value_label):
                w.setProperty("dimmed", "true" if dimmed else "false")
                w.style().unpolish(w)
                w.style().polish(w)
            self._row_keys[i] = key
            self.rows[key] = (name_label, value_label)

    def _copy_row(self, row: int) -> None:
        key = self._row_keys[row]
        if key is not None:
            self.copy_base(key)

    def _refresh(self) -> None:
        if self.float_mode is not None:
            self._refresh_float(self.float_mode)
            return
        views = integer_views(self.scratch, self.word_size)
        self._set_trunc_note(views.truncated and self.active, views.value_bits)
        self._sync_pin_button()
        dec_text = views.dec_unsigned
        if views.dec_signed != views.dec_unsigned:
            dec_text = f"{views.dec_unsigned}  ({views.dec_signed})"
        self._copy_texts = {
            "HEX": views.hex,
            "DEC": views.dec_unsigned,
            "BIN": views.binary,
            "ASC": views.ascii,
        }
        placeholder = "—"
        # Set bits rendered in the same phosphor/trace color as the bit grid's
        # asserted cells, so the two views read as one instrument, not two.
        # Displayed with space-separated nibble groups (copy keeps the
        # canonical "_" grouping) so QLabel can wrap the line at 64-bit
        # word sizes instead of overflowing the panel.
        bin_display = views.binary.replace("_", " ")
        bin_text = bin_display.replace(
            "1", f'<span style="color:{self.palette_tokens.bit_on}">1</span>'
        )
        lanes = [
            ("HEX", views.hex if self.active else placeholder),
            ("DEC", dec_text if self.active else placeholder),
            ("BIN", bin_text if self.active else placeholder),
        ]
        if any(ch != "." for ch in views.ascii):
            lanes.append(("ASC", views.ascii if self.active else placeholder))
        self._set_lanes(lanes, dimmed=not self.active)
        mask = (1 << self.word_size) - 1
        changed = self.changed & mask if self.active else 0
        if self._ref is not None and self.active:
            ref_label, ref_value = self._ref
            ref_masked = ref_value & mask
            diff = self._masked_scratch ^ ref_masked
            gained = (self._masked_scratch & diff).bit_count()
            lost = (~self._masked_scratch & diff).bit_count()
            self.delta_label.setText(f"Δ vs {ref_label} +{gained} -{lost}")
        elif changed:
            gained = (self._masked_scratch & changed).bit_count()
            lost = (~self._masked_scratch & changed).bit_count()
            self.delta_label.setText(f"Δ +{gained} -{lost}")
        else:
            self.delta_label.setText("")
        named_fields = (
            tuple((f.name, f.msb, f.lsb) for f in self.csr.fields)
            if self.csr
            else None
        )
        self.grid_widget.set_state(
            self._masked_scratch, self.word_size, self.active, changed, named_fields=named_fields
        )
        self._update_slice_label()
        self._refresh_field_table()

    def _sync_pin_button(self) -> None:
        """`_emit_pin_requested` needs an integer scratch; say so up front.

        Float view and the empty panel both leave it inert, and Alt+P already
        answers "nothing to pin" — the button should not look more capable
        than the shortcut it duplicates.
        """
        self.pin_btn.setEnabled(self.active)
        self.pin_btn.setToolTip("" if self.active else "no integer result to pin")

    def _set_trunc_note(self, truncated: bool, value_bits: int) -> None:
        self.trunc_note.setVisible(truncated)
        if not truncated:
            self.trunc_note.setText("")
            return
        self.trunc_note.setText(
            f"truncated — low {self.word_size} bits of a {value_bits}-bit value"
        )
        self.trunc_note.setToolTip(
            "the lanes and bit grid below are masked to the word size; "
            "cycle it with Alt+W to see the whole value"
        )

    def _refresh_field_table(self) -> None:
        if self.csr is None or not self.active:
            self.field_table.setVisible(False)
            return
        self.field_table.setVisible(True)
        field_bands = self.palette_tokens.field_bands
        parts = []
        for field_index, f in enumerate(self.csr.fields):
            bracket = f"[{f.msb}]" if f.msb == f.lsb else f"[{f.msb}:{f.lsb}]"
            if f.msb >= self.word_size:
                parts.append(
                    f'<span style="color:{self.palette_tokens.muted}">'
                    f"{f.name}&nbsp;{bracket}&nbsp;=&nbsp;-</span>"
                )
                continue
            value = (self._masked_scratch >> f.lsb) & ((1 << f.width) - 1)
            text = format_field_value(f, value)
            # Name colored to match its grid bracket, so the table and the
            # overlay above read as one mapping, not two separate legends.
            color = field_bands[field_index % len(field_bands)]
            # Non-breaking inside an entry: the wrap has to fall between fields,
            # never between a name and its bracket ("CMD" / "[7:0] = 0xF3").
            parts.append(
                f'<a href="{f.name}" style="color:{color}; text-decoration:none;">{f.name}</a>'
                f"&nbsp;{bracket}&nbsp;=&nbsp;{text}"
            )
        # Two non-breaking spaces for the gutter plus one real space: the only
        # place the line is allowed to wrap is between whole entries. All
        # non-breaking (as it was) would push the last field off the edge
        # instead of wrapping it.
        self.field_table.setText("&nbsp;&nbsp; ".join(parts))

    def _on_field_link(self, name: str) -> None:
        if self.csr is None:
            return
        f = self.csr.field(name)
        if f is None:
            return
        self.grid_widget.set_selection((f.msb, f.lsb))
        self._update_slice_label()

    def _refresh_float(self, views: FloatViews) -> None:
        """Read-only IEEE-754 mode: bit pattern + decoded sign/exponent/mantissa.

        The scratch value is untouched — leaving float mode restores the
        integer view exactly as it was.
        """
        self._set_trunc_note(False, 0)  # the pattern is the whole value here
        self._sync_pin_button()
        self._copy_texts = {
            "HEX": views.hex,
            "SGN": views.sign_text,
            "EXP": views.exponent_text,
            "MAN": views.mantissa_text,
        }
        lanes = [
            ("HEX", views.hex),
            ("SGN", views.sign_text),
            ("EXP", views.exponent_text),
            ("MAN", views.mantissa_text),
        ]
        self._set_lanes(lanes, dimmed=False)
        self.delta_label.setText("")
        self.grid_widget.set_state(
            views.bits,
            views.width,
            True,
            float_fields=(views.exp_width, views.man_width),
        )
        self._update_slice_label()

    def _selected_slice(self) -> tuple[int, int, int, int] | None:
        """(hi, lo, value, width) of the drag-selected field, if any."""
        if self.grid_widget.selection is None:
            return None
        hi, lo = self.grid_widget.selection
        width = hi - lo + 1
        value = (self._masked_scratch >> lo) & ((1 << width) - 1)
        return hi, lo, value, width

    def _update_slice_label(self) -> None:
        sliced = self._selected_slice()
        if sliced is None or not self.active:
            self.slice_label.setText("")
            return
        hi, lo, value, width = sliced
        hex_text = format_int_base(value, "hex", width)
        self.slice_label.setText(f"[{hi}:{lo}] = {hex_text} = {value} ({width} bits)")

    def set_palette(self, palette: Palette) -> None:
        self.palette_tokens = palette
        self.readout_caption.set_palette(palette)
        self.register_caption.set_palette(palette)
        self.grid_widget.set_palette(palette)
        self._refresh()  # re-render the BIN highlight color

    # -- actions --------------------------------------------------------------

    def copy_base(self, base: str) -> None:
        if not self.active and self.float_mode is None:
            return
        self._clipboard(self._copy_texts[base])  # plain text, never the rich-text markup
        self.copied.emit(f"{base} copied")

    def _emit_to_input(self) -> None:
        if not self.active:
            return
        sliced = self._selected_slice()
        if sliced is not None:
            hi, lo, _, _ = sliced
            self.value_to_input.emit(f"0x{self._masked_scratch:X}[{hi}:{lo}]")
        else:
            self.value_to_input.emit(f"0x{self._masked_scratch:X}")

    def _emit_pin_requested(self) -> None:
        if not self.active:
            return
        self.pin_requested.emit(self._masked_scratch)
