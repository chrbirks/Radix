"""Contextual visualization card between the preview and the integer panel.

Shows the card-shaped `viz` payloads some toolkit results carry — clock
relations, memory sizing, and epoch time. Payloads that describe a *word* (Qm.n,
IEEE-754) render in the REGISTER frame instead, in `bit_panel`, so the bits
under discussion are never drawn twice at two scales. The engine computes
every number in the payload — this widget only draws. Hidden when the
current value has no card payload.

Text is laid out by `_layout` before it is drawn: segments flow left to right
and wrap onto a further line when the card is too narrow, and the card grows
by that line. It used to draw fixed lines into rects wider than the widget, so
whatever did not fit was cut at the edge — "err +64 ppm" entirely, at the
minimum window width.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPolygonF,
    QResizeEvent,
)
from PySide6.QtWidgets import QWidget

from radix.engine.viz import ClockViz, MemViz, TimeViz
from radix.ui_qt.theme import FONT_BODY, FONT_MICRO, Palette

CardPayload = ClockViz | MemViz | TimeViz

CARD_PAD = 12
LINE_H = 24
METER_H = 8
METER_TRACK_W = 200  # mem-sizing address-space utilization bar
# clkdiv error color thresholds (a UART is unhappy past ~2-3%).
CLK_ERR_WARN_PPM = 10_000  # 1%
CLK_ERR_BAD_PPM = 30_000  # 3%
# clkdiv waveform strip: drawn only while the divider is small enough to read.
WAVE_MAX_DIV = 16
WAVE_ROW_H = 20
WAVE_GAP = 4
WAVE_LABEL_W = 100  # minimum label column; widens to fit the achieved-rate label
SEGMENT_GAP = "    "  # between the phrases of one card line
WAVE_STRIP_MAX_W = 420
WAVE_STRIP_H = 2 * WAVE_ROW_H + WAVE_GAP + 6
TICK_H = 3  # rising-edge tick marks below each trace row


@dataclass(frozen=True)
class _Text:
    """One run of card text, placed: what `paintEvent` draws and tests inspect."""

    text: str
    rect: QRectF
    color: str  # a Palette attribute name
    px: int = FONT_BODY
    role: str = ""  # "err" marks the clock error, for its hover rect


@dataclass(frozen=True)
class _Layout:
    texts: tuple[_Text, ...]
    lines: int  # text lines used, which sets the card height
    body_y: float  # y where non-text content (meter, waveform) starts


def _has_wave(viz: ClockViz) -> bool:
    """True when the clock card draws the divided-clock waveform strip."""
    return (
        viz.divisor is not None
        and viz.divisor <= WAVE_MAX_DIV
        and viz.wave_high is not None
        and viz.wave_low is not None
    )


class VizPanel(QWidget):
    def __init__(self, palette: Palette) -> None:
        super().__init__()
        self.setObjectName("vizPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.palette_tokens = palette
        self.payload: CardPayload | None = None
        self._hover_tip: str | None = None
        self.setMouseTracking(True)
        self.hide()

    def set_palette(self, palette: Palette) -> None:
        self.palette_tokens = palette
        self.update()

    def show_payload(self, payload: CardPayload | None) -> None:
        self.payload = payload
        self._hover_tip = None
        self.setToolTip("")
        self._apply_height()
        self.setVisible(payload is not None)
        self.update()

    def _apply_height(self) -> None:
        payload = self.payload
        if payload is None:
            return
        extra = WAVE_STRIP_H if isinstance(payload, ClockViz) and _has_wave(payload) else 0
        self.setFixedHeight(8 + self._layout().lines * LINE_H + extra + 10)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if event.oldSize().width() != event.size().width():
            self._apply_height()  # the wrap, and so the line count, follows the width

    # -- text layout --------------------------------------------------------------

    def _metrics(self, px: int) -> QFontMetrics:
        font = QFont(self.font())
        font.setPixelSize(px)
        return QFontMetrics(font)

    def _flow(
        self, segments: list[tuple[str, str, str]], line: int, x: float | None = None
    ) -> tuple[list[_Text], int]:
        """Place (text, color, role) segments from `line` on, wrapping as needed.

        Returns the placed texts and the next free line. A segment that does
        not fit the rest of its line starts the next one; one too wide even for
        a whole line is placed anyway (nothing here is that long in practice).
        """
        metrics = self._metrics(FONT_BODY)
        gap = metrics.horizontalAdvance(SEGMENT_GAP)
        right = self.width() - CARD_PAD
        start = CARD_PAD if x is None else x
        cursor = start
        placed: list[_Text] = []
        for text, color, role in segments:
            width = metrics.horizontalAdvance(text)
            if cursor > start and cursor + width > right:
                line += 1
                cursor = start = CARD_PAD
            rect = QRectF(cursor, 8 + line * LINE_H, width, LINE_H)
            placed.append(_Text(text, rect, color, FONT_BODY, role))
            cursor += width + gap
        return placed, line + 1

    def _layout(self) -> _Layout:
        payload = self.payload
        if isinstance(payload, ClockViz):
            return self._clock_layout(payload)
        if isinstance(payload, MemViz):
            return self._mem_layout(payload)
        if isinstance(payload, TimeViz):
            return self._time_layout(payload)
        return _Layout((), 0, 8.0)

    def text_layout(self) -> list[tuple[str, QRectF]]:
        """Every text the card draws with the rect it occupies (for tests)."""
        return [(t.text, t.rect) for t in self._layout().texts]

    def _clock_error_color(self, viz: ClockViz) -> str:
        ppm = abs(viz.error_ppm or 0.0)
        if ppm >= CLK_ERR_BAD_PPM:
            return "error"
        return "warn" if ppm >= CLK_ERR_WARN_PPM else "ok"

    def _clock_layout(self, viz: ClockViz) -> _Layout:
        texts, line = self._flow(
            [(f"freq {viz.freq_text}Hz", "text", ""), (f"period {viz.period_text}s", "text", "")],
            0,
        )
        if viz.divisor is None:
            return _Layout(tuple(texts), line, 8.0 + line * LINE_H)
        more, line = self._flow(
            [
                (f"/ {viz.divisor}  ->  {viz.achieved_text}Hz", "text", ""),
                (f"(target {viz.target_text}Hz)", "text", ""),
                # Colour-coded against UART-style tolerance.
                (f"err {viz.error_text}", self._clock_error_color(viz), "err"),
            ],
            line,
        )
        texts += more
        body_y = 8.0 + line * LINE_H
        if _has_wave(viz):
            x0, strip_w, _units = self._wave_geometry(viz)
            micro = self._metrics(FONT_MICRO)
            for i, label in enumerate(self._wave_labels(viz)):
                y_row = body_y + i * (WAVE_ROW_H + WAVE_GAP)
                rect = QRectF(CARD_PAD, y_row, micro.horizontalAdvance(label), WAVE_ROW_H)
                texts.append(_Text(label, rect, "muted", FONT_MICRO))
            if viz.duty_text is not None:
                duty = f"duty {viz.duty_text}"
                y_row = body_y + WAVE_ROW_H + WAVE_GAP
                rect = QRectF(x0 + strip_w + 10, y_row, micro.horizontalAdvance(duty), WAVE_ROW_H)
                texts.append(_Text(duty, rect, "muted", FONT_MICRO))
        return _Layout(tuple(texts), line, body_y)

    def _mem_layout(self, viz: MemViz) -> _Layout:
        texts, line = self._flow(
            [
                (f"{viz.depth} x {viz.width} bit", "text", ""),
                (f"addr {viz.addr_bits} bits", "text", ""),
                (f"{viz.total_bits} bits = {viz.bytes_text}", "text", ""),
            ],
            0,
        )
        label = f"{viz.depth} / {viz.addressable} addressable ({viz.util_text})"
        if viz.utilization >= 1.0:
            label += "  power of two"
        body_y = 8.0 + line * LINE_H  # the meter's line
        beside = CARD_PAD + METER_TRACK_W + 10
        width = self._metrics(FONT_BODY).horizontalAdvance(label)
        if beside + width <= self.width() - CARD_PAD:
            texts.append(_Text(label, QRectF(beside, body_y, width, LINE_H), "muted"))
            line += 1
        else:  # no room beside the meter: the label gets the line below it
            texts.append(_Text(label, QRectF(CARD_PAD, body_y + LINE_H, width, LINE_H), "muted"))
            line += 2
        return _Layout(tuple(texts), line, body_y)

    def _time_layout(self, viz: TimeViz) -> _Layout:
        texts, line = self._flow(
            [(f"{viz.date_text} {viz.time_text} UTC", "text", ""), (viz.weekday_text, "text", "")],
            0,
        )
        segments = [f"unit {viz.unit}"]
        if viz.seconds_text is not None:
            segments.append(f"= {viz.seconds_text}")
        segments += [f"ISO week {viz.iso_week_text}", viz.day_text]
        more, line = self._flow([(text, "muted", "") for text in segments], line)
        return _Layout(tuple(texts + more), line, 8.0 + line * LINE_H)

    # -- painting -----------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)  # QSS background/border
        payload = self.payload
        if payload is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        layout = self._layout()
        font = painter.font()
        for item in layout.texts:
            font.setPixelSize(item.px)
            painter.setFont(font)
            painter.setPen(QColor(getattr(self.palette_tokens, item.color)))
            # A hair wider than measured: the rect is the text's own advance.
            painter.drawText(
                item.rect.adjusted(0, 0, 2, 0), Qt.AlignmentFlag.AlignVCenter, item.text
            )
        if isinstance(payload, MemViz):
            self._paint_meter(painter, payload, layout.body_y)
        elif isinstance(payload, ClockViz) and _has_wave(payload):
            self._paint_wave(painter, payload, layout.body_y)
        painter.end()

    def _paint_meter(self, painter: QPainter, viz: MemViz, line_y: float) -> None:
        """Address-space utilization bar: full track = 2^addr_bits entries."""
        p = self.palette_tokens
        y = line_y + (LINE_H - METER_H) / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.bit_off))
        painter.drawRoundedRect(QRectF(CARD_PAD, y, METER_TRACK_W, METER_H), 3, 3)
        full = viz.utilization >= 1.0
        painter.setBrush(QColor(p.ok if full else p.bit_on))
        painter.drawRoundedRect(
            QRectF(CARD_PAD, y, METER_TRACK_W * viz.utilization, METER_H), 3, 3
        )

    def _paint_wave(self, painter: QPainter, viz: ClockViz, top: float) -> None:
        """Two divided-output periods under the reference, rising edges aligned at x0."""
        assert viz.wave_high is not None and viz.wave_low is not None
        p = self.palette_tokens
        high, low = viz.wave_high, viz.wave_low
        x0, strip_w, half_units = self._wave_geometry(viz)
        px = strip_w / half_units

        def wave(y_row: float, spans: list[int]) -> QPolygonF:
            y_top, y_bot = y_row + 2.0, y_row + WAVE_ROW_H - 2.0
            pts = [QPointF(x0, y_bot)]
            x = float(x0)
            level_high = True
            for span in spans:
                y_level = y_top if level_high else y_bot
                pts.append(QPointF(x, y_level))
                x += span * px
                pts.append(QPointF(x, y_level))
                level_high = not level_high
            return QPolygonF(pts)

        def rising_edges(spans: list[int]) -> list[float]:
            """X positions where the trace goes low -> high (always starts on one)."""
            xs = [float(x0)]
            x = float(x0)
            level_high = True
            for span in spans:
                x += span * px
                level_high = not level_high
                if level_high:
                    xs.append(x)
            return xs

        painter.setBrush(Qt.BrushStyle.NoBrush)
        rows = (
            ([1] * half_units, p.muted, 1.5),
            ([high, low, high, low], p.bit_on, 2.0),
        )
        for i, (spans, color, width) in enumerate(rows):
            y_row = top + i * (WAVE_ROW_H + WAVE_GAP)
            y_bot = y_row + WAVE_ROW_H - 2.0
            # Hairline baseline under the trace, sharp square joins on the trace itself.
            painter.setPen(QPen(QColor(p.hairline), 1))
            painter.drawLine(QPointF(x0, y_bot), QPointF(x0 + strip_w, y_bot))
            pen = QPen(QColor(color), width)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            painter.setPen(pen)
            painter.drawPolyline(wave(y_row, spans))
            painter.setPen(QPen(QColor(color), 1))
            for tick_x in rising_edges(spans):
                painter.drawLine(QPointF(tick_x, y_bot + 1), QPointF(tick_x, y_bot + 1 + TICK_H))

    # -- hover tooltips -----------------------------------------------------------
    # Geometry helpers below are shared with the layout and paint code above, so
    # the hit-test grid never drifts from what is actually drawn.

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        tooltip = self._tooltip_at(event.position()) if self.payload is not None else None
        if tooltip == self._hover_tip:
            return
        self._hover_tip = tooltip
        self.setToolTip(tooltip or "")

    def _tooltip_at(self, pos: QPointF) -> str | None:
        if isinstance(self.payload, ClockViz):
            return self._clock_tooltip(self.payload, pos)
        return None

    def _clock_tooltip(self, viz: ClockViz, pos: QPointF) -> str | None:
        err_hit = viz.divisor is not None and viz.error_ppm is not None
        if err_hit and self._clock_err_rect(viz).contains(pos):
            return self._clock_err_tooltip(viz)
        if _has_wave(viz):
            assert viz.wave_high is not None and viz.wave_low is not None
            x0, strip_w, half_units = self._wave_geometry(viz)
            px = strip_w / half_units
            top = self._layout().body_y
            for i, spans, label in (
                (0, [1] * half_units, "reference clock"),
                (
                    1,
                    [viz.wave_high, viz.wave_low, viz.wave_high, viz.wave_low],
                    f"divided output ({viz.achieved_text}Hz)",
                ),
            ):
                y_row = top + i * (WAVE_ROW_H + WAVE_GAP)
                if QRectF(x0, y_row, strip_w, WAVE_ROW_H).contains(pos):
                    level = self._level_at(spans, (pos.x() - x0) / px)
                    return f"{label} — {'high' if level else 'low'}"
        return None

    @staticmethod
    def _wave_labels(viz: ClockViz) -> tuple[str, str]:
        return f"T = {viz.period_text}s", f"{viz.achieved_text}Hz"

    def _wave_geometry(self, viz: ClockViz) -> tuple[float, float, int]:
        """(x of the strip's left edge, strip width, half-cycles drawn).

        The label column takes what its widest label needs — the achieved rate
        carries twelve digits, and a fixed column cut its unit off — and room
        for the duty figure is held back on the right, so neither is ever the
        thing that does not fit.
        """
        assert viz.divisor is not None
        half_units = 4 * viz.divisor
        micro = self._metrics(FONT_MICRO)
        label_w = max(
            WAVE_LABEL_W, max(micro.horizontalAdvance(t) for t in self._wave_labels(viz)) + 8
        )
        duty_w = 0
        if viz.duty_text is not None:
            duty_w = micro.horizontalAdvance(f"duty {viz.duty_text}") + 10
        x0 = CARD_PAD + label_w
        strip_w = min(self.width() - 2 * CARD_PAD - label_w - duty_w, WAVE_STRIP_MAX_W)
        return x0, max(strip_w, 40), half_units

    @staticmethod
    def _level_at(spans: list[int], units: float) -> bool:
        """Trace level at a given x position, in half-cycle units from the left edge."""
        x = 0.0
        level_high = True
        for span in spans:
            if units < x + span:
                return level_high
            x += span
            level_high = not level_high
        return level_high

    def _clock_err_rect(self, viz: ClockViz) -> QRectF:
        for item in self._clock_layout(viz).texts:
            if item.role == "err":
                return item.rect
        return QRectF()

    def _clock_err_tooltip(self, viz: ClockViz) -> str:
        ppm = abs(viz.error_ppm or 0.0)
        warn_pct = CLK_ERR_WARN_PPM / 10_000
        bad_pct = CLK_ERR_BAD_PPM / 10_000
        if ppm >= CLK_ERR_BAD_PPM:
            level = "bad"
        elif ppm >= CLK_ERR_WARN_PPM:
            level = "warn"
        else:
            level = "ok"
        return (
            f"{level}: err {viz.error_text}   "
            f"(ok <{warn_pct:.0f}%, warn {warn_pct:.0f}-{bad_pct:.0f}%, "
            f"bad >{bad_pct:.0f}% — typical UART tolerance)"
        )
