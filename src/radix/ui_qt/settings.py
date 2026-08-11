"""Persistent application settings.

QSettings pinned to INI format so behavior is identical on Windows and Linux
(a plain config file under AppData / ~/.config, never the registry). Session
settings are saved as they change; window geometry and always-on-top are
saved by MainWindow on close through the same object. Unknown or corrupt
stored values silently keep the built-in defaults.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QSettings

from radix.session import DECIMAL_MODES, INT_BASES, NOTATIONS, WORD_SIZES, Session


def app_settings() -> QSettings:
    return QSettings(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, "radix", "radix"
    )


def load_session(session: Session) -> None:
    """Apply persisted session settings, validating every value."""
    s = app_settings()
    try:
        word_size = s.value("word_size", session.word_size, type=int)
        signed = s.value("signed", session.signed, type=bool)
        angle_deg = s.value("angle_deg", session.angle_deg, type=bool)
        notation = s.value("notation", session.notation, type=str)
        int_base = s.value("int_base", session.int_base, type=str)
        decimal_mode = s.value("decimal_mode", session.decimal_mode, type=str)
        show_float_view = s.value("show_float_view", session.show_float_view, type=bool)
    except (TypeError, ValueError):
        return  # unreadable file → defaults
    if word_size in WORD_SIZES:
        session.word_size = word_size
    session.signed = bool(signed)
    session.angle_deg = bool(angle_deg)
    if notation in NOTATIONS:
        session.notation = notation
    if int_base in INT_BASES:
        session.int_base = int_base
    if decimal_mode in DECIMAL_MODES:
        session.decimal_mode = decimal_mode
    session.show_float_view = bool(show_float_view)


def save_session(session: Session) -> None:
    s = app_settings()
    s.setValue("word_size", session.word_size)
    s.setValue("signed", session.signed)
    s.setValue("angle_deg", session.angle_deg)
    s.setValue("notation", session.notation)
    s.setValue("int_base", session.int_base)
    s.setValue("decimal_mode", session.decimal_mode)
    s.setValue("show_float_view", session.show_float_view)


def load_state(session: Session) -> None:
    """Apply persisted variables/layouts/ans. Corrupt or missing data leaves
    the session at its (empty) defaults."""
    blob = app_settings().value("calc_state")
    if blob is None:
        return
    try:
        data = json.loads(blob)
    except (TypeError, ValueError):
        return
    if not isinstance(data, dict):
        return
    session.load_state_json(data)


def save_state(session: Session) -> None:
    app_settings().setValue("calc_state", json.dumps(session.state_to_json()))
