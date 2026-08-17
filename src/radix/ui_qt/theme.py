"""Design tokens and the application stylesheet.

One palette definition per scheme; the QSS is a template over the tokens so
light and dark can never drift structurally. The app follows the OS color
scheme via QStyleHints.colorScheme and re-applies on change.

Color is split by meaning, not by widget, like a scope separates chrome from
trace from cursor: `accent` (interaction: focus, selection, caret, chip
hover) is never used to render data, `bit_on`/`ok` (data trace / healthy
status) and `bit_changed`/`warn` (measurement cursor / attention) carry the
other two channels. `error` stands alone. Typography pairs a readout face
(JetBrains Mono, every number and expression) with a silkscreen face (IBM
Plex Sans Condensed SemiBold, uppercase micro-labels only).
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication

THEME_MODES = ("auto", "light", "dark")


@dataclass(frozen=True)
class Palette:
    background: str  # chassis
    surface: str  # raised controls: input, popups, dropdowns
    surface_sunken: str  # recessed "screen": the RESULT readout only
    text: str
    muted: str  # preview line, separators text, status bar
    hairline: str  # 1px separators
    accent: str  # interaction channel only: focus, selection, caret, chip hover
    accent_text: str  # text on accent
    error: str
    ok: str  # healthy/good status (duty-cycle ok, address space not overflowing)
    warn: str  # attention status (tolerance exceeded, near-full)
    chip_bg: str  # mode-chip resting background
    chip_bg_active: str  # mode-chip hover/pressed background
    bit_on: str  # data-trace channel: asserted bits, waveform
    bit_off: str
    bit_changed: str  # measurement-cursor channel: flipped bits, slice bracket
    float_sign: str  # IEEE-754 / Qm.n field bands in the bit grid
    float_exp: str
    float_man: str
    field_bands: tuple[str, ...]  # register field overlay, cycled by field index
    syn_number: str
    syn_function: str
    syn_operator: str


LIGHT = Palette(
    # "Datasheet": cool technical paper, not the cream-and-serif cliche.
    background="#F5F7F6",
    surface="#FFFFFF",
    surface_sunken="#EDF1EF",
    text="#18211C",
    muted="#5B6B61",
    hairline="#D8DEDA",
    accent="#2563EB",
    accent_text="#FFFFFF",
    error="#C4344F",
    ok="#0078FF",
    warn="#B87D0F",
    chip_bg="#EBEEEC",
    chip_bg_active="#DCE6FB",
    bit_on="#0078FF",
    bit_off="#E1E7E3",
    bit_changed="#B87D0F",
    float_sign="#B87D0F",
    float_exp="#0078FF",
    float_man="#7C5CBF",
    field_bands=("#0078FF", "#8B5CF6", "#0D9488", "#EA8C00", "#DB2777", "#64748B"),
    syn_number="#0078FF",
    syn_function="#7C5CBF",
    syn_operator="#B87D0F",
)

DARK = Palette(
    # "Obsidian Depths": a deep midnight-blue chassis with a bright,
    # high-contrast readout — no more washed-out grey secondary text.
    background="#2C3E50",
    surface="#34495E",
    surface_sunken="#1B2838",
    text="#ECF0F1",
    muted="#A9B7C6",
    hairline="#435B72",
    accent="#3498DB",
    accent_text="#1B2838",
    error="#FF6B6B",
    ok="#0078FF",
    warn="#F39C12",
    chip_bg="#34495E",
    chip_bg_active="#2E5978",
    bit_on="#0078FF",
    bit_off="#3B5068",
    bit_changed="#F39C12",
    float_sign="#F39C12",
    float_exp="#0078FF",
    float_man="#BB86FC",
    field_bands=("#0078FF", "#BB86FC", "#14B8A6", "#FB923C", "#F472B6", "#94A3B8"),
    syn_number="#0078FF",
    syn_function="#BB86FC",
    syn_operator="#F39C12",
)

MONO_FAMILY = "JetBrains Mono"  # readout face: every number and expression
LABEL_FAMILY = "IBM Plex Sans Condensed SemiBold"  # silkscreen face: micro-labels

FONT_MICRO = 13  # silkscreen labels, bit indices
FONT_SMALL = 15
FONT_BODY = 17
FONT_UI = 19
FONT_RESULT = 20
FONT_INPUT = 22

SPACE_XS = 4
SPACE_S = 8
SPACE_M = 12
SPACE_L = 16


def load_bundled_font() -> tuple[str, str]:
    """Register the bundled fonts; fall back to system fonts if unavailable.

    Returns (mono_family, label_family).
    """
    mono_loaded = False
    for name in ("JetBrainsMono-Regular.ttf", "JetBrainsMono-Bold.ttf"):
        ref = resources.files("radix.ui_qt") / "fonts" / name
        with resources.as_file(ref) as path:
            if QFontDatabase.addApplicationFont(str(path)) >= 0:
                mono_loaded = True
    label_loaded = False
    ref = resources.files("radix.ui_qt") / "fonts" / "IBMPlexSansCondensed-SemiBold.ttf"
    with resources.as_file(ref) as path:
        if QFontDatabase.addApplicationFont(str(path)) >= 0:
            label_loaded = True
    mono = (
        MONO_FAMILY
        if mono_loaded
        else QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
    )
    label = LABEL_FAMILY if label_loaded else mono
    return mono, label


def load_app_icon() -> QIcon:
    """Load the bundled app icon (radical-sign mark on the accent-blue tile)."""
    ref = resources.files("radix.ui_qt") / "icons" / "icon.png"
    with resources.as_file(ref) as path:
        # Read pixel data now, inside the context — `path` may point at a
        # temp-extracted file that as_file removes once the block exits.
        pixmap = QPixmap(str(path))
    return QIcon(pixmap)


_MODE_GLYPHS = {"light": "☀", "auto": "◐"}


def theme_mode_icon(mode: str, color: str, size: int = 16) -> QIcon:
    """Sun / moon / half-and-half glyph for the theme-mode status chip.

    Light/auto draw the Unicode glyph directly, but "☾" renders far thinner
    than the other two at 16px, so dark mode keeps a hand-drawn crescent (a
    circle minus an offset circle) for matching visual weight.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    ink = QColor(color)
    if mode == "dark":
        cx, cy = size / 2, size / 2
        r = size * 0.28
        disc = QPainterPath()
        disc.addEllipse(QPointF(cx, cy), r, r)
        bite = QPainterPath()
        bite.addEllipse(QPointF(cx + r * 0.6, cy - r * 0.4), r, r)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ink)
        painter.drawPath(disc.subtracted(bite))
    else:
        font = QFont()
        font.setPixelSize(round(size * 0.85))
        painter.setFont(font)
        painter.setPen(ink)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, _MODE_GLYPHS[mode])
    painter.end()
    return QIcon(pixmap)


def stylesheet(p: Palette, mono: str, label: str = LABEL_FAMILY) -> str:
    return f"""
    * {{
        font-family: "{mono}";
        font-size: {FONT_UI}px;
    }}
    QMainWindow, QWidget#root {{
        background: {p.background};
    }}
    /* No bottom border on the pane-stack pages: the RESULT ZoneCaption's rule
       sits ~10px below and is the zone divider (as it is for TRACE/PINNED/
       READOUT/REGISTER), so a second edge here only ever read as a double
       line. helpPane never had one — history and vars now match it. */
    QListView#history {{
        background: {p.background};
        border: none;
        padding: 6px;
    }}
    QWidget#inputBar {{
        background: {p.surface};
        border-bottom: 1px solid {p.hairline};
    }}
    QWidget#inputBar[focused="true"] {{
        border-bottom: 1px solid {p.accent};
    }}
    QLabel#prompt {{
        color: {p.accent};
        font-size: {FONT_INPUT}px;
        padding: 10px 0px 10px 12px;
    }}
    QPlainTextEdit#input {{
        background: transparent;
        color: {p.text};
        border: none;
        padding: 10px 12px;
        font-size: {FONT_INPUT}px;
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
    }}
    QLabel#resultValue {{
        background: {p.surface_sunken};
        color: {p.text};
        font-size: {FONT_RESULT}px;
        font-weight: 600;
        padding: 10px 12px;
        border-radius: 4px;
        margin: 0px 12px;
    }}
    QLabel#resultValue[dimmed="true"] {{
        color: {p.muted};
        font-weight: 400;
    }}
    QLabel#preview {{
        color: {p.muted};
        padding: 2px 12px 8px 12px;
        font-size: {FONT_BODY}px;
    }}
    QListWidget#completerPopup {{
        background: {p.surface};
        color: {p.text};
        border: 1px solid {p.hairline};
        border-radius: 4px;
        padding: 2px;
        font-size: {FONT_BODY}px;
        outline: none;
    }}
    QListWidget#completerPopup::item:selected {{
        background: {p.chip_bg_active};
        color: {p.text};
    }}
    QLabel#preview[state="error"] {{
        color: {p.error};
    }}
    QLabel#preview[state="toast"] {{
        color: {p.accent};
    }}
    QScrollArea#inspectorScroll {{
        background: {p.background};
        border: none;
    }}
    QScrollArea#inspectorScroll > QWidget > QWidget {{
        background: {p.background};
    }}
    QLabel.baseName, QLabel.laneName {{
        color: {p.muted};
        font-family: "{label}";
        font-size: {FONT_MICRO}px;
    }}
    QLabel.baseValue, QLabel.laneValue {{
        color: {p.text};
        font-size: {FONT_UI}px;
    }}
    QLabel.baseValue[dimmed="true"], QLabel.baseName[dimmed="true"],
    QLabel.laneValue[dimmed="true"], QLabel.laneName[dimmed="true"] {{
        color: {p.muted};
    }}
    QPushButton.copyBtn {{
        background: transparent;
        color: {p.muted};
        border: 1px solid {p.hairline};
        border-radius: 3px;
        padding: 1px 6px;
        font-family: "{label}";
        font-size: {FONT_SMALL}px;
    }}
    QPushButton.copyBtn:hover {{
        color: {p.accent};
        border-color: {p.accent};
    }}
    QPushButton.copyBtn:disabled {{
        color: {p.bit_off};
        border-color: {p.bit_off};
    }}
    QLabel.truncNote {{
        color: {p.warn};
        font-family: "{label}";
        font-size: {FONT_MICRO}px;
        padding: 2px 0px;
    }}
    QLabel.sliceNote {{
        color: {p.bit_changed};
        font-size: {FONT_SMALL}px;
        padding: 1px 6px;
    }}
    QLabel#fieldTable {{
        color: {p.text};
        font-size: {FONT_SMALL}px;
        padding: 2px 0px;
    }}
    QStatusBar {{
        background: {p.background};
        color: {p.muted};
        border-top: 1px solid {p.hairline};
        font-size: {FONT_SMALL}px;
    }}
    QStatusBar::item {{ border: none; }}
    QLabel.statusItem {{
        color: {p.muted};
        padding: 2px 8px;
    }}
    QLabel.statusItem:hover {{
        color: {p.accent};
    }}
    QToolButton.modeChip {{
        color: {p.muted};
        background: {p.chip_bg};
        border: none;
        border-radius: 9px;
        padding: 2px 10px;
        font-family: "{label}";
        font-size: {FONT_MICRO}px;
    }}
    QToolButton.modeChip:hover, QToolButton.modeChip:pressed {{
        color: {p.text};
        background: {p.chip_bg_active};
    }}
    QListWidget#varsPane {{
        background: {p.surface};
        color: {p.text};
        border: none;
        padding: 8px;
        font-size: {FONT_UI}px;
    }}
    QListWidget#varsPane::item {{
        padding: 4px 6px;
    }}
    QListWidget#varsPane::item:hover {{
        color: {p.accent};
    }}
    QTextEdit#helpPane {{
        background: {p.surface};
        color: {p.text};
        border: none;
        padding: 12px;
        font-size: {FONT_BODY}px;
    }}
    QWidget#channelsRack {{
        background: {p.surface_sunken};
    }}
    QWidget.chanStrip {{
        border-bottom: 1px solid {p.hairline};
    }}
    QLabel.chanSlot {{
        color: {p.muted};
        font-family: "{label}";
        font-size: {FONT_MICRO}px;
        min-width: 26px;
    }}
    QLabel.chanValue {{
        color: {p.text};
        font-size: {FONT_UI}px;
    }}
    QLabel.chanHint {{
        color: {p.muted};
        font-size: {FONT_SMALL}px;
        padding: 4px 0px;
    }}
    QLabel.refTag {{
        color: {p.bit_changed};
        font-family: "{label}";
        font-size: {FONT_MICRO}px;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
    }}
    QScrollBar::handle:vertical {{
        background: {p.hairline};
        border-radius: 4px;
        min-height: 24px;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 8px;
    }}
    QScrollBar::handle:horizontal {{
        background: {p.hairline};
        border-radius: 4px;
        min-width: 24px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QAbstractScrollArea::corner {{ background: transparent; }}
    """


def current_palette(app: QApplication) -> Palette:
    scheme = app.styleHints().colorScheme()
    return DARK if scheme == Qt.ColorScheme.Dark else LIGHT


def resolve_palette(app: QApplication, mode: str) -> Palette:
    """`mode` is one of THEME_MODES: "auto" follows the OS, else pinned."""
    if mode == "light":
        return LIGHT
    if mode == "dark":
        return DARK
    return current_palette(app)
