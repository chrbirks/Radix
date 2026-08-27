"""Golden tests for epoch(): Unix timestamp -> UTC date/time."""

from __future__ import annotations

import mpmath
import pytest

from engine_harness import run
from radix.engine.errors import EvalError
from radix.session import Session

# -- unit auto-detect and note text -------------------------------------------
# The primary result is the input unchanged; the date/time rides on the note.

NOTE_CASES = [
    ("epoch(0)", "0", "1970-01-01 00:00:00 UTC · s"),
    ("epoch(1234567890)", "1234567890", "2009-02-13 23:31:30 UTC · s"),
    ("epoch(1234567890123)", "1234567890123", "2009-02-13 23:31:30.123 UTC · ms"),
    ("epoch(1234567890123456)", "1234567890123456",
     "2009-02-13 23:31:30.123456 UTC · µs"),
    ("epoch(1234567890123456789)", "1234567890123456789",
     "2009-02-13 23:31:30.123456789 UTC · ns"),
    ("epoch(-86400)", "-86400", "1969-12-31 00:00:00 UTC · s"),
    ("epoch(1.5)", "1.5", "1970-01-01 00:00:01.500 UTC · s"),
    # Detection boundary: the same digit string flips from s to ms at 10^11.
    ("epoch(99999999999)", "99999999999", "5138-11-16 09:46:39 UTC · s"),
    ("epoch(100000000000)", "100000000000", "1973-03-03 09:46:40 UTC · ms"),
]


@pytest.mark.parametrize(("text", "primary", "note"), NOTE_CASES)
def test_epoch_note_golden(text: str, primary: str, note: str) -> None:
    assert run(text) == primary
    outcome = Session().evaluate(text)
    assert outcome.value is not None
    assert outcome.value.note == note


# -- viz payload ---------------------------------------------------------------

def test_epoch_attaches_time_viz() -> None:
    from radix.engine.viz import TimeViz

    outcome = Session().evaluate("epoch(1234567890123)")
    assert outcome.value is not None
    viz = outcome.value.viz
    assert isinstance(viz, TimeViz)
    assert viz == TimeViz(
        unit="ms",
        date_text="2009-02-13",
        time_text="23:31:30.123",
        weekday_text="Friday",
        iso_week_text="2009-W07",
        day_text="day 44 of 365",
        seconds_text="1234567890.123 s",
    )


def test_epoch_zero_viz_fields() -> None:
    from radix.engine.viz import TimeViz

    outcome = Session().evaluate("epoch(0)")
    assert outcome.value is not None
    viz = outcome.value.viz
    assert isinstance(viz, TimeViz)
    assert viz.seconds_text is None  # already in seconds: no normalized echo
    assert viz.weekday_text == "Thursday"
    assert viz.iso_week_text == "1970-W01"
    assert viz.day_text == "day 1 of 365"


def test_epoch_negative_iso_edge() -> None:
    # 1969-12-31 belongs to ISO week-numbering year 1970.
    from radix.engine.viz import TimeViz

    outcome = Session().evaluate("epoch(-86400)")
    assert outcome.value is not None
    viz = outcome.value.viz
    assert isinstance(viz, TimeViz)
    assert viz.weekday_text == "Wednesday"
    assert viz.iso_week_text == "1970-W01"
    assert viz.day_text == "day 365 of 365"


# -- errors --------------------------------------------------------------------

def test_epoch_out_of_range() -> None:
    with pytest.raises(EvalError, match="year 1–9999"):
        run("epoch(2**70)")  # read as ns, still ~year 41000
    with pytest.raises(EvalError, match="read as ms"):
        run("epoch(-70e12)")  # read as ms: before year 1


def test_epoch_rejects_non_finite() -> None:
    # Not reachable from the language (no inf literal); pin the handler contract.
    from radix.engine.functions import FUNCTIONS, EvalContext, FunctionDomainError

    ctx = EvalContext(word_size=32, signed=False, angle_deg=True)
    with pytest.raises(FunctionDomainError, match="finite"):
        FUNCTIONS["epoch"].handler([mpmath.inf], ctx)


# -- comma decimal mode --------------------------------------------------------

def test_epoch_fraction_localizes_decimal() -> None:
    session = Session()
    session.decimal_mode = "comma"
    outcome = session.evaluate("epoch(1,5)")
    assert outcome.value is not None
    assert outcome.value.note == "1970-01-01 00:00:01,500 UTC · s"


# -- help ----------------------------------------------------------------------

def test_epoch_topic_help() -> None:
    outcome = Session().evaluate("help epoch")
    assert outcome.help_text is not None
    assert "epoch(1234567890)" in outcome.help_text
