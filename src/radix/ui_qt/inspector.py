"""The inspector: live visualization card stacked over the register view.

Always-visible read-only state, as distinct from the history/help/vars pane
stack the user is actively navigating. TRACE carries only the card-shaped
payloads (clock, memory); Qm.n and IEEE-754 layouts describe a word and so
render in REGISTER, inside `IntegerView`.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QVBoxLayout, QWidget

from radix.ui_qt.bit_panel import IntegerView
from radix.ui_qt.channels import ChannelsRack
from radix.ui_qt.theme import Palette
from radix.ui_qt.viz_panel import CARD_PAD, CardPayload, VizPanel
from radix.ui_qt.zones import ZoneCaption, margin_wrap


class Inspector(QWidget):
    def __init__(self, palette: Palette, clipboard_setter: Callable[[str], None]) -> None:
        super().__init__()
        self.setObjectName("inspector")
        self.trace_caption = ZoneCaption("TRACE")
        self.trace_caption.set_palette(palette)
        self.vizpanel = VizPanel(palette)
        self.trace_caption.hide()
        self.intview = IntegerView(palette, clipboard_setter)
        self.channels_caption = ZoneCaption("PINNED")
        self.channels_caption.set_palette(palette)
        self.channels = ChannelsRack(palette, clipboard_setter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(margin_wrap(self.trace_caption, CARD_PAD))
        layout.addWidget(self.vizpanel)
        layout.addWidget(self.intview)
        layout.addWidget(margin_wrap(self.channels_caption, 12))
        layout.addWidget(self.channels)
        layout.addStretch(1)

    def show_viz_payload(self, payload: CardPayload | None) -> None:
        self.vizpanel.show_payload(payload)
        self.trace_caption.setVisible(payload is not None)

    def set_palette(self, palette: Palette) -> None:
        self.trace_caption.set_palette(palette)
        self.intview.set_palette(palette)
        self.vizpanel.set_palette(palette)
        self.channels_caption.set_palette(palette)
        self.channels.set_palette(palette)
