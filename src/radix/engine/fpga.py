"""FPGA/HDL toolkit functions: bit utilities, clock helpers, fixed-point Qm.n.

Registered into the same FUNCTIONS table as the math functions, so help text
and evaluation stay in one place. Handlers may return a plain number or a
full Value when they carry display metadata (declared width, SI-suffix
preference, quantization-error note).
"""

from __future__ import annotations

import dataclasses
import math
import struct
import sys

import mpmath

from radix.engine.formatter import float_views, format_si, group_digits, power_of_two
from radix.engine.functions import (
    FUNCTIONS,
    EvalContext,
    FunctionDomainError,
    Handler,
    _register,
)
from radix.engine.values import WORKING_DPS, WORKING_PREC, Number, Value, to_mpf
from radix.engine.viz import ClockViz, FixedPointViz, FloatBitsViz, MemViz

MAX_MASK_BITS = 1_000_000
# mem() sizing converts to float for the capacity string and the utilization
# bar, which overflows above ~1.8e308. Capping each dimension keeps the product
# (and so every derived float) comfortably inside that, at a ceiling no real
# device comes near.
MAX_MEM_DIM = 1 << 64
# clkdiv() draws and prints its divider; past this it is not a divider anyone
# builds, and a 5000-digit one cannot even be printed.
MAX_CLOCK_DIVIDER = 1 << 64


def _int_arg(args: list[Number], i: int, what: str) -> int:
    x = args[i]
    if isinstance(x, int):
        return x
    raise FunctionDomainError(f"{what}: argument {i + 1} must be an integer")


def _word_mask(ctx: EvalContext) -> int:
    return (1 << ctx.word_size) - 1


def _loc(text: str, ctx: EvalContext) -> str:
    """Localize a pure-number string's decimal point to the session separator.

    Only for strings that are entirely a number (``mpmath.nstr`` output); never
    for text where ``.`` means something else, e.g. the ``Q3.5`` format tag.
    """
    return text if ctx.decimal == "." else text.replace(".", ctx.decimal)


# -- bit utilities -------------------------------------------------------------


def _clog2(args: list[Number], ctx: EvalContext) -> Number:
    n = _int_arg(args, 0, "clog2")
    if n <= 0:
        raise FunctionDomainError("clog2: argument must be positive")
    return (n - 1).bit_length()


def _flog2(args: list[Number], ctx: EvalContext) -> Number:
    n = _int_arg(args, 0, "flog2")
    if n <= 0:
        raise FunctionDomainError("flog2: argument must be positive")
    return n.bit_length() - 1


def _mask_fn(args: list[Number], ctx: EvalContext) -> Number:
    n = _int_arg(args, 0, "mask")
    if not 0 <= n <= MAX_MASK_BITS:
        raise FunctionDomainError(f"mask: width must be 0..{MAX_MASK_BITS}")
    return (1 << n) - 1


def _bit_fn(args: list[Number], ctx: EvalContext) -> Number:
    n = _int_arg(args, 0, "bit")
    if not 0 <= n <= MAX_MASK_BITS:
        raise FunctionDomainError(f"bit: index must be 0..{MAX_MASK_BITS}")
    return 1 << n


def _popcount(args: list[Number], ctx: EvalContext) -> Number:
    return (_int_arg(args, 0, "popcount") & _word_mask(ctx)).bit_count()


def _parity(args: list[Number], ctx: EvalContext) -> Number:
    return (_int_arg(args, 0, "parity") & _word_mask(ctx)).bit_count() & 1


def _revbits(args: list[Number], ctx: EvalContext) -> Number:
    v = _int_arg(args, 0, "revbits")
    width = ctx.word_size if len(args) == 1 else _int_arg(args, 1, "revbits")
    if not 1 <= width <= 1024:
        raise FunctionDomainError("revbits: width must be 1..1024")
    v &= (1 << width) - 1
    result = 0
    for _ in range(width):
        result = (result << 1) | (v & 1)
        v >>= 1
    return result


def _byteswap(width: int) -> Handler:
    def handler(args: list[Number], ctx: EvalContext) -> Number:
        v = _int_arg(args, 0, f"byteswap{width}") & ((1 << width) - 1)
        raw = v.to_bytes(width // 8, "big")
        return int.from_bytes(raw, "little")

    return handler


def _sext(args: list[Number], ctx: EvalContext) -> Number:
    v = _int_arg(args, 0, "sext")
    bits = _int_arg(args, 1, "sext")
    if not 1 <= bits <= ctx.word_size:
        raise FunctionDomainError(f"sext: bits must be 1..{ctx.word_size} (the word size)")
    v &= (1 << bits) - 1
    if v >> (bits - 1):  # sign bit set: fill up to the word size
        v |= _word_mask(ctx) ^ ((1 << bits) - 1)
    return v


def _zext(args: list[Number], ctx: EvalContext) -> Number:
    v = _int_arg(args, 0, "zext")
    bits = _int_arg(args, 1, "zext")
    if not 1 <= bits <= ctx.word_size:
        raise FunctionDomainError(f"zext: bits must be 1..{ctx.word_size} (the word size)")
    return v & ((1 << bits) - 1)


def _rotate(left: bool) -> Handler:
    name = "rol" if left else "ror"

    def handler(args: list[Number], ctx: EvalContext) -> Number:
        v = _int_arg(args, 0, name) & _word_mask(ctx)
        n = _int_arg(args, 1, name) % ctx.word_size
        w = ctx.word_size
        if not left:
            n = (w - n) % w
        return ((v << n) | (v >> (w - n))) & _word_mask(ctx) if n else v

    return handler


# -- clock & unit helpers --------------------------------------------------------


def _reciprocal(args: list[Number], what: str) -> mpmath.mpf:
    x = mpmath.mpf(args[0])
    if x == 0:
        raise FunctionDomainError(f"{what}: argument must be non-zero")
    return 1 / x


def _period(args: list[Number], ctx: EvalContext) -> Value:
    t = _reciprocal(args, "period")
    d = ctx.decimal
    viz = ClockViz(
        freq_text=format_si(mpmath.mpf(args[0]), d), period_text=format_si(t, d)
    )
    return Value(t, prefer_si=True, viz=viz)


def _freq(args: list[Number], ctx: EvalContext) -> Value:
    f = _reciprocal(args, "freq")
    d = ctx.decimal
    viz = ClockViz(
        freq_text=format_si(f, d), period_text=format_si(mpmath.mpf(args[0]), d)
    )
    return Value(f, prefer_si=True, viz=viz)


def _clkdiv(args: list[Number], ctx: EvalContext) -> Value:
    """Nearest integer divider from a reference clock to a target rate."""
    f_clk = to_mpf(args[0])
    f_target = to_mpf(args[1])
    if f_clk <= 0 or f_target <= 0:
        raise FunctionDomainError("clkdiv: frequencies must be positive")
    d = ctx.decimal
    ratio = f_clk / f_target
    if ratio > MAX_CLOCK_DIVIDER:
        raise FunctionDomainError("clkdiv: the divider would exceed 2**64")
    divisor = max(1, int(mpmath.nint(ratio)))
    achieved = f_clk / divisor
    ppm = float((achieved - f_target) / f_target * 1_000_000)
    # Past 1%, percent reads better than ppm.
    error_text = _loc(
        f"{ppm / 10_000:+.2f}%" if abs(ppm) >= 10_000 else f"{ppm:+.0f} ppm", ctx
    )
    # Divided-output shape in ref half-cycles: a /1 "divider" passes the clock
    # through; otherwise a single-edge counter stays high ceil(N/2) ref cycles,
    # so odd dividers get the classic asymmetric duty.
    if divisor == 1:
        wave_high, wave_low = 1, 1
    else:
        wave_high, wave_low = 2 * ((divisor + 1) // 2), 2 * (divisor // 2)
    viz = ClockViz(
        freq_text=format_si(f_clk, d),
        period_text=format_si(1 / f_clk, d),
        divisor=divisor,
        target_text=format_si(f_target, d),
        achieved_text=format_si(achieved, d),
        error_text=error_text,
        error_ppm=ppm,
        wave_high=wave_high,
        wave_low=wave_low,
        duty_text=_loc(f"{100 * wave_high / (wave_high + wave_low):.3g}%", ctx),
    )
    note = f"actual {format_si(achieved, d)}, error {error_text}"
    return Value(divisor, note=note, viz=viz)


# -- memory sizing ---------------------------------------------------------------


def _binary_size(bits: int, decimal: str = ".") -> str:
    size = bits / 8
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024:
            return f"{size:.4g} {unit}".replace(".", decimal)
        size /= 1024
    return f"{size:.4g} PiB".replace(".", decimal)


def _mem(args: list[Number], ctx: EvalContext) -> Value:
    """Memory sizing: depth x width -> total bits, with addressing metadata."""
    depth = _int_arg(args, 0, "mem")
    width = _int_arg(args, 1, "mem")
    if depth <= 0 or width <= 0:
        raise FunctionDomainError("mem: depth and width must be positive")
    if depth > MAX_MEM_DIM or width > MAX_MEM_DIM:
        raise FunctionDomainError("mem: depth and width must be at most 2**64")
    addr_bits = (depth - 1).bit_length()
    addressable = 1 << addr_bits
    total_bits = depth * width
    utilization = depth / addressable
    viz = MemViz(
        depth=depth,
        width=width,
        addr_bits=addr_bits,
        addressable=addressable,
        total_bits=total_bits,
        bytes_text=_binary_size(total_bits, ctx.decimal),
        utilization=utilization,
        util_text=f"{utilization * 100:.0f}%",
    )
    note = f"addr {addr_bits} bits, {viz.bytes_text}"
    return Value(total_bits, note=note, viz=viz)


# -- fixed-point Qm.n --------------------------------------------------------------

MAX_Q_BITS = 128
# Bits of the argument kept below the format's LSB, so the reported
# quantization error is itself accurate. Formats up to WORKING_PREC minus this
# are served at the working precision; wider ones raise it for the call.
FIX_GUARD_BITS = 40


def _q_format(args: list[Number], what: str) -> tuple[int, int, int]:
    m = _int_arg(args, 1, what)
    n = _int_arg(args, 2, what)
    if m < 0 or n < 0 or m + n == 0 or m + n > MAX_Q_BITS:
        raise FunctionDomainError(f"{what}: need 0 <= m, n and 0 < m+n <= {MAX_Q_BITS}")
    return m, n, m + n


def _fix_precision(args: list[Number]) -> int | None:
    """Precision fix() needs its value argument at: the whole word plus guard bits.

    None for anything that is not a valid format — the handler reports that.
    """
    m, n = args[1], args[2]
    if not (isinstance(m, int) and isinstance(n, int)):
        return None
    if m < 0 or n < 0 or not 0 < m + n <= MAX_Q_BITS:
        return None
    return m + n + FIX_GUARD_BITS


def _q_bit_weights(m: int, n: int) -> tuple[str, ...]:
    """Per-bit weight text, LSB-first. The MSB carries the two's-complement sign."""
    total = m + n
    weights = []
    for bit in range(total):
        if bit == total - 1:
            weights.append(f"-{power_of_two(m - 1)}")
        else:
            weights.append(power_of_two(bit - n))
    return tuple(weights)


def _fixed_viz(
    m: int,
    n: int,
    raw: int,
    exact_text: str,
    stored_text: str,
    error_text: str,
    error_lsb: float,
    lsb_text: str,
    decimal: str = ".",
) -> FixedPointViz:
    """Build the payload, deriving every pre-formatted field the UI only draws.

    The text arguments arrive as ``.``-decimal number strings and are
    localized here.
    """
    total = m + n
    signed = raw - (1 << total) if raw >> (total - 1) else raw

    def loc(s: str) -> str:
        return s if decimal == "." else s.replace(".", decimal)

    return FixedPointViz(
        m=m,
        n=n,
        raw=raw,
        exact_text=loc(exact_text),
        stored_text=loc(stored_text),
        error_text=loc(error_text),
        error_lsb=error_lsb,
        hex_text=group_digits(f"{raw:X}", 4, min_width=-(-total // 4), prefix="0x"),
        dec_text=str(raw),
        dec_signed_text=str(signed),
        error_lsb_text=loc(lsb_text),
        bit_weights=_q_bit_weights(m, n),
    )


def _exact_parts(x: Number) -> tuple[int, int]:
    """(numerator, exponent) with ``x == numerator * 2**exponent`` exactly."""
    if isinstance(x, int):
        return x, 0
    sign, man, exp, _bc = x._mpf_
    return (-int(man) if sign else int(man)), int(exp)


def _round_scaled(numerator: int, shift: int) -> int:
    """``numerator * 2**shift`` rounded to the nearest integer, ties to even."""
    if shift >= 0:
        return numerator << shift
    drop = -shift
    magnitude = abs(numerator)
    if drop > magnitude.bit_length() + 1:
        return 0  # under a quarter of an LSB: no need to build 2**drop
    quotient, remainder = divmod(magnitude, 1 << drop)
    half = 1 << (drop - 1)
    if remainder > half or (remainder == half and quotient & 1):
        quotient += 1
    return -quotient if numerator < 0 else quotient


def _q_range_text(m: int, n: int, ctx: EvalContext) -> str:
    """The format's real-valued range, e.g. ``-1.0 to 0.999969482`` for Q1.15."""
    total = m + n
    with mpmath.workprec(total + 8):
        lo = mpmath.ldexp(mpmath.mpf(-1), m - 1)
        hi = -lo - mpmath.ldexp(mpmath.mpf(1), -n)
        return _loc(f"{mpmath.nstr(lo, 9)} to {mpmath.nstr(hi, 9)}", ctx)


def _fix(args: list[Number], ctx: EvalContext) -> Value:
    """Real → Qm.n two's-complement raw value (round to nearest, ties to even).

    Exact in the bits: the argument is taken apart as numerator·2^exponent and
    scaled with integer arithmetic, so nothing here rounds but the one
    quantization step being asked for. The evaluator supplies the argument at
    ``_fix_precision`` bits, which makes that hold for the whole word.
    """
    m, n, total = _q_format(args, "fix")
    x = args[0]
    numerator, exponent = _exact_parts(x)
    shift = exponent + n
    lo, hi = -(1 << (total - 1)), (1 << (total - 1)) - 1
    # Leading-bit position first, so a huge value is refused without scaling it.
    fits = numerator.bit_length() + shift <= total + 1
    scaled = _round_scaled(numerator, shift) if fits else 0
    if not fits or not lo <= scaled <= hi:
        shown = _loc(mpmath.nstr(to_mpf(x), 8), ctx)
        raise FunctionDomainError(
            f"fix: {shown} does not fit Q{m}.{n} (range {_q_range_text(m, n, ctx)})"
        )
    raw = scaled & ((1 << total) - 1)
    # What rounding dropped, still exact: err == residue * 2**exponent.
    residue = numerator - (scaled << -shift) if shift < 0 else 0
    with mpmath.workprec(max(mpmath.mp.prec, total + FIX_GUARD_BITS)):
        exact_text = mpmath.nstr(to_mpf(x), 8)
        stored_text = mpmath.nstr(mpmath.ldexp(mpmath.mpf(scaled), -n), 8)
        err = mpmath.ldexp(to_mpf(residue), exponent)
        err_lsb = float(mpmath.ldexp(to_mpf(abs(residue)), shift)) if residue else 0.0
    # Bits of the word below what a stored real's working precision reaches.
    beyond = scaled.bit_length() - WORKING_PREC if ctx.limited_input else None
    if beyond is not None and beyond > -4:
        bound_lsb = 2.0**beyond
        if beyond >= 1:
            limit = f"low {beyond} bit{'s' if beyond > 1 else ''} beyond"
        else:
            limit = "last bit at the limit of"
        note = f"Q{m}.{n}, {limit} the input's {WORKING_DPS}-digit precision"
        error_text = "≤ " + mpmath.nstr(mpmath.ldexp(mpmath.mpf(1), beyond - n), 3)
        lsb_text = f"≤ {bound_lsb:.3g} LSB"
        err_lsb = bound_lsb
    else:
        error_text = mpmath.nstr(err, 3) if residue else "0"
        # `Q{m}.{n}` is a format tag, not a number: localize only the error value.
        note = f"Q{m}.{n}, quantization error = {_loc(error_text, ctx)}"
        if not residue:
            lsb_text = "0 LSB"
        else:
            # A real error must never read as none: not when it rounds to 0.00
            # LSB, and not when it underflows the float entirely (1e-5000).
            err_lsb = err_lsb or sys.float_info.min
            lsb_text = "<0.01 LSB" if err_lsb < 0.005 else f"{err_lsb:.2f} LSB"
    viz = _fixed_viz(
        m,
        n,
        raw,
        exact_text=exact_text,
        stored_text=stored_text,
        error_text=error_text,
        error_lsb=err_lsb,
        lsb_text=lsb_text,
        decimal=ctx.decimal,
    )
    return Value(raw, declared_width=total, note=note, viz=viz)


def _unfix(args: list[Number], ctx: EvalContext) -> Value:
    """Qm.n two's-complement raw value → real, exactly."""
    raw = _int_arg(args, 0, "unfix")
    m, n, total = _q_format(args, "unfix")
    wrapped = raw & ((1 << total) - 1)
    signed = wrapped - (1 << total) if wrapped >> (total - 1) else wrapped
    # At the word's own width, so the real holds every bit and fix() of it
    # returns the same word however wide the format is.
    with mpmath.workprec(max(mpmath.mp.prec, total + 2)):
        real = mpmath.ldexp(mpmath.mpf(signed), -n)
        text = mpmath.nstr(real, 8)
    viz = _fixed_viz(
        m,
        n,
        wrapped,
        exact_text=text,
        stored_text=text,  # decoding is exact: no quantization step
        error_text="0",
        error_lsb=0.0,
        lsb_text="0 LSB",
        decimal=ctx.decimal,
    )
    note = f"from Q{m}.{n}"
    # A raw value is in range read either way: as the unsigned word or as the
    # signed number it encodes. Anything else lost bits to the mask above.
    if not -(1 << (total - 1)) <= raw < (1 << total):
        note += f" (raw value wrapped to {total} bits)"
    return Value(real, note=note, viz=viz)


# -- IEEE-754 ----------------------------------------------------------------------


def _float_pack(width: int) -> Handler:
    fmt = ">f" if width == 32 else ">d"

    def handler(args: list[Number], ctx: EvalContext) -> Value:
        name = f"float{width}"
        x = mpmath.mpf(args[0])
        try:
            fv = float_views(x, width, ctx.decimal)
        except OverflowError:
            raise FunctionDomainError(f"{name}: value does not fit the format") from None
        assert fv is not None  # width is always 32 or 64
        stored = struct.unpack(fmt, fv.bits.to_bytes(width // 8, "big"))[0]
        if math.isinf(stored):  # finite input packed to inf: out of range
            raise FunctionDomainError(f"{name}: value does not fit the format")
        stored_text = _loc(mpmath.nstr(mpmath.mpf(stored), 9), ctx)
        viz = FloatBitsViz(
            width=width,
            exp_width=fv.exp_width,
            man_width=fv.man_width,
            bits=fv.bits,
            hex_text=fv.hex,
            exact_text=_loc(mpmath.nstr(x, 9), ctx),
            stored_text=stored_text,
            rounded=mpmath.mpf(stored) != x,
            sign_text=fv.sign_text,
            exponent_text=fv.exponent_text,
            mantissa_text=fv.mantissa_text,
        )
        return Value(fv.bits, declared_width=width,
                     note=f"{name} stores {stored_text}", viz=viz)

    return handler


def _float_unpack(width: int) -> Handler:
    fmt = ">f" if width == 32 else ">d"

    def handler(args: list[Number], ctx: EvalContext) -> Value:
        name = f"unfloat{width}"
        v = _int_arg(args, 0, name) & ((1 << width) - 1)
        decoded = struct.unpack(fmt, v.to_bytes(width // 8, "big"))[0]
        if math.isinf(decoded) or math.isnan(decoded):
            raise FunctionDomainError(f"{name}: pattern decodes to inf/nan")
        real = mpmath.mpf(decoded)
        fv = float_views(real, width, ctx.decimal)
        assert fv is not None  # width is always 32 or 64
        text = _loc(mpmath.nstr(real, 9), ctx)
        viz = FloatBitsViz(
            width=width,
            exp_width=fv.exp_width,
            man_width=fv.man_width,
            bits=fv.bits,
            hex_text=fv.hex,
            exact_text=text,
            stored_text=text,  # decoding is exact: nothing is rounded
            rounded=False,
            sign_text=fv.sign_text,
            exponent_text=fv.exponent_text,
            mantissa_text=fv.mantissa_text,
        )
        return Value(real, note=f"from float{width} 0x{v:X}", viz=viz)

    return handler


_BITS = "Bit utilities"
_CLOCK = "Clock & units"
_MEM = "Memory"
_FIXED = "Fixed-point"
_FLOAT = "Floating point"

_TOOLKIT: list[tuple[str, tuple[int, int], str, str, str, str, Handler]] = [
    ("clog2", (1, 1), "n", _BITS,
     "Ceiling log2 — address width for N entries.", "clog2(300) = 9", _clog2),
    ("flog2", (1, 1), "n", _BITS,
     "Floor log2 — index of the highest set bit.", "flog2(300) = 8", _flog2),
    ("mask", (1, 1), "n", _BITS, "N low bits set: (1<<n)-1.", "mask(12) = 0xFFF", _mask_fn),
    ("bit", (1, 1), "n", _BITS, "Single set bit: 1<<n.", "bit(7) = 0x80", _bit_fn),
    ("popcount", (1, 1), "v", _BITS, "Number of set bits (within the word size).",
     "popcount(0xF0F0)", _popcount),
    ("parity", (1, 1), "v", _BITS,
     "XOR of all bits: 1 if odd number set.", "parity(0b1011) = 1", _parity),
    ("revbits", (1, 2), "v, width", _BITS, "Reverse bit order in the word (or in `width` bits).",
     "revbits(0b1101, 4) = 0b1011", _revbits),
    ("byteswap16", (1, 1), "v", _BITS, "Swap byte order in 16 bits (endianness).",
     "byteswap16(0x1234) = 0x3412", _byteswap(16)),
    ("byteswap32", (1, 1), "v", _BITS, "Swap byte order in 32 bits (endianness).",
     "byteswap32(0xDEADBEEF)", _byteswap(32)),
    ("byteswap64", (1, 1), "v", _BITS, "Swap byte order in 64 bits (endianness).",
     "byteswap64(0x0123456789ABCDEF)", _byteswap(64)),
    ("sext", (2, 2), "v, bits", _BITS,
     "Sign-extend the low `bits` up to the word size.", "sext(0xFF, 8)", _sext),
    ("zext", (2, 2), "v, bits", _BITS,
     "Zero-extend: keep only the low `bits`.", "zext(0x1FF, 8) = 0xFF", _zext),
    ("rol", (2, 2), "v, n", _BITS, "Rotate left within the word size.", "rol(0x80, 1)",
     _rotate(True)),
    ("ror", (2, 2), "v, n", _BITS, "Rotate right within the word size.", "ror(1, 1)",
     _rotate(False)),
    ("period", (1, 1), "f", _CLOCK, "Clock period from frequency: 1/f, shown with SI suffix.",
     "period(100M) = 10n", _period),
    ("freq", (1, 1), "t", _CLOCK, "Frequency from period: 1/t, shown with SI suffix.",
     "freq(8n) = 125M", _freq),
    ("clkdiv", (2, 2), "f_clk, f_target", _CLOCK,
     "Nearest integer divider round(f_clk/f_target), with achieved-rate error.",
     "clkdiv(50M, 115200) = 434", _clkdiv),
    ("mem", (2, 2), "depth, width", _MEM,
     "RAM/ROM sizing: total bits, address width, capacity in bytes.",
     "mem(4096, 36) = 147456", _mem),
    ("fix", (3, 3), "value, m, n", _FIXED,
     "Real → fixed-point Qm.n raw value (two's complement; nearest, ties to even).",
     "fix(0.7071, 1, 15) = 0x5A82", _fix),
    ("unfix", (3, 3), "raw, m, n", _FIXED,
     "Fixed-point Qm.n raw value → real.", "unfix(0x5A82, 1, 15)", _unfix),
    ("float32", (1, 1), "x", _FLOAT,
     "IEEE-754 single: the 32-bit pattern of x, as an integer.",
     "float32(1.5) = 0x3FC0_0000", _float_pack(32)),
    ("float64", (1, 1), "x", _FLOAT,
     "IEEE-754 double: the 64-bit pattern of x, as an integer.",
     "float64(1.5)", _float_pack(64)),
    ("unfloat32", (1, 1), "bits", _FLOAT,
     "Decode a 32-bit IEEE-754 pattern back to the real value.",
     "unfloat32(0x3FC00000) = 1.5", _float_unpack(32)),
    ("unfloat64", (1, 1), "bits", _FLOAT,
     "Decode a 64-bit IEEE-754 pattern back to the real value.",
     "unfloat64(0x3FF8000000000000)", _float_unpack(64)),
]


def register_fpga_functions() -> None:
    for name, arity, params, category, summary, example, handler in _TOOLKIT:
        _register(name, arity, params, category, summary, example, handler)
    # fix() is the one function whose answer can be wider than the working
    # precision: it tells the evaluator how many bits its value needs.
    FUNCTIONS["fix"] = dataclasses.replace(FUNCTIONS["fix"], precision=_fix_precision)


register_fpga_functions()
