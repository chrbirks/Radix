"""Result formatting, kept strictly separate from working precision.

Reals display at DISPLAY_DIGITS significant digits in one of four notations:
``auto`` (plain within a comfortable exponent range, scientific outside),
``sci`` (always d.ddde±xx), ``eng`` (exponent forced to a multiple of 3), and
``eng_si`` (engineering with an SI suffix when one exists, e.g. ``10n``).

Integers additionally render as hex, signed/unsigned decimal, and
nibble-grouped binary, reinterpreted through a word size and signedness —
display-only concerns that never touch stored values.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

import mpmath

from radix.engine.values import Number, Value, magnitude_fits

DISPLAY_DIGITS = 12
# Plain notation is used in auto mode when the decimal exponent is in this range.
AUTO_PLAIN_MIN_EXP = -5
AUTO_PLAIN_MAX_EXP = 12

_SI_BY_EXP = {
    -15: "f", -12: "p", -9: "n", -6: "u", -3: "m",
    0: "", 3: "k", 6: "M", 9: "G", 12: "T",
}

Notation = str  # "auto" | "sci" | "eng" | "eng_si"


@dataclass(frozen=True)
class IntegerViews:
    """All base renderings of one integer under a word size + signedness."""

    hex: str
    dec_unsigned: str
    dec_signed: str
    binary: str
    # Every view above is masked to `word_size`, so a value too wide for the
    # word renders as its low bits and nothing in the text says so. These two
    # let the display flag that, instead of presenting a masked pattern as if
    # it were the whole answer.
    value_bits: int = 0  # narrowest word size that would render `value` exactly
    truncated: bool = False  # value_bits > word_size: the views lost information


@dataclass(frozen=True)
class FloatViews:
    """IEEE-754 decomposition of a real, at the word size's precision.

    Only 32 (single) and 64 (double) bit words map to a float format;
    float_views() returns None for other word sizes.
    """

    bits: int  # the raw packed bit pattern
    width: int  # 32 or 64
    exp_width: int  # 8 or 11
    man_width: int  # 23 or 52
    hex: str  # nibble-grouped hex of the bit pattern
    sign_text: str  # "+" / "-"
    exponent_text: str  # decoded, e.g. "1023 - bias 1023 = 2^0"
    mantissa_text: str  # decoded, e.g. "1.5703125"


_FLOAT_FORMATS = {32: (">f", 8, 23, 127), 64: (">d", 11, 52, 1023)}


def float_views(value: Number, word_size: int) -> FloatViews | None:
    if word_size not in _FLOAT_FORMATS:
        return None
    pack, exp_width, man_width, bias = _FLOAT_FORMATS[word_size]
    x = float(value)
    try:
        bits = int.from_bytes(struct.pack(pack, x), "big")
    except OverflowError:  # magnitude beyond single precision: packs to inf
        bits = int.from_bytes(struct.pack(pack, math.copysign(math.inf, x)), "big")
    sign = bits >> (word_size - 1)
    exp_bits = (bits >> man_width) & ((1 << exp_width) - 1)
    man_bits = bits & ((1 << man_width) - 1)
    if exp_bits == 0:
        if man_bits == 0:
            exponent_text = "0 (zero)"
            mantissa_text = "0"
        else:
            exponent_text = f"0 (subnormal, 2^{1 - bias})"
            mantissa_text = f"{man_bits / 2**man_width:.10g}"
    elif exp_bits == (1 << exp_width) - 1:
        exponent_text = f"{exp_bits} (all ones)"
        mantissa_text = "inf" if man_bits == 0 else "nan"
    else:
        exponent_text = f"{exp_bits} - bias {bias} = 2^{exp_bits - bias}"
        mantissa_text = f"{1 + man_bits / 2**man_width:.10g}"
    return FloatViews(
        bits=bits,
        width=word_size,
        exp_width=exp_width,
        man_width=man_width,
        hex=_group(f"{bits:X}", 4, min_width=word_size // 4, prefix="0x"),
        sign_text="-" if sign else "+",
        exponent_text=exponent_text,
        mantissa_text=mantissa_text,
    )


def format_number(value: Value, notation: Notation = "auto") -> str:
    """The primary (decimal) rendering of a result.

    Integers follow the selected notation too (sci/eng/eng_si), rendering
    like reals at display precision; only ``auto`` keeps them exact.
    """
    n = value.number
    if value.prefer_si and notation == "auto":
        notation = "eng_si"
    if isinstance(n, int):
        if notation == "auto":
            try:
                return str(n)
            except ValueError:
                # Python caps int->str width (sys.set_int_max_str_digits), and
                # the evaluator's result guard permits ints far wider than that
                # cap. Such a result is still worth showing — just not
                # digit-for-digit — so fall back to scientific notation.
                return format_real(mpmath.mpf(n), "sci")
        return format_real(mpmath.mpf(n), notation)
    return format_real(n, notation)


def format_real(x: mpmath.mpf, notation: Notation = "auto") -> str:
    if x == 0:
        return "0"
    if not magnitude_fits(x):
        # Defensive only: guard_displayable rejects these before they can reach
        # a display path. Bail out *before* _significant_digits, since decimal
        # conversion is the unbounded step (minutes, then a hard failure).
        return "-overflow" if x < 0 else "overflow"
    digits, exponent = _significant_digits(x, DISPLAY_DIGITS)
    negative = x < 0
    if notation == "auto":
        if AUTO_PLAIN_MIN_EXP <= exponent <= AUTO_PLAIN_MAX_EXP:
            return _plain(digits, exponent, negative)
        return _sci(digits, exponent, negative)
    if notation == "sci":
        return _sci(digits, exponent, negative)
    if notation in ("eng", "eng_si"):
        return _eng(digits, exponent, negative, si=notation == "eng_si")
    raise ValueError(f"unknown notation {notation!r}")


def format_int_base(value: int, base: str, word_size: int) -> str:
    """Compact hex/bin rendering of an integer result (display base option).

    Non-negative values render at their natural width, nibble-grouped;
    negative values render as word-size two's complement, matching the
    integer panel.
    """
    if base == "dec":
        return str(value)
    wrapped = value & ((1 << word_size) - 1) if value < 0 else value
    if base == "hex":
        return _group(f"{wrapped:X}", 4, min_width=1, prefix="0x")
    if base == "bin":
        return _group(f"{wrapped:b}", 4, min_width=1, prefix="0b")
    raise ValueError(f"unknown base {base!r}")


def bits_needed(value: int) -> int:
    """Narrowest word size that renders `value` exactly in one of the two lanes.

    A non-negative value needs its plain bit length (it reads off the unsigned
    lane); a negative one needs a two's-complement sign bit on top (it reads
    off the signed lane). ``integer_views`` compares this against the word size
    to decide whether masking threw information away.
    """
    if value >= 0:
        return value.bit_length()
    return (~value).bit_length() + 1


def integer_views(value: int, word_size: int) -> IntegerViews:
    mask = (1 << word_size) - 1
    wrapped = value & mask
    signed_value = wrapped - (1 << word_size) if wrapped >> (word_size - 1) else wrapped
    width = bits_needed(value)
    return IntegerViews(
        hex=_group(f"{wrapped:X}", 4, min_width=word_size // 4, prefix="0x"),
        dec_unsigned=str(wrapped),
        dec_signed=str(signed_value),
        binary=_group(f"{wrapped:b}", 4, min_width=word_size, prefix="0b"),
        value_bits=width,
        truncated=width > word_size,
    )


# -- internals ---------------------------------------------------------------


def _significant_digits(x: mpmath.mpf, count: int) -> tuple[str, int]:
    """Return (digit string of length <= count, decimal exponent of first digit).

    The value is abs(x) = 0.digits * 10**(exponent+1), i.e. for 123.4 the
    result is ("1234", 2).
    """
    # mpmath.nstr in 'e' style gives round-tripped digits at requested precision.
    s = mpmath.nstr(abs(x), count, strip_zeros=True, min_fixed=1, max_fixed=0)
    mant, _, exp = s.partition("e")
    exponent = int(exp) if exp else 0
    digits = mant.replace(".", "").rstrip("0") or "0"
    return digits, exponent


def _plain(digits: str, exponent: int, negative: bool) -> str:
    sign = "-" if negative else ""
    if exponent >= len(digits) - 1:
        return sign + digits + "0" * (exponent - len(digits) + 1)
    if exponent >= 0:
        return sign + digits[: exponent + 1] + "." + digits[exponent + 1 :]
    return sign + "0." + "0" * (-exponent - 1) + digits


def _sci(digits: str, exponent: int, negative: bool) -> str:
    sign = "-" if negative else ""
    mantissa = digits[0] + ("." + digits[1:] if len(digits) > 1 else "")
    return f"{sign}{mantissa}e{exponent:+d}"


def _eng(digits: str, exponent: int, negative: bool, si: bool) -> str:
    eng_exp = 3 * (exponent // 3)
    shift = exponent - eng_exp  # 0, 1 or 2 digits before the point
    mantissa_digits = digits + "0" * max(0, shift + 1 - len(digits))
    head = mantissa_digits[: shift + 1]
    tail = mantissa_digits[shift + 1 :]
    mantissa = head + ("." + tail if tail else "")
    sign = "-" if negative else ""
    if si and eng_exp in _SI_BY_EXP:
        return f"{sign}{mantissa}{_SI_BY_EXP[eng_exp]}"
    return f"{sign}{mantissa}e{eng_exp:+d}"


def _group(digits: str, group: int, min_width: int, prefix: str) -> str:
    padded = digits.rjust(min_width, "0")
    rem = len(padded) % group
    parts = ([padded[:rem]] if rem else []) + [
        padded[i : i + group] for i in range(rem, len(padded), group)
    ]
    return prefix + "_".join(parts)


def format_si(x: Number) -> str:
    """Engineering + SI-suffix rendering used by period()/freq() style output."""
    if isinstance(x, int):
        x = mpmath.mpf(x)
    return format_real(x, "eng_si")
