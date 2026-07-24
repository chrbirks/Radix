# radix.ui_qt gotchas

- QSS px fonts leave `QFont.pointSize()` at −1 — scale via
  `history_model._scaled`, never `setPointSizeF` directly.
- The inspector lives inside `main_window.InspectorScroll`, and two overrides
  there are load-bearing — don't simplify it back to a plain `QScrollArea`.
  (1) `sizeHint` defers to the child, because a bare scroll area reports a
  tiny hint and the layout would shrink the inspector to a permanent stub.
  (2) `event()` forwards `LayoutRequest` upward with `updateGeometry()`: a
  scroll area normally *absorbs* its child's layout changes (it can scroll
  instead), so without this the window layout keeps negotiating against a
  stale hint and the panel sits a few pixels scrolled forever after Alt+W
  grows the bit grid to a 64-bit word. `pane_stack` is `QSizePolicy.Ignored`
  vertically for the matching reason: it is the elastic zone, so it must not
  bid for height against the fixed-content zones below it.
- UI tests run **without** the application stylesheet, where the default
  system font is small enough that everything fits. Layout defects only
  appear at the QSS type sizes and under Fusion, so anything asserting
  geometry must use the `styled_window` fixture in `tests/test_ui_smoke.py`,
  not the plain `window` one. Be aware that even that fixture did not
  reproduce the original squeeze — offscreen geometry differs enough from a
  real session that measuring in a scratch script against a live
  `MainWindow` is still the authoritative check for layout work.
- `QFontMetrics` (not just `.horizontalAdvance`) used to segfault under
  `QT_QPA_PLATFORM=offscreen` for glyphs needing font fallback (`→`/`←` in
  help summaries and the RESULT readout, `☀`/`☾`/`◐` in the theme-mode icon),
  worked around by substituting ASCII/vector-drawn stand-ins. Verified
  2026-07-22 this no longer reproduces with the installed fontconfig
  (2.18.2-1) and this project's Qt/PySide6 (forced real font-fallback in a
  standalone repro and ran the full offscreen suite), so the arrows and the
  light/auto theme-mode glyphs render as actual Unicode again. Dark mode's
  icon stays hand-drawn (`theme.theme_mode_icon`, a circle minus an offset
  circle) — unrelated to the segfault, "☾" just renders far thinner than
  the sun/half-circle glyphs at 16px. If the segfault resurfaces on a
  different Qt/fontconfig pairing: keep measured/painted strings to glyphs
  the bundled fonts cover, and construct `QFontMetrics(font)` yourself —
  `widget.fontMetrics()` can dangle in PySide6 regardless of this bug.
- On Wayland (GNOME Shell), `QApplication.setWindowIcon()` alone is not
  enough — the compositor looks up the icon via the window's desktop-file id
  matched against an *installed* `.desktop` file, ignoring in-process
  `QIcon`s. That's what `app.setDesktopFileName("radix")` (`ui_qt/app.py`)
  plus the shipped `packaging/radix.desktop` and
  `packaging/icons/hicolor/*/apps/radix.png` are for; see README for the
  install step. Don't "fix" a missing/wrong taskbar icon by touching
  `theme.load_app_icon()` again — that path already works, this is a
  separate Linux desktop-integration concern. Two non-obvious failure modes
  if it's still not showing: (1) the install directory is `$XDG_DATA_HOME`,
  not necessarily `~/.local/share` — some setups remap it, check
  `echo $XDG_DATA_HOME` (and compare against the actual `gnome-shell`
  process's env via `/proc/<pid>/environ`, which can differ from an
  interactive shell's if the override lives in shell rc rather than a
  session-wide mechanism); (2) `Exec=` in the desktop file must resolve
  (PATH or absolute path) — GLib's `GDesktopAppInfo` refuses to construct
  *at all* from a file whose `Exec=` doesn't resolve, so an unresolvable
  `Exec=` is indistinguishable from the file not existing, which looks
  exactly like the original bug. Verify with
  `python3 -c "import gi; gi.require_version('Gio','2.0'); from gi.repository import Gio; print(Gio.DesktopAppInfo.new('radix.desktop'))"`
  — `None` means one of these two is still wrong.
