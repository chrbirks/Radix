"""Wall-clock time conversions: Unix epoch timestamps to UTC.

Registered into the same FUNCTIONS table as the math functions. The input
unit (s/ms/µs/ns) is auto-detected from the magnitude — each threshold sits
where one unit's plausible-date window hands over to the next (10^11 s is
year 5138; 10^11 ms is March 1973) — and the result always names the unit it
assumed. All arithmetic happens on exact integer nanoseconds; `datetime` only
turns whole seconds into a calendar date, so the conversion is independent of
the OS (`fromtimestamp` is not, pre-1970) and of the locale (no `%A`).
"""

from __future__ import annotations

from calendar import isleap
from datetime import UTC, datetime, timedelta

import mpmath

from radix.engine.functions import EvalContext, FunctionDomainError, _register
from radix.engine.values import Number, Value
from radix.engine.viz import TimeViz

_TIME = "Time"
_EPOCH0 = datetime(1970, 1, 1, tzinfo=UTC)
# datetime's own span, as epoch seconds: 0001-01-01 00:00:00 .. 9999-12-31 23:59:59.
_MIN_S = -62_135_596_800
_MAX_S = 253_402_300_799
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
# (upper bound on |t|, unit tag, nanoseconds per unit)
_UNITS = ((10**11, "s", 10**9), (10**14, "ms", 10**6), (10**17, "µs", 10**3), (None, "ns", 1))


def _frac_text(nanos: int, ctx: EvalContext) -> str:
    """Sub-second suffix: empty, or ".500"/".123456"/".000000001".

    Trailing zeros are trimmed in steps of 3 so the fraction always reads as
    whole milli/micro/nanoseconds; the separator follows the session decimal.
    """
    if nanos == 0:
        return ""
    digits = f"{nanos:09d}"
    while digits.endswith("000"):
        digits = digits[:-3]
    return ctx.decimal + digits


def _detect_unit(mag: Number) -> tuple[str, int]:
    """Pick the input unit from the magnitude: (unit tag, ns per unit)."""
    for bound, unit, ns_per in _UNITS:
        if bound is None or mag < bound:
            return unit, ns_per
    raise AssertionError("unreachable: the ns row has no bound")


def _epoch(args: list[Number], ctx: EvalContext) -> Value:
    t = args[0]
    if not isinstance(t, int) and not mpmath.isfinite(t):
        raise FunctionDomainError("epoch: argument must be finite")
    unit, ns_per = _detect_unit(abs(t))
    # Exact for ints; an mpf rounds once, at the nanosecond digit (25-dps
    # working precision holds ~83 mantissa bits vs ~61 for an ns-era value).
    total_ns = t * ns_per if isinstance(t, int) else int(mpmath.nint(mpmath.mpf(t) * ns_per))
    secs, nanos = divmod(total_ns, 10**9)
    if not _MIN_S <= secs <= _MAX_S:
        raise FunctionDomainError(f"epoch: timestamp out of the year 1–9999 range (read as {unit})")
    dt = _EPOCH0 + timedelta(seconds=secs)
    date_text = f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"
    time_text = f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}{_frac_text(nanos, ctx)}"
    iso = dt.isocalendar()
    seconds_text = None
    if unit != "s":
        # From |total_ns|, not secs/nanos: floor divmod would say -0.5 s is "-1.5".
        s_int, s_ns = divmod(abs(total_ns), 10**9)
        seconds_text = f"{'-' if total_ns < 0 else ''}{s_int}{_frac_text(s_ns, ctx)} s"
    viz = TimeViz(
        unit=unit,
        date_text=date_text,
        time_text=time_text,
        weekday_text=_WEEKDAYS[dt.weekday()],
        iso_week_text=f"{iso[0]}-W{iso[1]:02d}",
        day_text=f"day {dt.timetuple().tm_yday} of {366 if isleap(dt.year) else 365}",
        seconds_text=seconds_text,
    )
    return Value(t, note=f"{date_text} {time_text} UTC · {unit}", viz=viz)


_register(
    "epoch", (1, 1), "t", _TIME,
    "Unix epoch timestamp → UTC date/time; unit s/ms/µs/ns auto-detected.",
    "epoch(1234567890)", _epoch,
)
