"""Integer view: hex/dec/bin rows with per-base copy, plus clickable bit rows.

The panel shows a *scratch* value seeded from the latest integer result.
Clicking a bit cell toggles that bit of the scratch value, re-renders all
bases, and writes the new value into the input line as a hex literal. A new
result reseeds the scratch. Float results grey the panel.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
)
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
from radix.engine.viz import FixedPointViz, FloatBitsViz
from radix.ui_qt.theme import FONT_MICRO, Palette
from radix.ui_qt.zones import ZoneCaption, margin_wrap

CELL = 24
GAP = 4
NIBBLE_GAP = 10
HEX_H = 20  # strip above each cell row for per-nibble hex digits
INDEX_H = 18  # strip below each cell row for bit-index labels
FIELD_H = 20  # field-band strip above the hex strip, present only with a csr
FIELD_LABEL_GAP = 4  # breathing room between the field name and its bracket line
# When any field name is wider than its bracket span, every label in the grid
# tilts 45° (uniform strip, nothing elided to "…" over a 1-bit field). The
# tilted strip is a fixed height: names whose rise would exceed
# FIELD_LABEL_MAX_PX are elided instead of growing the grid further.
FIELD_ANGLE = 45
FIELD_LABEL_MAX_PX = 84  # vertical extent budget of a tilted label (~12 chars)
FIELD_ANGLED_H = FIELD_LABEL_MAX_PX + FIELD_LABEL_GAP + 4
ROW_H = HEX_H + CELL + GAP + INDEX_H
BYTE_WIDTH = 8 * (CELL + GAP) + 2 * NIBBLE_GAP  # one byte group incl. nibble gaps
LANE_ROWS = 5  # max simultaneous lanes (HEX/DEC/BIN, or HEX/VAL/SGN/EXP/MAN)
TOP_MARGIN = 8  # above the first row, so tall hex-digit labels don't clip the widget edge
GRID_INSET = 12  # left/right inset of the cell rows; matches the 12px margin_wrap gutter
BOTTOM_MARGIN = 4


@dataclass(frozen=True)
class BitBands:
    """Read-only three-band layout: MSB sign cell | middle band | low band.

    IEEE-754 (sign/exponent/mantissa) and Qm.n (sign/integer/fraction) are the
    same shape, so both drive the grid through this. `low_width` alone is
    enough — the middle band is whatever is left between it and the sign cell.
    """

    low_width: int  # mantissa bits / fraction bits
    names: tuple[str, str, str] = ("sign", "exponent", "mantissa")
    point_bit: int | None = None  # binary point sits left of this bit (-1: right of the LSB)
    bit_notes: tuple[str, ...] | None = None  # LSB-first per-bit weight text, for tooltips


def _views_of(packed: FloatBitsViz) -> FloatViews:
    """The same IEEE-754 decomposition under the formatter's field names."""
    return FloatViews(
        bits=packed.bits,
        width=packed.width,
        exp_width=packed.exp_width,
        man_width=packed.man_width,
        hex=packed.hex_text,
        sign_text=packed.sign_text,
        exponent_text=packed.exponent_text,
        mantissa_text=packed.mantissa_text,
    )


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
        # Set when showing a packed layout (IEEE-754 or Qm.n): cells get band
        # colors and become read-only.
        self.bands: BitBands | None = None
        # (name, msb, lsb) tuples, msb-descending, when a register field
        # layout is showing. Unlike float mode, cells stay clickable/editable.
        self.named_fields: tuple[tuple[str, int, int], ...] | None = None
        self._angled = False  # field labels tilted because one overflows its span
        self._field_heights: list[int] = []  # per-row field strip height, see _apply_height
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
        bands: BitBands | None = None,
        named_fields: tuple[tuple[str, int, int], ...] | None = None,
    ) -> None:
        self.value = value
        self.word_size = word_size
        self.enabled_look = enabled
        self.changed = changed
        self.bands = bands
        self.named_fields = named_fields
        self._apply_height()
        self.update()

    def _micro_font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(FONT_MICRO)
        return font

    def _field_segments(self) -> Iterator[tuple[int, str, int, int, bool]]:
        """(field_index, name, bit_left, bit_right, is_msb_segment) per drawn row.

        Walks each visible field (msb < word_size) row by row, yielding the
        highest/lowest bit of the part that lands on that row. The name is
        drawn only on the MSB-most segment; other rows get just the bracket.
        """
        assert self.named_fields is not None
        per_row = self._bits_per_row()
        for field_index, (name, msb, lsb) in enumerate(self.named_fields):
            if msb >= self.word_size:
                continue  # clipped by the current word size: not drawn
            pos_start = self.word_size - 1 - msb
            pos_end = self.word_size - 1 - lsb
            for row in range(self._rows()):
                row_start = row * per_row
                seg_start = max(pos_start, row_start)
                seg_end = min(pos_end, row_start + per_row - 1)
                if seg_start > seg_end:
                    continue
                bit_left = self.word_size - 1 - seg_start
                bit_right = self.word_size - 1 - seg_end
                yield field_index, name, bit_left, bit_right, seg_start == pos_start

    def _labels_overflow(self) -> bool:
        """True when some field name is wider than the span it would sit over."""
        if self.named_fields is None:
            return False
        fm = QFontMetrics(self._micro_font())
        for _i, name, bit_left, bit_right, is_msb in self._field_segments():
            if not is_msb:
                continue
            span = self._cell_rect(bit_right).right() - self._cell_rect(bit_left).left()
            if fm.horizontalAdvance(name) > span:
                return True
        return False

    def _band_of(self, bit: int) -> int:
        """0 (sign) / 1 (exponent, integer) / 2 (mantissa, fraction) for a bit."""
        assert self.bands is not None
        if bit == self.word_size - 1:
            return 0
        return 1 if bit >= self.bands.low_width else 2

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
        usable = max(self.width() - 2 * GRID_INSET, BYTE_WIDTH)
        bytes_fit = max(1, (usable + NIBBLE_GAP) // BYTE_WIDTH)
        return min(self.word_size, 8 * bytes_fit)

    def _rows(self) -> int:
        per_row = self._bits_per_row()
        return (self.word_size + per_row - 1) // per_row

    def _label_rise(self, fm: QFontMetrics, name: str) -> float:
        """Vertical extent of `name` drawn at FIELD_ANGLE, capped at the budget."""
        rad = math.radians(FIELD_ANGLE)
        rise = fm.horizontalAdvance(name) * math.sin(rad) + fm.ascent() * math.cos(rad)
        return min(float(FIELD_LABEL_MAX_PX), rise)

    @staticmethod
    def _label_anchor_x(text_w: float, x_left: float, x_right: float) -> float:
        """x where a tilted label's baseline starts.

        Centred over the span when it fits there; otherwise pinned over the
        first cell's centre so a long name over a 1-bit field runs off to the
        right instead of sliding over its left-hand neighbour.
        """
        footprint = text_w * math.cos(math.radians(FIELD_ANGLE))
        return max(x_left + CELL / 2, (x_left + x_right) / 2 - footprint / 2)

    def _measure_field_heights(self) -> list[int]:
        """Per-row field strip height.

        Horizontal labels: the slim FIELD_H everywhere. Tilted: each row is
        exactly as tall as its tallest label needs (up to FIELD_ANGLED_H, the
        point where names get elided instead), and rows without a label —
        a wrapped word's field-less upper row — keep the slim strip.
        """
        rows = self._rows()
        if self.named_fields is None:
            return [0] * rows
        heights = [FIELD_H] * rows
        if not self._angled:
            return heights
        fm = QFontMetrics(self._micro_font())
        per_row = self._bits_per_row()
        for _i, name, bit_left, _r, is_msb in self._field_segments():
            if not is_msb:
                continue
            row = (self.word_size - 1 - bit_left) // per_row
            needed = math.ceil(self._label_rise(fm, name)) + FIELD_LABEL_GAP + 4
            heights[row] = max(heights[row], needed)
        return heights

    def _field_h(self, row: int) -> int:
        """Height of the field strip above `row`'s hex digits (cached)."""
        return self._field_heights[row] if row < len(self._field_heights) else 0

    def _row_top(self, row: int) -> int:
        """y of the top of `row`'s field strip (or hex strip, without fields)."""
        return TOP_MARGIN + row * ROW_H + sum(self._field_heights[:row])

    def _grid_height(self) -> int:
        return self._row_top(self._rows()) + BOTTOM_MARGIN

    def _apply_height(self) -> None:
        # Span widths depend on the row wrap (hence on the widget width), so
        # the tilt decision and strip heights are re-taken whenever the
        # height is. Only x-geometry is read while measuring, so the stale
        # height cache is harmless until it is replaced here.
        self._angled = self._labels_overflow()
        self._field_heights = self._measure_field_heights()
        self.setMinimumHeight(self._grid_height())

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._apply_height()
        super().resizeEvent(event)

    def _row_span(self, row: int) -> tuple[int, int]:
        """(highest, lowest) bit index drawn on `row`."""
        per_row = self._bits_per_row()
        hi = self.word_size - 1 - row * per_row
        return hi, max(0, hi - per_row + 1)

    def _cell_rect(self, bit: int) -> QRectF:
        """Rect for a bit index (0 = LSB). MSB is top-left."""
        per_row = self._bits_per_row()
        pos = self.word_size - 1 - bit  # 0 for MSB
        row, col = divmod(pos, per_row)
        # Nibble gaps sit between bit 4k and bit 4k-1, counted from the row's
        # leftmost bit. For word sizes that are a multiple of 4 (every session
        # word size) this is exactly `col // 4`; packed layouts like Q2.3 are
        # the only case where the two differ.
        row_hi, _ = self._row_span(row)
        nibble_gaps = row_hi // 4 - bit // 4
        x = GRID_INSET + col * (CELL + GAP) + nibble_gaps * NIBBLE_GAP
        y = self._row_top(row) + self._field_h(row) + HEX_H
        return QRectF(x, y, CELL, CELL)

    def sizeHint(self) -> QSize:
        return QSize(2 * BYTE_WIDTH + 2 * GRID_INSET, self._grid_height())

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        p = self.palette_tokens
        on = QColor(p.bit_on if self.enabled_look else p.bit_off)
        off = QColor(p.bit_off)
        off.setAlphaF(0.6 if not self.enabled_look else 1.0)
        band_colors = (p.float_sign, p.float_exp, p.float_man)
        for bit in range(self.word_size):
            rect = self._cell_rect(bit)
            set_ = (self.value >> bit) & 1
            if self.bands is not None and self.enabled_look:
                color = QColor(band_colors[self._band_of(bit)])
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
        if self.bands is not None and self.bands.point_bit is not None:
            self._paint_binary_point(painter, self.bands.point_bit)
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
        # phosphor trace color when set). Walked per row so a group is never
        # split across the wrap, and so a word size that isn't a multiple of 4
        # (Qm.n formats only) still gets its leading partial digit.
        for row in range(self._rows()):
            row_hi, row_lo = self._row_span(row)
            hi = row_hi
            while hi >= row_lo:
                lo = max(row_lo, hi // 4 * 4)
                digit = (self.value >> lo) & ((1 << (hi - lo + 1)) - 1)
                msb_cell = self._cell_rect(hi)
                lsb_cell = self._cell_rect(lo)
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
                hi = lo - 1
        # Bit-index labels under each nibble's MSB cell (63, 59, … 3), plus bit 0.
        index_font = painter.font()
        index_font.setPixelSize(FONT_MICRO)
        painter.setFont(index_font)
        painter.setPen(QColor(self.palette_tokens.muted))
        for bit in range(self.word_size):
            if bit % 4 == 3 or bit == 0 or bit == self.word_size - 1:
                cell = self._cell_rect(bit)
                label_rect = QRectF(cell.left() - GAP, cell.bottom() + 1, CELL + 2 * GAP, INDEX_H)
                painter.drawText(label_rect, Qt.AlignmentFlag.AlignHCenter, str(bit))
        painter.end()

    def _paint_binary_point(self, painter: QPainter, point_bit: int) -> None:
        """Radix-point tick in the gap left of `point_bit` (-1: right of the LSB)."""
        if point_bit >= self.word_size:
            return
        if point_bit >= 0:
            cell = self._cell_rect(point_bit)
            left = self._cell_rect(point_bit + 1) if point_bit + 1 < self.word_size else None
            # Centre it in the real gap, which is a nibble gap at 4-bit boundaries;
            # a point landing at a row wrap falls back to the row's left edge.
            x = (
                (left.right() + cell.left()) / 2
                if left is not None and left.top() == cell.top()
                else cell.left() - GAP / 2
            )
        else:
            cell = self._cell_rect(0)
            x = cell.right() + GAP / 2
        painter.setPen(QPen(QColor(self.palette_tokens.text), 2))
        painter.drawLine(QPointF(x, cell.top() - 3), QPointF(x, cell.bottom() + 3))

    def _paint_field_bands(self, painter: QPainter) -> None:
        """Bracket + name over each row a field spans (dimension-line style).

        A field wrapping across rows draws its name once, on the row holding
        its MSB-most segment; other rows get only the bracket. Names sit
        horizontally inside their span, or — when any one of them would not
        fit — the whole strip tilts 45° (see `FIELD_ANGLE`).
        """
        assert self.named_fields is not None
        p = self.palette_tokens
        micro_font = self._micro_font()
        fm = QFontMetrics(micro_font)
        per_row = self._bits_per_row()
        for field_index, name, bit_left, bit_right, is_msb in self._field_segments():
            color = QColor(p.field_bands[field_index % len(p.field_bands)])
            row = (self.word_size - 1 - bit_left) // per_row
            left_rect = self._cell_rect(bit_left)
            right_rect = self._cell_rect(bit_right)
            y_top = self._row_top(row)
            y_line = y_top + self._field_h(row) - 4
            x_left, x_right = left_rect.left(), right_rect.right()
            painter.setPen(QPen(color, 1.5))
            painter.drawLine(QPointF(x_left, y_line), QPointF(x_right, y_line))
            painter.drawLine(QPointF(x_left, y_line), QPointF(x_left, y_line + 3))
            painter.drawLine(QPointF(x_right, y_line), QPointF(x_right, y_line + 3))
            if not is_msb:
                continue
            painter.setFont(micro_font)
            painter.setPen(color)
            if not self._angled:
                label_rect = QRectF(
                    x_left, y_top, x_right - x_left, y_line - y_top - FIELD_LABEL_GAP
                )
                text = fm.elidedText(name, Qt.TextElideMode.ElideRight, int(label_rect.width()))
                painter.drawText(
                    label_rect,
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                    text,
                )
                continue
            # Tilted: baseline rises to the upper-right from over the span.
            # Budget the run so it neither exceeds the strip height nor
            # leaves the widget's right edge (measured from the leftmost
            # possible anchor, the worst case). The glyph ascent projects
            # onto both axes too, so it is subtracted from each budget.
            rad = math.radians(FIELD_ANGLE)
            ascent = fm.ascent()
            x_min = x_left + CELL / 2
            avail = min(
                (FIELD_LABEL_MAX_PX - ascent * math.cos(rad)) / math.sin(rad),
                (self.width() - x_min - ascent * math.sin(rad) - 2) / math.cos(rad),
            )
            text = fm.elidedText(name, Qt.TextElideMode.ElideRight, int(avail))
            anchor_x = self._label_anchor_x(fm.horizontalAdvance(text), x_left, x_right)
            anchor = QPointF(anchor_x, y_line - FIELD_LABEL_GAP)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            painter.translate(anchor)
            painter.rotate(-FIELD_ANGLE)
            painter.drawText(QPointF(0, 0), text)
            painter.restore()

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
        if not self.enabled_look or self.bands is not None:  # packed layout: read-only
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
        if self.bands is not None:
            tip = f"bit {bit} = {state}    {self.bands.names[self._band_of(bit)]}"
            if self.bands.bit_notes is not None:
                tip += f", weight {self.bands.bit_notes[bit]}"
            self.setToolTip(tip)
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
        self._cursor_anchor: int | None = None  # Shift+arrow range origin
        self.float_mode: FloatViews | None = None  # read-only IEEE-754 display
        # Packed layouts a toolkit function produced, rendered here rather than
        # in a separate card so REGISTER always *is* the word being discussed.
        self.fixed_view: FixedPointViz | None = None  # fix()/unfix() Qm.n
        self.float_bits: FloatBitsViz | None = None  # float32()/float64() and their inverses
        self.csr: Csr | None = None  # field layout for the shown value
        # Argument separator for the one-shot `csr(value, SPEC)` form written
        # back to the input line. Read at emit time (the owner points it at
        # the session's decimal syntax) so it can never go stale.
        self.arg_sep: Callable[[], str] = lambda: ","

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

        # The slice readout is this row's only occupant and appears only while
        # a drag selection exists, so the row otherwise collapses to its bottom
        # margin and the grid sits a normal zone gap above PINNED.
        actions = QHBoxLayout()
        actions.setContentsMargins(12, 0, 12, 8)
        actions.addStretch(1)
        self.slice_label = QLabel("")
        self.slice_label.setProperty("class", "sliceNote")
        self.slice_label.setToolTip("drag across bit cells to read a field; Esc clears")
        self.slice_label.hide()
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
        fixed_view: FixedPointViz | None = None,
        float_bits: FloatBitsViz | None = None,
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
        self.fixed_view = fixed_view if value is None else None
        self.float_bits = float_bits if value is None else None
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
        if not self.active or self._packed_mode:
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
    def _packed_mode(self) -> bool:
        """A read-only layout is showing: IEEE-754 (view or result) or Qm.n."""
        return (
            self.float_mode is not None
            or self.fixed_view is not None
            or self.float_bits is not None
        )

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
        if self.fixed_view is not None:
            self._refresh_fixed(self.fixed_view)
            return
        if self.float_bits is not None:
            self._refresh_float(_views_of(self.float_bits), packed=self.float_bits)
            return
        if self.float_mode is not None:
            self._refresh_float(self.float_mode)
            return
        self.register_caption.set_text("REGISTER")
        views = integer_views(self.scratch, self.word_size)
        self._set_trunc_note(views.truncated and self.active, views.value_bits)
        dec_text = views.dec_unsigned
        if views.dec_signed != views.dec_unsigned:
            dec_text = f"{views.dec_unsigned}  ({views.dec_signed})"
        self._copy_texts = {
            "HEX": views.hex,
            "DEC": views.dec_unsigned,
            "BIN": views.binary,
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
        self._set_lanes(lanes, dimmed=not self.active)
        mask = (1 << self.word_size) - 1
        changed = self.changed & mask if self.active else 0
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
        # One field per row, as a rich-text table so every "=" lands in the
        # same column whatever the name lengths: name [range] | = | value.
        rows = []
        for field_index, f in enumerate(self.csr.fields):
            bracket = f"[{f.msb}]" if f.msb == f.lsb else f"[{f.msb}:{f.lsb}]"
            if f.msb >= self.word_size:
                muted = self.palette_tokens.muted
                rows.append(
                    f'<tr><td><span style="color:{muted}">{f.name}&nbsp;{bracket}</span></td>'
                    f'<td style="padding:0 6px; color:{muted}">=</td>'
                    f'<td><span style="color:{muted}">-</span></td></tr>'
                )
                continue
            value = (self._masked_scratch >> f.lsb) & ((1 << f.width) - 1)
            text = format_field_value(f, value)
            # Name colored to match its grid bracket, so the table and the
            # overlay above read as one mapping, not two separate legends.
            color = field_bands[field_index % len(field_bands)]
            rows.append(
                f'<tr><td><a href="{f.name}" style="color:{color}; text-decoration:none;">'
                f"{f.name}</a>&nbsp;{bracket}</td>"
                f'<td style="padding:0 6px">=</td>'
                f"<td>{text}</td></tr>"
            )
        self.field_table.setText(
            '<table cellspacing="0" cellpadding="0">' + "".join(rows) + "</table>"
        )

    def _on_field_link(self, name: str) -> None:
        if self.csr is None:
            return
        f = self.csr.field(name)
        if f is None:
            return
        self.grid_widget.set_selection((f.msb, f.lsb))
        self._update_slice_label()

    def _refresh_fixed(self, viz: FixedPointViz) -> None:
        """Read-only Qm.n mode: the raw word, banded sign/integer/fraction.

        Like float mode, the scratch value is untouched — the previous integer
        reappears intact once another result arrives.
        """
        total = viz.m + viz.n
        fmt = f"Q{viz.m}.{viz.n}"
        self.register_caption.set_text(f"REGISTER · {fmt}")
        self._set_trunc_note(False, 0)  # the Q word is the whole value
        dec_text = viz.dec_text
        if viz.dec_signed_text != viz.dec_text:
            dec_text = f"{viz.dec_text}  ({viz.dec_signed_text})"
        value_text = (
            f"{viz.stored_text}  (exact)"
            if viz.error_lsb == 0
            else f"{viz.exact_text} → {viz.stored_text}"
        )
        self._copy_texts = {
            "HEX": viz.hex_text,
            "DEC": viz.dec_text,
            fmt: viz.stored_text,
            "ERR": viz.error_text,
        }
        self._set_lanes(
            [
                ("HEX", viz.hex_text),
                ("DEC", dec_text),
                (fmt, value_text),
                ("ERR", f"{viz.error_text}  ({viz.error_lsb_text})"),
            ],
            dimmed=False,
        )
        self.grid_widget.set_state(
            viz.raw,
            total,
            True,
            bands=BitBands(
                low_width=min(viz.n, total - 1),
                names=("sign", "integer", "fraction"),
                point_bit=viz.n - 1 if viz.n else -1,
                bit_notes=viz.bit_weights,
            ),
        )
        self._update_slice_label()

    def _refresh_float(self, views: FloatViews, packed: FloatBitsViz | None = None) -> None:
        """Read-only IEEE-754 mode: bit pattern + decoded sign/exponent/mantissa.

        `packed` is set when a float32()/float64() call produced the pattern
        (rather than the FLOAT ON view of a plain real), and adds the stored
        value the format actually holds.

        The scratch value is untouched — leaving float mode restores the
        integer view exactly as it was.
        """
        self.register_caption.set_text(
            f"REGISTER · float{views.width}" if packed is not None else "REGISTER"
        )
        self._set_trunc_note(False, 0)  # the pattern is the whole value here
        self._copy_texts = {
            "HEX": views.hex,
            "SGN": views.sign_text,
            "EXP": views.exponent_text,
            "MAN": views.mantissa_text,
        }
        lanes: list[tuple[str, str]] = [("HEX", views.hex)]
        if packed is not None:
            value_text = packed.stored_text
            if packed.rounded and packed.exact_text != packed.stored_text:
                value_text += f"   (rounded from {packed.exact_text})"
            self._copy_texts["VAL"] = packed.stored_text
            lanes.append(("VAL", value_text))
        lanes += [
            ("SGN", views.sign_text),
            ("EXP", views.exponent_text),
            ("MAN", views.mantissa_text),
        ]
        self._set_lanes(lanes, dimmed=False)
        self.grid_widget.set_state(
            views.bits,
            views.width,
            True,
            bands=BitBands(low_width=views.man_width),
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
            self.slice_label.hide()
            return
        hi, lo, value, width = sliced
        hex_text = format_int_base(value, "hex", width)
        self.slice_label.setText(f"[{hi}:{lo}] = {hex_text} = {value} ({width} bits)")
        self.slice_label.show()

    def set_palette(self, palette: Palette) -> None:
        self.palette_tokens = palette
        self.readout_caption.set_palette(palette)
        self.register_caption.set_palette(palette)
        self.grid_widget.set_palette(palette)
        self._refresh()  # re-render the BIN highlight color

    # -- actions --------------------------------------------------------------

    def copy_base(self, base: str) -> None:
        if not self.active and not self._packed_mode:
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
            return
        literal = f"0x{self._masked_scratch:X}"
        # Under a csr layout the edit is written back as the decode expression
        # itself: the preview then re-derives the same layout instead of
        # reading a bare literal and dropping it.
        if self.csr is None:
            self.value_to_input.emit(literal)
        elif self.csr.name is not None:
            self.value_to_input.emit(f"{self.csr.name}({literal})")
        else:
            self.value_to_input.emit(f"csr({literal}{self.arg_sep()} {self.csr.spec_text()})")

