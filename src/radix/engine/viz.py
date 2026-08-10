"""Structured visualization payloads attached to Values.

Toolkit functions that have something worth *drawing* (fixed-point and
IEEE-754 layouts, clock relations, memory sizing) attach one of these to
their result Value.
The engine computes every number in the payload; the UI's VizPanel only
renders them and never re-derives math. Text fields are pre-formatted here
for the same reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True)
class FixedPointViz:
    """Qm.n layout for fix()/unfix(): m integer bits (MSB = sign), n fraction."""

    m: int
    n: int
    raw: int  # two's-complement raw word, m+n bits
    exact_text: str  # the requested real value
    stored_text: str  # the value actually representable in Qm.n
    error_text: str  # signed quantization error (e.g. "-6.87e-6")
    error_lsb: float  # |error| in LSBs; 0..0.5 for round-to-nearest
    hex_text: str  # nibble-grouped raw word, e.g. "0x5A82"
    dec_text: str  # raw word as unsigned decimal
    dec_signed_text: str  # raw word read as two's complement
    error_lsb_text: str  # pre-formatted, e.g. "0.24 LSB"
    bit_weights: tuple[str, ...]  # LSB-first, len == m+n, e.g. "2^-15" / "-2^0"


@dataclass(frozen=True)
class ClockViz:
    """Clock relations for period()/freq()/clkdiv().

    freq/period always describe the reciprocal pair. The divider fields are
    set by clkdiv() only; error_ppm stays numeric so the UI can color-code
    it against tolerance thresholds without re-deriving math.
    """

    freq_text: str  # SI-formatted frequency, e.g. "100M"
    period_text: str  # SI-formatted period, e.g. "10n"
    divisor: int | None = None
    target_text: str | None = None  # requested output frequency
    achieved_text: str | None = None  # freq / divisor
    error_text: str | None = None  # pre-formatted, e.g. "+64 ppm" or "-0.79%"
    error_ppm: float | None = None  # signed achieved-vs-target error
    wave_high: int | None = None  # divided-output high time, in ref half-cycles
    wave_low: int | None = None  # low time, in ref half-cycles; high+low == 2*divisor
    duty_text: str | None = None  # pre-formatted, e.g. "50%" or "66.7%"


@dataclass(frozen=True)
class MemViz:
    """Memory sizing for mem(depth, width)."""

    depth: int
    width: int
    addr_bits: int  # clog2(depth)
    addressable: int  # 2**addr_bits
    total_bits: int  # depth * width
    bytes_text: str  # human capacity, e.g. "18 KiB"
    utilization: float  # depth / addressable; < 1 flags non-power-of-two waste
    util_text: str  # pre-formatted, e.g. "73%"


@dataclass(frozen=True)
class FloatBitsViz:
    """IEEE-754 field layout for float32()/float64()/unfloat32()/unfloat64()."""

    width: int  # 32 or 64
    exp_width: int  # 8 or 11
    man_width: int  # 23 or 52
    bits: int  # the packed bit pattern
    hex_text: str  # nibble-grouped, e.g. "0x3FC0_0000"
    exact_text: str  # the requested value
    stored_text: str  # the value actually stored after rounding to the format
    rounded: bool  # True when storing changed the value (numeric compare)
    sign_text: str  # "+" / "-"
    exponent_text: str  # decoded, e.g. "127 - bias 127 = 2^0"
    mantissa_text: str  # decoded, e.g. "1.5"


VizPayload: TypeAlias = FixedPointViz | ClockViz | MemViz | FloatBitsViz
