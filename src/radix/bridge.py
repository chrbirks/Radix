"""Qt-free adapter the Android app talks to.

The phone UI is a painter: every string it shows — the primary text, the
hex/dec/bin views, the nibble grid, engine notes, error spans, the bit-range
readout — is produced here, so the Kotlin side never formats a number or
touches a bit. This module must stay importable without PySide6
(``tests/test_bridge.py`` checks that).

Kotlin reaches it through one entry point, ``rpc(bridge, method, args_json)``,
which JSON-decodes the arguments, dispatches over an explicit allow-list and
never raises: engine errors come back as ``kind: "error"`` payloads and
anything else as an ``internal:`` error, so bad input can't crash the app.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from radix import __version__
from radix.engine.errors import CalcError, IncompleteError
from radix.engine.functions import FUNCTIONS
from radix.engine.lexer import tokenize_prefix
from radix.history.store import HistoryStore, StoredEntry
from radix.session import INT_BASES, NOTATIONS, WORD_SIZES, Outcome, Session

Payload = dict[str, Any]

_INFO_KINDS = frozenset({"help", "vars", "csr", "clear", "del"})
_MRU_LIMIT = 24


def _nibbles(hex_view: str) -> list[dict[str, Any]]:
    """Split an IntegerViews.hex string (``0xDEAD_BEEF``) into MSB-first nibbles,
    each with its hex digit and four bits, MSB first."""
    digits = hex_view.removeprefix("0x").replace("_", "")
    return [
        {"hex": d, "bits": [(int(d, 16) >> shift) & 1 for shift in (3, 2, 1, 0)]}
        for d in digits
    ]


class Bridge:
    """One per process. Owns the Session, the on-device history file and the
    bit-grid scratch value."""

    def __init__(self, files_dir: str, state_json: str | None = None) -> None:
        # Comma mode is the shipped default (see radix.__main__.main) and is
        # fixed on the phone: the keypad legend is printed for it.
        self.session = Session(decimal_mode="comma")
        self.store = HistoryStore(Path(files_dir) / "history.jsonl")
        self._entries: list[StoredEntry] = self.store.load()
        # Mirrors ui_qt/bit_panel.py: the scratch stays *unmasked* so cycling
        # the word size never destroys upper bits.
        self._scratch: int | None = None
        self._mru: list[str] = []  # function names, most recently committed first
        if state_json is not None:
            self.load_state(state_json)

    # -- modes -------------------------------------------------------------

    def modes(self) -> Payload:
        s = self.session
        return {
            "word_size": s.word_size,
            "signed": s.signed,
            "angle": "deg" if s.angle_deg else "rad",
            "notation": s.notation,
            "int_base": s.int_base,
        }

    def set_mode(self, name: str, value: object) -> Payload:
        s = self.session
        if name == "word_size":
            if value not in WORD_SIZES:
                raise ValueError(f"word_size must be one of {WORD_SIZES}, got {value!r}")
            s.word_size = int(value)  # validated against WORD_SIZES above
        elif name == "signed":
            s.signed = bool(value)
        elif name == "angle":
            if value not in ("deg", "rad"):
                raise ValueError(f"angle must be 'deg' or 'rad', got {value!r}")
            s.angle_deg = value == "deg"
        elif name == "notation":
            if value not in NOTATIONS:
                raise ValueError(f"notation must be one of {NOTATIONS}, got {value!r}")
            s.notation = str(value)
        elif name == "int_base":
            if value not in INT_BASES:
                raise ValueError(f"int_base must be one of {INT_BASES}, got {value!r}")
            s.int_base = str(value)
        else:
            raise ValueError(f"unknown mode {name!r}")
        return self.modes()

    # -- evaluation ----------------------------------------------------------

    def preview(self, text: str) -> Payload:
        """Side-effect-free evaluation for the live preview line."""
        try:
            outcome = self.session.evaluate(text, commit=False)
        except CalcError as exc:
            return self._error(exc)
        return self._payload(outcome)

    def evaluate(self, text: str) -> Payload:
        """Commit one line: variables, ``ans`` and history change here only."""
        try:
            outcome = self.session.evaluate(text, commit=True)
        except CalcError as exc:
            return self._error(exc)
        payload = self._payload(outcome)
        if outcome.kind == "clear":
            self.clear_history()
        elif outcome.value is not None:
            self._remember_functions(text)
            expression = text.strip()
            self.store.append(
                expression,
                payload["text"],
                payload["note"],
                value=outcome.value,
                prefix=payload["prefix"],
            )
            self._entries.append(
                StoredEntry(
                    expression,
                    payload["text"],
                    payload["note"],
                    time.time(),
                    value=outcome.value,
                    prefix=payload["prefix"],
                )
            )
        return payload

    def _error(self, exc: CalcError) -> Payload:
        return {
            "kind": "error",
            "message": exc.message,
            "span": [exc.span.start, exc.span.end],
            "incomplete": isinstance(exc, IncompleteError),
            "modes": self.modes(),
        }

    def _payload(self, outcome: Outcome) -> Payload:
        s = self.session
        p: Payload = {
            "kind": "empty",
            "text": "",
            "normalized": outcome.normalized,
            "note": "",
            "prefix": "",
            "nibbles": [],
            "modes": self.modes(),
        }
        if outcome.kind in _INFO_KINDS:
            p["kind"] = "info"
            p["info_text"] = outcome.help_text or _info_default(outcome)
            return p
        value = outcome.value
        if value is None:
            return p
        p["text"] = s.format_value(value)
        p["note"] = value.note or ""
        if outcome.kind == "assign" and outcome.target is not None:
            p["prefix"] = outcome.target
        views = s.views_for(value)
        if views is None:
            p["kind"] = "real"  # the scratch is untouched, as on the desktop
            return p
        number = value.number
        assert isinstance(number, int)
        self._scratch = number  # the grid edits whatever is shown, previewed or committed
        p["kind"] = "int"
        p["hex"] = views.hex
        p["dec"] = views.dec_signed if s.signed else views.dec_unsigned
        p["bin"] = views.binary
        p["nibbles"] = _nibbles(views.hex)
        p["truncated"] = views.truncated
        return p

    # -- bit editing ---------------------------------------------------------

    @property
    def _masked_scratch(self) -> int:
        if self._scratch is None:
            raise ValueError("no integer result to edit")
        return self._scratch & ((1 << self.session.word_size) - 1)

    def toggle_bit(self, bit: int) -> Payload:
        """Flip one bit of the shown value. The edited literal becomes the new
        input line (``input``), and the returned payload previews it."""
        if not 0 <= bit < self.session.word_size:
            raise ValueError(f"bit {bit} outside the {self.session.word_size}-bit word")
        masked = self._masked_scratch ^ (1 << bit)
        literal = f"0x{masked:X}"
        payload = self.preview(literal)
        payload["input"] = literal
        return payload

    def field(self, hi: int, lo: int) -> Payload:
        """Readout for a drag-selected bit range, e.g. ``[15:8] = 0xBE = 190``."""
        word_size = self.session.word_size
        if not 0 <= lo <= hi < word_size:
            raise ValueError(f"[{hi}:{lo}] is not a range inside a {word_size}-bit word")
        masked = self._masked_scratch
        width = hi - lo + 1
        value = (masked >> lo) & ((1 << width) - 1)
        return {
            "text": f"[{hi}:{lo}] = 0x{value:X} = {value}",
            "input": f"0x{masked:X}[{hi}:{lo}]",
        }

    # -- history ---------------------------------------------------------------

    def history(self) -> list[Payload]:
        """Entries oldest first, results re-rendered under the current modes."""
        return [
            {
                "expression": e.expression,
                "result": self.session.format_value(e.value) if e.value is not None else e.result,
                "note": e.note,
                "timestamp": e.timestamp,
                "prefix": e.prefix,
            }
            for e in self._entries
        ]

    def delete_history(self, index: int) -> list[Payload]:
        del self._entries[index]
        self.store.rewrite(self._entries)
        return self.history()

    def clear_history(self) -> list[Payload]:
        self.store.clear()
        self._entries = []
        return []

    # -- catalog and suggestions -------------------------------------------------

    def functions(self) -> list[Payload]:
        """The fn sheet: every registered function grouped by category, in table
        order — generated from the same tables the evaluator dispatches through."""
        groups: dict[str, list[Payload]] = {}
        for spec in FUNCTIONS.values():
            groups.setdefault(spec.category, []).append(
                {
                    "name": spec.name,
                    "params": spec.params,
                    "display": spec.signature_sep("; "),
                    "summary": spec.summary,
                    "insert": spec.name + "(",
                }
            )
        return [{"category": category, "items": items} for category, items in groups.items()]

    def suggest(self, text: str, cursor: int, limit: int = 12) -> list[Payload]:
        """Chips for the fn strip: prefix matches while an identifier is being
        typed, otherwise most-recently-used functions first."""
        prefix = self._identifier_prefix(text[:cursor])
        if prefix is not None:
            names = [name for name in FUNCTIONS if name.startswith(prefix)]
        else:
            names = self._mru + [name for name in FUNCTIONS if name not in self._mru]
        return [{"name": name, "insert": name + "("} for name in names[:limit]]

    def _identifier_prefix(self, head: str) -> str | None:
        """The identifier being typed at the end of ``head``, by the lexer's own
        rules — so ``0xBEEF`` and ``4k`` are numbers, not half-typed names."""
        tokens = tokenize_prefix(head, self.session.decimal_syntax)
        if not tokens:
            return None
        last = tokens[-1]
        if last.kind == "IDENT" and last.span.end == len(head):
            return last.text
        return None

    def _remember_functions(self, text: str) -> None:
        for token in tokenize_prefix(text, self.session.decimal_syntax):
            if token.kind == "IDENT" and token.text in FUNCTIONS:
                if token.text in self._mru:
                    self._mru.remove(token.text)
                self._mru.insert(0, token.text)
        del self._mru[_MRU_LIMIT:]

    # -- persistence ---------------------------------------------------------------

    def state_json(self) -> str:
        return json.dumps(
            {"session": self.session.state_to_json(), "modes": self.modes(), "mru": self._mru}
        )

    def load_state(self, json_text: str) -> None:
        """Inverse of ``state_json``. Malformed input degrades to defaults —
        this is a file on the device that a half-finished write can truncate."""
        try:
            data = json.loads(json_text)
        except ValueError:
            return
        if not isinstance(data, dict):
            return
        session = data.get("session")
        if isinstance(session, dict):
            self.session.load_state_json(session)
        modes = data.get("modes")
        if isinstance(modes, dict):
            for name, value in modes.items():
                try:
                    self.set_mode(str(name), value)
                except ValueError:
                    continue
        mru = data.get("mru")
        if isinstance(mru, list):
            self._mru = [name for name in mru if isinstance(name, str) and name in FUNCTIONS]

    def version(self) -> str:
        return __version__


def _info_default(outcome: Outcome) -> str:
    if outcome.kind == "clear":
        return "cleared"
    if outcome.kind == "del":
        return f"deleted {outcome.target}"
    return ""


# -- the Kotlin entry point ------------------------------------------------------

RPC_METHODS = frozenset(
    {
        "preview",
        "evaluate",
        "set_mode",
        "modes",
        "toggle_bit",
        "field",
        "history",
        "delete_history",
        "clear_history",
        "functions",
        "suggest",
        "state_json",
        "load_state",
        "version",
    }
)


def rpc(bridge: Bridge, method: str, args_json: str) -> str:
    """Call one Bridge method by name with JSON keyword arguments; JSON result.

    Never raises: anything that isn't an engine ``CalcError`` (those are already
    payloads) comes back as an ``internal:`` error so the app stays up.
    """
    try:
        if method not in RPC_METHODS:
            raise ValueError(f"unknown method {method!r}")
        args = json.loads(args_json)
        if not isinstance(args, dict):
            raise ValueError("arguments must be a JSON object")
        result = getattr(bridge, method)(**args)
    except Exception as exc:  # noqa: BLE001 — the boundary must swallow everything
        result = {
            "kind": "error",
            "message": f"internal: {exc}",
            "span": None,
            "incomplete": False,
            "modes": bridge.modes(),
        }
    return json.dumps(result)
