# Radix

Keyboard-first scientific + programmer calculator (Python 3.11+, PySide6) for
engineers, with an FPGA/HDL toolkit. Ships as PyInstaller onedir binaries for
Windows and Linux. The full design rationale and feature spec live in
`README.md` and `CHANGELOG.md`.

## Commands

```sh
QT_QPA_PLATFORM=offscreen uv run pytest tests/ -q   # all tests (offscreen-safe)
uv run ruff check src tests                         # lint
uv run mypy                                         # strict on radix.engine.*
uv run radix                                        # launch GUI
uv run radix -e "0xFF << 2"                         # one-shot CLI (no display)
uv run pyinstaller packaging/radix.spec             # frozen build into dist/
cd android && ./gradlew test                        # Android ViewModel unit tests (JDK 17 + SDK)
cd android && ./gradlew assembleDebug               # arm64 APK; -Pradix.abi=x86_64 for an emulator
```

All three checks must pass before committing. Everything runs through `uv` —
never pip or a bare `python`.

## Architecture

Pipeline: lexer → Pratt parser → AST → tree-walking evaluator → formatter.
Nothing is ever `eval`ed. All tokens/errors carry source `Span`s for caret
diagnostics.

- `src/radix/engine/` — headless math core (lexer, parser, evaluator,
  formatter, functions/constants tables, FPGA helpers, help generation).
  `help` text (plain + HTML variants) and the input autocomplete popup are
  generated from the same tables the evaluator dispatches through — extend
  the tables, never hand-write help entries. Every registered function must
  supply `params` (display argument names) and `category`.
- `src/radix/session.py` — `Session` façade owning all state (variables,
  `ans`, word size, signedness, deg/rad, notation). `evaluate(text,
  commit=False)` is the side-effect-free preview path.
- `src/radix/ui_qt/` — the UI only calls `Session.evaluate` and renders
  the result; it never computes math itself.
- `src/radix/bridge.py` — Qt-free JSON adapter the Android app calls
  (`rpc(bridge, method, args_json)`); must stay importable without PySide6
  (`tests/test_bridge.py` checks). Every string the phone paints — nibbles,
  hex/dec/bin, notes, error spans, field readouts — is produced here.
- `android/` — Kotlin/Compose front-end; Chaquopy bundles `src/` by path.
  `CalculatorViewModel` owns the input line and serialises all bridge calls
  on one dispatcher; composables under `ui/` only paint `UiState`. Unit tests
  run against a scripted `FakeBridge`; `BridgeSmokeTest` boots the real
  interpreter on a device.
- Rich result graphics ride the `Value.viz` channel: engine functions attach
  a frozen payload from `engine/viz.py` (`FixedPointViz`/`ClockViz`/`MemViz` —
  numbers *and* pre-formatted text computed engine-side), and
  `ui_qt/viz_panel.py` only paints it. A new visualization = a new payload
  dataclass + a `_paint_*` branch; never derive math in the panel.
- `tests/` — golden tables are the executable spec; Hypothesis property
  tests; pytest-qt smoke tests.

## Design decisions (settled — do not re-litigate)

- **Fully modeless**: one grammar, no mode switch. `**` is always power, `^`
  is always XOR. Integer results always show hex/dec/bin + bit grid.
- Lexer: longest-identifier-match before SI-suffix reading (`2pi`=2·π,
  `4k`=4000 always); `e` is an exponent only before digits; literal prefixes
  (`hFF`/`xFF`/`b1010`, HDL `8'hFF`, `x"FF"`) win over identifier names.
- Bit ops are integer-only (explicit error on floats, never silent
  truncation) and masked to the session word size; plain arithmetic never
  wraps. `>>` is logical when unsigned, arithmetic when signed.
- Numeric tower: exact Python ints preserved; reals via mpmath (25 dps
  working, 12 sig digits displayed). Display formatting is separate from
  precision.
- The integer panel's `scratch` stays **unmasked**; mask only at
  display/copy time (`_masked_scratch`) so cycling word size never destroys
  upper bits. The input line always reflects bit-grid edits.
- Version is single-sourced from `radix.__version__` (hatchling dynamic
  version); it appears in the window title, help header, and `--version`.
  Versions are a plain incrementing integer (`"1"`, `"2"`, …) — not semver.

## Conventions & gotchas

- All UI geometry/fonts live in `ui_qt/theme.py` (QSS, px sizes) and the
  constants atop `ui_qt/bit_panel.py`; tests derive expectations from those
  constants (e.g. `BYTE_WIDTH`) — keep new tests constant-derived, not
  hardcoded pixels.
- Pyright "Import could not be resolved" diagnostics for PySide6 etc. are
  IDE-only noise (venv not detected); ruff/mypy/pytest via uv are
  authoritative.
- No git remote is configured, so CI (including the Windows PyInstaller leg)
  has never run; the frozen build is verified locally on Linux only.
- Android: `connectedDebugAndroidTest` uninstalls the app afterwards (history
  and state gone), so reinstall before adb-driven UI checks. Verify UI
  changes on the headless emulator with `adb exec-out screencap -p` and
  `input tap` — setup and the disk/AVD gotchas are in `android/README.md`.
  The phone register has no changed-bit outlines (the desktop's orange
  "flipped since last value" marks) — dropped on request.
- The app icon (radical-sign mark, `#2563eb` tile) lives at
  `src/radix/ui_qt/icons/icon.png` (runtime, via `theme.load_app_icon()`) and
  `packaging/icon.ico` (PyInstaller `EXE(icon=...)`, Windows/macOS only —
  ignored with a warning on Linux, which is expected). Qt/Wayland-specific
  gotchas live in `src/radix/ui_qt/CLAUDE.md`; the mypy/`Number`-type gotcha
  lives in `src/radix/engine/CLAUDE.md`.

## Working preferences

- The user is an FPGA programmer; keyboard-first UX and a modern, clean,
  usability-first UI are hard requirements.
- Verify UI changes visually: render an offscreen screenshot (script in the
  scratchpad that builds `MainWindow`, evaluates an expression, saves
  `window.grab()`) and inspect it — don't trust geometry math alone.
- Commit each completed request as one commit with a short imperative
  subject; don't push (no remote).
- Add user-visible changes to `CHANGELOG.md` (Keep a Changelog format) under
  a new `[Unreleased]` section when post-1.0.0 changes accumulate.
