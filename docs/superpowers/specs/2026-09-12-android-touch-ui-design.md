# Radix for Android — touch-first personal build (design)

Status: approved 2026-09-12. Personal sideload only; no Play Store.

## Why

The headless core (`src/radix/engine/`, `session.py`, `history/`) has no Qt
dependency and only pure-Python deps (`mpmath`, `platformdirs`), so it runs on
Android unchanged. The Qt UI does not port: a phone has no keyboard, and the
Android IME buries exactly the characters the grammar lives on (`0x`, A–F,
`<<`, `^`, `&`). The phone gets a new touch-first front-end over the same
engine.

## Decisions

| Decision | Choice |
|---|---|
| Scope | Focused field subset: hex/dec/bin, bit ops, FPGA/clock helpers, SI arithmetic. All engine functions stay reachable (the fn sheet is generated from engine tables); only extra drawings are dropped — csr field bands, channels/pins, inspector, IEEE-754 band cards, viz cards. |
| Input | Custom 6×6 keypad is primary; an `abc` key summons the Android IME on demand for typed names/commands. |
| Symbol homes | Fixed. `SI`, `[ ]`, `fn` open small sheets. Only the fn chip strip is context-aware (prefix-filtered, else most-recently-used). |
| Result card | Polymorphic. Integer → nibble-hero register (hex digit above its four bits, `word_size/4` nibbles, four per row) with a `DEC … · 0x…` footer. Real → large value card. Engine `note` renders under either. |
| Panel below the card | Segmented `BITS · HISTORY · MODES`. |
| Modes | Word size and signedness: tappable status chips *and* in MODES. Notation, result base, deg/rad: MODES only. Decimal separator fixed to comma mode (desktop default), not exposed. |
| Engine embedding | Chaquopy; Python source bundled by path from `../../src`. |
| Repo | Same repository: new `android/` Gradle project plus a Qt-free `src/radix/bridge.py`. |

## Keypad

```
A  B  C  │ <<  >> │ ⌫
D  E  F  │ &   |  │ /
7  8  9  │ ^   ~  │ *
4  5  6  │ (   )  │ -
1  2  3  │ [ ] ;  │ +
0  ,  0x │ SI abc │ =
```

Three zones per row with a gutter between them, so a thumb never crosses the
pad for one kind of key: literals on the left (hex rows above the classic
digit pad, `0x` beside `0`), bit-operator pairs then call/slice structure
and the two modifiers in the middle, and the `⌫`/arithmetic/`=` column on the
right — the corners every calculator uses.
`,` is the decimal separator, `;` the argument separator (comma mode). `SI`
sheet: `f p n µ m k M G T Ki Mi Gi`. `[ ]` sheet: `[ ] : ** // %`. `fn` opens
the function sheet grouped by engine `category`; `ans` is a permanent chip
next to it (it is a name, not a symbol); the rest of the strip shows
`suggest()` chips. Long-press `⌫` clears the line.

## Screens

1. Integer result — register card, `D E A D / B E E F` for `0xDEAD << 16 | 0xBEEF`.
2. Integer with engine note — `clkdiv(50M; 115200)` → `434`, note under the card.
3. Real result — `period(100M)` → `10n` large; fn sheet open.
4. HISTORY tab — tap recalls, long-press copies/deletes.
5. MODES tab — five segmented rows; footer shows `Radix <version>`.

Mockups: `.superpowers/brainstorm/88840-1789205079/content/` (not committed).

## Architecture

```
Kotlin (Compose)                      Python (Chaquopy, same process)
CalculatorViewModel ── rpc(json) ──▶  radix.bridge.rpc(bridge, method, args_json) -> json
   │ UiState                                │
   ▼                                        ▼
Composables (paint only)              Bridge ─▶ Session(engine) + HistoryStore(files_dir)
```

Everything crossing the boundary is a JSON string. Payloads are pre-formatted
engine-side (nibbles, hex/dec text, notes, error spans); Compose only paints —
the same rule `engine/viz.py` ↔ `ui_qt/viz_panel.py` follows. Bit toggling and
range readouts are computed in the bridge on an unmasked scratch value, mirroring
`ui_qt/bit_panel.py`. One `Bridge` per process; calls serialised on one thread.

## Errors and persistence

`CalcError` → `{kind: error, message, span, incomplete}`; any other exception →
`{kind: error, message: "internal: …"}` — the app never crashes on engine input.
Session state + modes persist as `state.json` in the app files dir; history via
`HistoryStore(files_dir / "history.jsonl")`.

## Testing

`tests/test_bridge.py` (pytest, no Qt) covers payload shapes, nibble layouts at
all word sizes, bit toggle round-trips, suggestions, state round-trip and rpc
error paths. Kotlin: ViewModel unit tests against a fake bridge; one
instrumented smoke test that boots Chaquopy and evaluates `1+1`.
