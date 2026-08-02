# Changelog

All notable changes to Radix (formerly Calcutron-9000) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions are a simple incrementing integer (1, 2, 3, …), not semantic
versioning — there's one user, no external API to keep compatible, and no
ambiguity to resolve about major/minor/patch.

## [Unreleased]

## [7] - 2026-08-02

### Added

- The READOUT zone now says when a result is too wide for the current word
  size — e.g. `truncated — low 8 bits of a 64-bit value` above the lanes.
  Every lane and the bit grid have always masked to the word size, so
  `0xDEADBEEFCAFEBABE` at 8 bits read as `HEX 0xBE` and `2**200` at 32 bits as
  `HEX 0x0000_0000`, with nothing to distinguish that from the whole answer
  and nothing explaining why READOUT disagreed with RESULT.
- An empty history pane now shows worked examples — SI suffixes, a bit-op,
  `clkdiv`, a CSR definition and `help` — instead of a blank pane above an
  all-zero register panel. It disappears on the first result.
- Alt+G puts a keyboard cursor on the register grid: arrows move it,
  Shift+arrows drag out a bit range (the same field readout the mouse drag
  gives), space toggles the bit under it, Esc puts the keys back. The grid
  was previously reachable only with a mouse, in an app whose contract is
  that everything is on the keyboard.

### Changed

- The history pane is captioned like every other zone (HISTORY / HELP /
  VARIABLES), so switching to variables or a help topic no longer swaps in a
  similar-looking list with nothing naming it.
- A short history now sits against the input line instead of floating at the
  top of a mostly empty pane — the newest result is next to where you type.
  Once entries overflow, scrolling behaves exactly as before.
- Pinning a value that is already in the rack reports "already pinned as C1"
  instead of adding an indistinguishable duplicate strip.
- The preview line elides overlong text with an ellipsis and offers the full
  string as a tooltip, rather than stopping at the edge with no sign that
  anything was cut.
- Transient confirmations ("pinned C1", "deleted x", a CSR definition) now
  appear on the preview line under the input instead of the status bar, where
  the mode chips left them 46-58px — every message past about eight characters
  was cut off, so defining `csr CTRL = EN[31] IRQ[30:28] ADDR[27:8] CMD[7:0]`
  confirmed with the word `csr`.
- The help and variables panes now take the inspector's space while they are
  showing (it returns on Esc), so the help overview gets the window rather
  than the ~240px the inspector left it. Help also wraps to the window now:
  the function and operator tables reflow while keeping their columns
  aligned. The two hand-aligned blocks (basics, shortcuts) still keep their
  layout and can scroll sideways in a narrow window, as before.
- Up/Down and PageUp/PageDown scroll the help or variables pane while one is
  showing — the input line always holds focus, so there was previously no way
  to scroll either from the keyboard at all.
- `pin result` and the per-lane `copy` buttons are now disabled when there is
  nothing to act on (an empty panel, or `pin` in the IEEE-754 view) instead of
  looking available and doing nothing.
- Long history entries now elide with an ellipsis and carry the full
  expression and result in a tooltip, rather than running off the edge
  mid-digit with nothing to indicate text was cut.
- The inspector (visualization card, register view, pinned rack) now scrolls
  when the window is too short for it, instead of compressing its contents.
  Below a certain height Qt used to shrink the integer panel past its own
  minimum, which painted the `pin result` button and the Δ readout across the
  bit grid and clipped the wrapped BIN lane — worst at a 64-bit word size,
  where the grid wraps to four rows and the low half of the register could be
  cut off entirely at the default window size.
- The default window is now 640x880 (was 600x800), sized so a 64-bit word
  fits without scrolling on a first run. The minimum size is unchanged;
  smaller windows scroll rather than break.
- The live-preview line now shows explicit grouping parentheses for
  mixed-precedence expressions, so a surprising precedence is visible before
  you press Enter — e.g. `x10>>2+h10>>2` previews as `16 >> (2 + 16) >> 2 = 0`,
  making it clear that `+` binds tighter than `>>`. Same-precedence chains
  (`a + b + c`) and superscript powers (`2³ + 1`) stay paren-free.
- Pinning a value that already has a channel (an assignment pinned under its
  variable name) now updates that channel instead of adding a second one with
  the same label.
- `mem()` now rejects a depth or width above `2**64`, and CSR field indices
  above 4095, rather than accepting numbers no device could have.

### Fixed

- The result base and float-view status chips advertised Alt+B and Alt+F in
  their tooltips long after those keys became bash-style word-jump in the
  input line — following either moved the cursor instead. Both the tooltip
  and the key binding now come from one table, and the README keyboard
  reference is corrected (it also gained the missing Alt+P and Alt+Shift+F).
- Mode chips no longer elide their own labels ("FLOAT OFF" as "FL…FF",
  "unsigned" as "un…ed" at the minimum window size). Each chip is sized for
  the widest label it can hold, which also stops the status bar shuffling
  sideways as you toggle modes.
- A register field and its bit range can no longer wrap apart in the field
  table ("CMD" on one line, "[7:0] = 0xF3" on the next).
- The input placeholder no longer runs off the edge of a minimum-width
  window (it was cut mid-word at 520px).
- Pinned channel strips line up with the 12px gutter every other inspector
  zone uses, instead of running flush to the window edge.
- Results too wide to print in full — anything past about 4300 digits, such as
  `2**20000` — now display in scientific notation (`3.98027684034e+6020`)
  instead of doing nothing at all. Previously the whole line silently failed:
  no result, no history entry, no error, with only a traceback on a stderr
  nobody sees. An *assignment* was worse, committing the variable before the
  failure, after which the variables pane and every expression naming it broke
  too, across restarts. Hex and binary display were never affected, so the same
  expression appeared to work or vanish depending on the result base.
- Expressions whose result runs away in magnitude — `exp(2**20000)` and the
  like — now report `result is out of range` immediately. Previously they took
  22 seconds and then failed, or never finished at all, freezing the window:
  the live preview evaluates while you type, so this could hit mid-keystroke.
  The error points at the innermost call that produced the value.
- `1**n`, `0**n` and `(-1)**n` with a huge `n` are no longer rejected as
  `result too large`; they are one digit whatever the exponent.
- A corrupt or hand-edited config file no longer stops Radix from starting.
  Wrong-shaped stored state, a malformed real, an out-of-range CSR field, and a
  pinned-channel REF marker pointing past the channels that survived were all
  unhandled; each now falls back to a default and keeps whatever else loaded.
- Commands separated by a tab rather than a space (`del⇥x`) are now recognized.
- The preview now renders multi-digit and negative integer exponents as
  superscripts (`2**10` → `2¹⁰`, `2**64` → `2⁶⁴`, `2**-1` → `2⁻¹`); previously
  any exponent outside `0`–`9` fell back to the textual `**`.
- History entries with a real (non-integer) result now keep reformatting when
  you cycle the result notation (AUTO/SCI/ENG/…) after a restart. Previously
  only integer results survived a restart with a reformattable value; reals
  were persisted as text only and froze at whatever notation they were saved
  in. The full result value (reals round-trip bit-exact) is now persisted.

## [6] - 2026-07-23

### Changed

- The history panel is redesigned as a grouped ledger: the input line now
  recedes as muted text, an accent `= ` leader unmistakably marks the
  result, and a hairline divider separates entries.
- The data-trace green (asserted bits, syntax-highlighted numbers, IEEE-754
  exponent band) is now blue (`#0078FF`) in both themes.
- "Cycle integer result base" and "toggle float view" moved from Alt+B /
  Alt+F to Alt+Shift+B / Alt+Shift+F, freeing Alt+B/F for bash-style
  word-jump cursor movement in the input field.

### Added

- Variables, named `csr`s, and `ans` now persist across restarts in the
  same INI file as the other settings, saved after every assign/`del`/
  `csr`/`clear` so a crash doesn't lose them. `clear` also wipes the
  saved copy.
- Bash/readline-style line editing in the input field: Ctrl+B/F move the
  cursor by one character, Alt+B/F by one word, Ctrl+E jumps to end of
  line, Ctrl+D/H delete the char forward/backward, and Ctrl+W deletes the
  word behind the cursor.
- Alt+F (or a new "FLOAT ON/OFF" status-bar chip) toggles the IEEE-754
  breakdown that READOUT/REGISTER show for real-number results at word size
  32/64. Off by default — the panel greys instead, as it already did at
  word sizes 8/16 — since the float view is rarely needed and previously
  appeared on nearly every non-integer result. Persisted across restarts.
- CSR field layouts: `csr CTRL = EN[31] IRQ[30:28] ADDR[27:8]
  CMD[7:0]` names a reusable bit-field layout; `CTRL(value)` decodes any
  integer against it, and `csr(value, EN[7] CMD[3:0])` does a one-shot
  decode without naming a csr. The REGISTER bit grid draws colored
  bracket-and-name bands over the fields live, with a field-value table
  below that updates as bits are toggled; click a field name to select its
  bit range. `ans.ADDR` (or `CTRL(x).ADDR`) reads a decoded field back out
  as a plain integer. `vars`/`del`/`clear` all know about csrs alongside
  variables.

### Fixed

- The history panel no longer scrolled all the way to the bottom on
  startup with a large persisted history: the window manager can resize
  the view again a beat after the initial `scrollToBottom()` (e.g. Wayland
  settling final geometry after the window is mapped), leaving the
  scrollbar frozen one row short. The view now re-pins to the bottom after
  any resize if it was already there beforehand.
- PINNED's mini bit strips drew adjacent "set" bits edge-to-edge within a
  nibble, so consecutive 1s visually merged into one solid block instead of
  reading as distinct bits. Added a small gap between every cell (on top of
  the existing larger nibble-boundary gap), matching the spacing convention
  already used by REGISTER's bit grid.
- The history pane could grow a spurious horizontal scrollbar during normal
  use, with no long results involved. `QListView`'s default
  `ResizeMode.Fixed` only lays row widths out once, at first show — a later
  viewport-width change (a window resize, or the vertical scrollbar popping
  in as entries accumulate) left existing rows sized to a stale width.
  Switched `history_view` to `ResizeMode.Adjust` (keeps row widths synced to
  the viewport) and declared `ScrollBarAlwaysOff` on its horizontal axis
  (this list never legitimately needs it).

## [5] - 2026-07-13

### Added

- Alt+M (or a new status-bar chip) cycles the theme through auto / light /
  dark. "Auto" follows the OS color scheme as before (and keeps reacting
  live to OS theme changes); light/dark pin an explicit choice, persisted
  across restarts, shown as a sun/moon/half-and-half icon drawn with
  QPainter primitives rather than a Unicode glyph (the bundled fonts aren't
  guaranteed to cover "☀"/"☾", and this codebase has hit real
  QFontMetrics segfaults under QT_QPA_PLATFORM=offscreen from exactly this
  class of missing-glyph fallback before).

### Changed

- The version no longer appears in the window title (just "Radix" now) —
  it's shown as a small "vN" item at the far right of the status bar
  instead. Still appears in the help pane header and `--version`.
- Default word size is now 32-bit (was 64-bit). Alt+W still cycles all four
  sizes (8/16/32/64); a fresh session or settings-less window now starts at
  32-bit.

## [4] - 2026-07-13

### Added

- A RESULT zone between history and the input bar shows the most recently
  evaluated result at a large, bold size — previously the answer was only
  visible as the newest (unemphasized) history row, with the live preview
  going blank right after Enter. Persists across restarts (seeded from the
  last loaded history entry), shows a dimmed placeholder before the first
  evaluation, and reformats along with history when the result base,
  notation, signedness, or word size changes.
- Alt+I shows/hides the whole inspector panel (TRACE/READOUT/REGISTER/
  CHANNELS) — the history pane grows to fill the freed space. Persists
  across restarts.

### Changed

- The TRACE panel (viz cards) no longer has a darker recessed background —
  only the new RESULT readout stands out that way now. TRACE now matches
  READOUT/REGISTER and the rest of the chassis, instead of the three
  panels being visually inconsistent with each other.

### Fixed

- The hex-digit label above each nibble in the register view's bit grid was
  clipped 1px at the top on every row — the strip it's drawn in was exactly
  as tall as the font's reserved ascent, with no room to spare. Widened the
  strip (`HEX_H` 18px -> 20px).
- At startup, the history pane didn't scroll all the way to the bottom.
  `scrollToBottom()` ran right after loading persisted history, before the
  window was ever shown — item heights (word-wrapped) depend on the real,
  polished viewport width, which isn't final until the first show. Deferred
  the initial scroll to a `showEvent` override that fires once.

## [3] - 2026-07-13

### Added

- Channels rack: pin up to 8 values — from a history entry's right-click menu,
  the integer panel's "pin" button, or Alt+P for the last result — as
  scope-style strips (slot label, formatted value, mini bit strip) below the
  register view. Pinned channels persist across restarts. One channel can be
  armed as REF (click its strip, or its context menu): the armed strip shows
  a live XOR readout and a second amber mini bit strip against whatever value
  the panel is currently showing, and the integer panel's delta note reads
  `Δ vs C1 +n -m` instead of the plain previous-value diff. The register grid
  itself is unaffected either way — it always highlights only the diff
  against the panel's own previous value, never the REF diff.
- Click a history entry to inspect its value in the register/viz panel
  without touching the input line or recalling it (double-click still
  recalls the expression as before). The inspected row gets a highlighted
  accent bar; typing, evaluating, or Esc returns to following the live
  input/last result.
- Trace panel (the Qm.n, IEEE-754, and clock/divider cards below the
  register view) now responds to mouse hover: bit cells in the Qm.n and
  float32/float64 bars show the bit index, value, and field (sign/integer/
  fraction or sign/exponent/mantissa); the clkdiv waveform strip reports
  high/low state per trace on hover; the color-coded frequency-error text
  explains the ok/warn/bad thresholds.

### Changed

- The inspector panel is now organized into silkscreen-captioned zones
  (TRACE / READOUT / REGISTER / CHANNELS) with hairline rules between them,
  matching the screen-printed sections of a physical front panel.
- Redesigned the UI around a "bench instrument" visual direction (precision
  test equipment / waveform viewer) instead of the generic dark-IDE look:
  a two-channel dark palette (blue = interaction, phosphor green = data
  trace, amber = measurement cursor) and a "datasheet" light palette,
  paired with a silkscreen label face (IBM Plex Sans Condensed SemiBold)
  alongside the JetBrains Mono readout.
- Dark palette repainted as "Obsidian Depths": a deep midnight-blue chassis
  (`#2C3E50`) replaces the earlier near-black graphite, with much higher
  contrast text and secondary/muted text (previously ~4.4:1 against the
  background, now ~5.4:1) — the near-black scheme read as too dark, with
  too much grey secondary text.
- The integer panel's base rows are now generic lanes: HEX/DEC (merged
  signed reading when it differs from unsigned)/BIN/ASC (hidden when
  nothing is printable) in integer mode, HEX/SGN/EXP/MAN in float mode.
  BIN's set bits are highlighted in the same phosphor color as the bit
  grid's asserted cells, and the row wraps instead of overflowing the
  panel at 64-bit word sizes.
- History renders as a ledger: assignments show a chip with the variable
  name instead of inline `x ← ` text.
- Status-bar mode indicators are now real chip buttons instead of
  plain clickable text.
- The clkdiv clock card's waveform is a proper timing diagram: hairline
  baselines, sharp rising-edge ticks, and the divided row labeled by its
  actual achieved frequency.
- All UI text is two sizes larger for readability (11-20px scale raised to
  13-22px). The clock card's waveform label column was widened so its
  "T = …s" / achieved-frequency labels don't clip at the larger size.
- The bit grid no longer outlines individual flipped bits in amber — the
  `Δ +n -m` gained/lost note already says the same thing as text.

### Removed

- The register view's "-> input" button (the bit grid already writes edits
  to the input line as you toggle bits) and the bit grid's collapse rail for
  leading all-zero rows (Alt+E, "click to expand") — the grid now always
  shows every row of the current word size.

### Fixed

- On Linux/Wayland (GNOME Shell in particular), the running app showed the
  generic executable icon instead of the Radix mark — Wayland compositors
  resolve a window's icon from an installed `.desktop` file matched by app
  id, not from the in-process `QIcon`. The app now reports its desktop-file
  id (`QApplication.setDesktopFileName`), and a `radix.desktop` plus
  `hicolor`-theme icon set (16 through 256px) ship alongside it — see the
  README for the one-time install step the frozen build needs. Two gotchas
  discovered getting this working: the install location is `$XDG_DATA_HOME`,
  which isn't always `~/.local/share` (some setups remap it — check
  `echo $XDG_DATA_HOME`); and the desktop file's `Exec=` must actually
  resolve (`PATH` or an absolute path), because GLib silently refuses to
  parse the whole entry otherwise — an unresolvable `Exec=` makes GNOME
  Shell unable to see the file at all, which looks identical to the
  original bug.
- History entries loaded from a previous session never responded to Alt+B
  (result base) or Alt+N (notation) — only entries evaluated in the current
  session did. Integer-valued entries now persist their raw value (and the
  assignment-badge prefix) so they reformat correctly across restarts too;
  float/text entries still re-evaluate only on recall, unchanged.

## [2] - 2026-07-12

### Added

- The clkdiv clock card now draws the reference vs divided clock waveform
  for divisors up to 16, rising edges aligned, with the divided output's
  duty cycle read out (odd divisors show their asymmetric high/low split).
- New `float32()`/`float64()`/`unfloat32()`/`unfloat64()` functions: the
  IEEE-754 bit pattern of a value as an integer (and back), with a viz card
  showing the sign/exponent/mantissa cell bands and decoded fields — usable
  at any word size, unlike the passive 32/64-bit float view, and pasteable
  into HDL as a plain integer.
- History context menu (right-click an entry): copy result, copy expression,
  copy as hex/dec/bin (for integer results, in the current word size),
  recall, and delete entry (also removed from the persisted history).
- Variables inspector: `vars` (or Alt+V) opens a pane listing every defined
  variable rendered in the current base/notation; click a row to insert the
  name, right-click to delete. New `del <name>` command removes a variable
  from the keyboard. Both commands appear in the autocomplete.
- Autocomplete in the input field: typing an identifier (or Ctrl+Space) pops
  a list of matching functions, constants, variables, and commands with
  signatures and one-line summaries. Tab inserts; Enter inserts only after
  navigating with Up/Down, so plain Enter always evaluates.
- The `help` overview now groups functions by category (trigonometry, bit
  utilities, clock & units, fixed-point, …) with the signature and summary
  of every function; `help <name>` shows real argument names. The GUI help
  pane renders it as an aligned table.
- Integer result display base (dec/hex/bin) for the history pane and the
  live preview — cycle via the status-bar item or Alt+B. Existing history
  entries re-render in the chosen base; float results are unaffected.
- History re-renders when the notation changes (floats included), not just
  on display-base changes.
- The notation setting (sci/eng/eng·si) now applies to integer results too:
  10000000 displays as `1e+7` (SCI), `10e+6` (ENG), or `10M` (ENG·SI).
  AUTO keeps integers exact, and the hex/bin display base takes precedence.
- Settings now persist across restarts: word size, signedness, deg/rad,
  notation, result base, always-on-top, and window size/position. Stored as
  a plain INI file (`AppData` on Windows, `~/.config` on Linux) via
  QSettings.
- New `clkdiv(f_clk, f_target)` toolkit function: nearest integer divider
  with the achieved rate and signed error (ppm, or % past 1%). The viz panel
  shows the clock card — reference freq/period, `/ N → achieved (target)`,
  and the error colored green/amber/red at 1% / 3% (UART tolerance).
  `period()`/`freq()` show their reciprocal pair on the same card.
- New `mem(depth, width)` toolkit function: total bits, address width
  (clog2), and capacity in B/KiB/MiB. The viz panel adds an address-space
  utilization bar that flags non-power-of-two depths (amber, with the
  wasted-address percentage).
- New visualization panel between the preview and the integer panel, driven
  by structured payloads the engine attaches to results. `fix()`/`unfix()`
  now draw the Qm.n layout: sign/integer/fraction bit bands with the binary
  point marked, the exact vs. stored value, and a quantization-error meter
  scaled against the ½ LSB round-to-nearest bound.
- Float results no longer grey the integer panel: at 32/64-bit word size the
  panel shows the IEEE-754 bit pattern with color-coded sign / exponent /
  mantissa bands and decoded HEX / SGN / EXP / MAN rows (read-only; copy
  buttons work — handy for float constants in HDL). 8/16-bit words grey the
  panel as before.
- Bit grid: drag across cells to select a bit range — a readout shows the
  field as `[15:8] = 0xBE = 190 (8 bits)`, and "→ input" then inserts the
  slice expression (`0x…[15:8]`). Esc or a plain click clears the selection.
- Bit grid: each nibble group shows its hex digit above the cells (muted when
  zero), so the grid reads directly against the HEX row.
- Bit grid: bits that flipped vs. the previously shown value are outlined
  (amber) with a `Δ +n -m` gained/lost note — makes the effect of masks,
  shifts, and rotates visible at a glance.
- Bit grid: hovering a cell shows the bit index, its weight (2^n), and its
  byte/nibble position.
- New ASC row in the integer panel: the value's bytes as ASCII (dots for
  non-printable), with its own copy button — quick decode of magic numbers
  and packed strings.

### Fixed

- Errors now underline the offending span directly in the input field (red
  wavy underline) instead of a `·····^` caret in the preview line, which
  drifted off-target because the preview and input use different font sizes.
- Window size was saved on close but never actually restored (the startup
  default overrode it).
- The autocomplete popup could deactivate the main window or fail to
  position itself on some window managers (Wayland in particular) because
  it was a top-level Tool window; it's now a plain child widget raised over
  the input, which sidesteps window-manager focus/positioning entirely.

### Removed

- The "copy Verilog" / "copy VHDL" / "copy C" buttons in the integer panel.

### Changed

- Renamed the app from Calcutron-9000 to **Radix** — the actual mathematical
  term for "the base of a number system," which is what the dec/hex/bin
  simultaneous display has always been about. The package, CLI command
  (`calcutron` → `radix`), and import paths (`calcutron.*` → `radix.*`) all
  changed to match. Settings and history now live under a new `radix` config
  directory (`~/.config/radix` on Linux, `%APPDATA%\radix` on Windows) instead
  of `calcutron` — nothing migrates automatically, so a fresh install starts
  with default settings and empty history.
- Added an app icon: a white radical-sign (√) mark on the accent-blue tile,
  used for the window/taskbar icon on both platforms.
- Larger bit-grid cells (24 px) for readability.
- Clicking a bit in the grid now writes the edited value straight into the
  input field as a hex literal (previously only via the "→ input" button).

## [1] - 2026-07-11

First release.

### Added

- **Expression engine** — hand-written lexer + Pratt parser, fully modeless:
  `**` is always power, `^` is always XOR, one grammar for scientific and
  programmer math. Exact integers preserved; reals via mpmath (25-digit
  working precision, 12 significant digits displayed; auto/sci/eng/SI
  notations).
- **Literals** — decimal/float with `_` separators, `0x`/`0b`/`0o`,
  `h`/`x`/`b` prefixed numbers (`hFF`, `xFF`, `b1010`), scientific `1.5e-9`,
  SI suffixes (`4.7k`, `100n`; `f p n u µ m k M G T`), binary prefixes
  (`32Ki`, `Mi`, `Gi`), HDL sized literals (`8'hFF`, `12'b1010_1010`, `4'd9`,
  `8'o17`) and VHDL hex strings (`x"FF"`).
- **Operators** — full C-like ladder (`| ^ & << >> + - * / // % ~ **`),
  implicit multiplication (`2pi`, `3(x+1)`), Verilog-style bit slicing
  (`x[7:4]`, `x[3]`). Bit operators are integer-only, masked to the session
  word size (8/16/32/64, signed/unsigned); plain arithmetic never wraps.
- **Variables and `ans`** — `x = 4.7k`, previous result via `ans`.
- **FPGA toolkit** — `clog2 flog2 mask bit popcount parity revbits
  byteswap16/32/64 sext zext rol ror`, clock helpers `period`/`freq` with
  SI-suffix output, fixed-point `fix`/`unfix` (Qm.n) with quantization error.
- **Scientific functions** — `sin cos tan asin acos atan sinh cosh tanh log
  ln log2 sqrt exp abs floor ceil round`; constants `pi`, `e`; deg/rad toggle.
- **Qt GUI (PySide6)** — stacked single-column layout: history, input with
  live syntax highlighting and debounced live preview (side-effect free,
  updates while typing), integer panel (hex/dec/signed/bin rows with per-base
  copy, set bits highlighted, copy as Verilog/VHDL/C), clickable bit grid
  with index labels that wraps to the window width, clickable status bar
  (deg/rad, word size, signedness, notation). The integer panel follows the
  input field live and greys out for float results.
- **Keyboard-first UX** — Enter evaluates, Up/Down recall, Ctrl+L clear,
  Ctrl+Shift+C copy result, F1/`help` help pane, Alt+W/S/D/N cycle settings,
  Alt+T always-on-top.
- **Theming** — OS-following light/dark palettes, flat QSS design, bundled
  JetBrains Mono (OFL).
- **Help** — `help` / `help <name>` generated from the evaluator's own
  function and operator tables; also available as `calcutron -e help`.
- **CLI** — `calcutron -e "0xFF << 2"` one-shot evaluation (prints
  hex/dec/bin for integers), `--version`.
- **Persistence** — history in JSONL via platformdirs, window geometry via
  QSettings.
- **Packaging** — PyInstaller onedir builds for Windows and Linux with CI
  (GitHub Actions matrix) running tests, ruff, mypy, and a frozen-binary
  smoke test.
