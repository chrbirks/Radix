"""The channels rack: a scope-instrument bank of pinned values.

Up to `MAX_CHANNELS` values ("C1", "C2", … or a variable name for pinned
assignments) sit in compact strips — slot label, formatted text, and a mini
one-row bit strip for integers. Persisted via QSettings as a JSON blob;
`main_window.py` owns save/restore, this module only (de)serializes its own
state (`to_json`/`restore`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QVBoxLayout, QWidget

from radix.engine.values import Value
from radix.ui_qt.theme import Palette

MAX_CHANNELS = 8
MINI_STRIP_H = 12
STRIP_PAD = 6
MINI_NIBBLE_GAP = 3
MINI_CELL_GAP = 1
RACK_GUTTER = 12  # matches the 12px side gutter the other inspector zones use


@dataclass
class Channel:
    """`label` is "C1"... (lowest unused number, never renumbered on unpin)
    or an assignment's variable name used verbatim. `value` is None for
    text-only restores (non-int channels don't reconstruct a Value)."""

    label: str
    value: Value | None
    text: str


class MiniBitStrip(QWidget):
    """Paint-only single-row bit strip, MSB left. No text, no metrics, no
    mouse handling — purely decorative geometry driven off widget width."""

    def __init__(self, palette: Palette) -> None:
        super().__init__()
        self.palette_tokens = palette
        self.word_size = 64
        self.value = 0
        self._on_color: str | None = None
        self.setFixedHeight(MINI_STRIP_H)

    def set_state(self, value: int, word_size: int) -> None:
        self.value = value
        self.word_size = word_size
        self.update()

    def set_color(self, color: str | None) -> None:
        """Override the "set bit" color (None reverts to `palette.bit_on`)."""
        self._on_color = color
        self.update()

    def set_palette(self, palette: Palette) -> None:
        self.palette_tokens = palette
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        p = self.palette_tokens
        on = QColor(self._on_color if self._on_color is not None else p.bit_on)
        off = QColor(p.bit_off)
        word_size = max(1, self.word_size)
        nibble_gaps = max(0, word_size // 4 - 1)
        cell_gaps = word_size - 1
        usable = max(
            0.0,
            self.width() - nibble_gaps * MINI_NIBBLE_GAP - cell_gaps * MINI_CELL_GAP,
        )
        cell_w = usable / word_size
        painter.setPen(Qt.PenStyle.NoPen)
        x = 0.0
        for pos in range(word_size):
            bit = word_size - 1 - pos  # MSB first
            set_ = (self.value >> bit) & 1
            painter.setBrush(on if set_ else off)
            painter.drawRect(QRectF(x, 0, cell_w, self.height()))
            x += cell_w
            if pos != word_size - 1:
                x += MINI_CELL_GAP
                if pos % 4 == 3:
                    x += MINI_NIBBLE_GAP
        painter.end()


class ChannelStrip(QWidget):
    """One pinned channel: slot label + value text + (hidden) REF tag, over
    a mini bit strip for integer channels. Left-click emits `clicked`
    (WP4 arms REF from it); context menu offers send-to-input/copy/REF/unpin."""

    clicked = Signal()
    to_input = Signal(str)
    copied = Signal(str)
    unpin_requested = Signal()
    ref_toggled = Signal()

    def __init__(
        self,
        palette: Palette,
        channel: Channel,
        word_size: int,
        is_ref: bool,
        clipboard_setter: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.setProperty("class", "chanStrip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.palette_tokens = palette
        self.channel = channel
        self.word_size = word_size
        self.is_ref = is_ref
        self._clipboard = clipboard_setter

        self._live: int | None = None

        self.slot_label = QLabel(channel.label)
        self.slot_label.setProperty("class", "chanSlot")
        self.value_label = QLabel(channel.text)
        self.value_label.setProperty("class", "chanValue")
        self.ref_tag = QLabel("REF")
        self.ref_tag.setProperty("class", "refTag")
        self.ref_tag.hide()
        self.xor_label = QLabel("")
        self.xor_label.setProperty("class", "refTag")
        self.xor_label.hide()
        self.bitstrip = MiniBitStrip(palette)
        self.diff_strip = MiniBitStrip(palette)
        self.diff_strip.set_color(palette.bit_changed)
        self.diff_strip.hide()
        self._update_bitstrip()

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.slot_label)
        top.addWidget(self.value_label, 1)
        top.addWidget(self.xor_label)
        top.addWidget(self.ref_tag)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(STRIP_PAD, STRIP_PAD, STRIP_PAD, STRIP_PAD)
        layout.setSpacing(4)
        layout.addLayout(top)
        layout.addWidget(self.bitstrip)
        layout.addWidget(self.diff_strip)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.set_ref(is_ref)

    def _update_bitstrip(self) -> None:
        value = self.channel.value
        is_int = value is not None and isinstance(value.number, int)
        self.bitstrip.setVisible(is_int)
        if is_int:
            assert value is not None
            mask = (1 << self.word_size) - 1
            self.bitstrip.set_state(value.number & mask, self.word_size)

    def refresh(self, channel: Channel, word_size: int) -> None:
        self.channel = channel
        self.word_size = word_size
        self.slot_label.setText(channel.label)
        self.value_label.setText(channel.text)
        self._update_bitstrip()
        self._update_ref_extras()

    def set_ref(self, is_ref: bool) -> None:
        self.is_ref = is_ref
        self.ref_tag.setVisible(is_ref)
        self._update_ref_extras()

    def set_live(self, value: int | None) -> None:
        self._live = value
        self._update_ref_extras()

    def _update_ref_extras(self) -> None:
        value = self.channel.value
        is_int = value is not None and isinstance(value.number, int)
        if not (self.is_ref and self._live is not None and is_int):
            self.xor_label.hide()
            self.diff_strip.hide()
            return
        assert value is not None
        mask = (1 << self.word_size) - 1
        ref = value.number & mask
        live = self._live & mask
        xor = (live ^ ref) & mask
        self.xor_label.setText(f"XOR 0x{xor:X}")
        self.xor_label.show()
        self.diff_strip.set_state(xor, self.word_size)
        self.diff_strip.show()

    def set_palette(self, palette: Palette) -> None:
        self.palette_tokens = palette
        self.bitstrip.set_palette(palette)
        self.diff_strip.set_palette(palette)
        self.diff_strip.set_color(palette.bit_changed)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def _context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        value = self.channel.value
        is_int = value is not None and isinstance(value.number, int)
        to_input_action = menu.addAction("-> input")
        to_input_action.setEnabled(is_int)
        copy_action = menu.addAction("copy")
        menu.addSeparator()
        ref_action = menu.addAction("clear REF" if self.is_ref else "set REF")
        menu.addSeparator()
        unpin_action = menu.addAction("unpin")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is to_input_action and is_int:
            self._send_to_input()
        elif chosen is copy_action:
            self._copy()
        elif chosen is ref_action:
            self.ref_toggled.emit()
        elif chosen is unpin_action:
            self.unpin_requested.emit()

    def _send_to_input(self) -> None:
        value = self.channel.value
        if value is None or not isinstance(value.number, int):
            return
        mask = (1 << self.word_size) - 1
        self.to_input.emit(f"0x{value.number & mask:X}")

    def _copy(self) -> None:
        self._clipboard(self.channel.text)
        self.copied.emit(f"copied {self.channel.text}")


class ChannelsRack(QWidget):
    """Owns the pinned channel list, the REF marker index, and the current
    word size (for reformatting int channels' bit strips)."""

    to_input = Signal(str)
    copied = Signal(str)
    ref_changed = Signal()

    def __init__(self, palette: Palette, clipboard_setter: Callable[[str], None]) -> None:
        super().__init__()
        self.setObjectName("channelsRack")
        self.palette_tokens = palette
        self._clipboard = clipboard_setter
        self.channels: list[Channel] = []
        self.ref_index: int | None = None
        self.word_size = 64
        self._live: int | None = None

        self.hint_label = QLabel("nothing pinned -- Alt+P pins the last result")
        self.hint_label.setProperty("class", "chanHint")

        self.layout_ = QVBoxLayout(self)
        # Side gutter matching the PINNED caption above and every other zone
        # in the inspector; the strips used to run flush to the window edge.
        self.layout_.setContentsMargins(RACK_GUTTER, 0, RACK_GUTTER, 0)
        self.layout_.setSpacing(4)
        self.layout_.addWidget(self.hint_label)

        self._strips: list[ChannelStrip] = []
        self._rebuild()

    # -- label assignment -----------------------------------------------------

    def _auto_label(self) -> str:
        used = set()
        for c in self.channels:
            if c.label.startswith("C") and c.label[1:].isdigit():
                used.add(int(c.label[1:]))
        n = 1
        while n in used:
            n += 1
        return f"C{n}"

    def label_of(self, value: Value) -> str | None:
        """Label of the channel already holding this integer, if any.

        The rack exists to compare values against each other, so four strips
        all reading `43981` are just noise crowding out the seven slots that
        could hold something else.
        """
        number = value.number
        if not isinstance(number, int):
            return None  # non-int channels restore as text; no identity to match
        for channel in self.channels:
            other = channel.value
            if other is not None and isinstance(other.number, int) and other.number == number:
                return channel.label
        return None

    # -- mutation ---------------------------------------------------------------

    def pin(self, value: Value, text: str, label: str | None) -> str | None:
        # Re-pinning a named value (an assignment) updates its existing strip
        # instead of adding a second one under the same label — two identically
        # labelled channels are indistinguishable in the rack.
        if label is not None:
            for i, existing in enumerate(self.channels):
                if existing.label == label:
                    self.channels[i] = Channel(label, value, text)
                    self._rebuild()
                    return label
        if len(self.channels) >= MAX_CHANNELS:
            return None
        existing_label = self.label_of(value)
        if existing_label is not None:
            return existing_label  # already in the rack; caller says so
        assigned = label if label is not None else self._auto_label()
        self.channels.append(Channel(assigned, value, text))
        self._rebuild()
        return assigned

    def unpin(self, i: int) -> None:
        if not 0 <= i < len(self.channels):
            return
        del self.channels[i]
        if self.ref_index is not None:
            if self.ref_index == i:
                self.ref_index = None
            elif self.ref_index > i:
                self.ref_index -= 1
        self._rebuild()

    def refresh(self, fmt: Callable[[Value], str], word_size: int) -> None:
        self.word_size = word_size
        for i, channel in enumerate(self.channels):
            if channel.value is not None:
                self.channels[i] = Channel(channel.label, channel.value, fmt(channel.value))
        self._rebuild()

    def set_palette(self, palette: Palette) -> None:
        self.palette_tokens = palette
        for strip in self._strips:
            strip.set_palette(palette)

    def set_live(self, value: int | None) -> None:
        self._live = value
        for strip in self._strips:
            strip.set_live(value)

    # -- persistence ---------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        channels: list[dict[str, Any]] = []
        for c in self.channels:
            if c.value is not None and isinstance(c.value.number, int):
                channels.append({"label": c.label, "kind": "int", "int": c.value.number})
            else:
                channels.append({"label": c.label, "kind": "text", "text": c.text})
        return {"ref": self.ref_index, "channels": channels}

    def restore(self, blob: dict[str, Any], fmt: Callable[[Value], str], word_size: int) -> None:
        """Rebuild the rack from a persisted blob, tolerating a corrupt one.

        Individual bad entries are skipped rather than losing the whole rack,
        and `ref` is validated against the channels that actually survived —
        an out-of-range index would otherwise raise IndexError straight out of
        MainWindow's constructor, leaving the app unable to start.
        """
        channels: list[Channel] = []
        for entry in blob["channels"][:MAX_CHANNELS]:
            try:
                label = str(entry["label"])
                if entry["kind"] == "int":
                    raw = entry["int"]
                    if not isinstance(raw, int) or isinstance(raw, bool):
                        continue
                    value = Value(raw)
                    channels.append(Channel(label, value, fmt(value)))
                else:
                    channels.append(Channel(label, None, str(entry["text"])))
            except (KeyError, TypeError, ValueError):
                continue
        self.channels = channels
        ref = blob.get("ref")
        valid_ref = (
            isinstance(ref, int) and not isinstance(ref, bool) and 0 <= ref < len(channels)
        )
        self.ref_index = ref if valid_ref else None
        self.word_size = word_size
        self._rebuild()

    # -- rack UI ---------------------------------------------------------------

    def _rebuild(self) -> None:
        for strip in self._strips:
            strip.setParent(None)
        self._strips = []
        self.hint_label.setVisible(not self.channels)
        for i, channel in enumerate(self.channels):
            strip = ChannelStrip(
                self.palette_tokens,
                channel,
                self.word_size,
                i == self.ref_index,
                self._clipboard,
            )
            strip.to_input.connect(self.to_input)
            strip.copied.connect(self.copied)
            strip.unpin_requested.connect(lambda i=i: self.unpin(i))
            strip.ref_toggled.connect(lambda i=i: self._toggle_ref(i))
            strip.clicked.connect(lambda i=i: self._toggle_ref(i))
            strip.set_live(self._live)
            self.layout_.addWidget(strip)
            self._strips.append(strip)

    def _toggle_ref(self, i: int) -> None:
        self.ref_index = None if self.ref_index == i else i
        for j, strip in enumerate(self._strips):
            strip.set_ref(j == self.ref_index)
        self.ref_changed.emit()
