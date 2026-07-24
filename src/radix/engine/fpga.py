"""FPGA/HDL toolkit functions: bit utilities, clock helpers, fixed-point Qm.n.

Registered into the same FUNCTIONS table as the math functions, so help text
and evaluation stay in one place. Handlers may return a plain number or a
full Value when they carry display metadata (declared width, SI-suffix
preference, quantization-error note).
"""

from __future__ import annotations

import math
import struct

import mpmath

from radix.engine.formatter import float_views, format_si
from radix.engine.functions import (
    EvalContext,
    FunctionDomainError,
    Handler,
    _register,
)
from radix.engine.values import Number, Value
from radix.engine.viz import ClockViz, FixedPointViz, FloatBitsViz, MemViz

MAX_MASK_BITS = 1_000_000
# mem() sizing converts to float for the capacity string and the utilization
# bar, which overflows above ~1.8e308. Capping each dimension keeps the product
# (and so every derived float) comfortably inside that, at a ceiling no real
# device comes near.
MAX_MEM_DIM = 1 << 64


def _int_arg(args: list[Number], i: int, what: str) -> int:
    x = args[i]
    if isinstance(x, int):
        return x
    raise FunctionDomainError(f"{what}: argument {i + 1} must be an integer")


def _word_mask(ctx: EvalContext) -> int:
    return (1 << ctx.word_size) - 1


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
    viz = ClockViz(freq_text=format_si(mpmath.mpf(args[0])), period_text=format_si(t))
    return Value(t, prefer_si=True, viz=viz)


def _freq(args: list[Number], ctx: EvalContext) -> Value:
    f = _reciprocal(args, "freq")
    viz = ClockViz(freq_text=format_si(f), period_text=format_si(mpmath.mpf(args[0])))
    return Value(f, prefer_si=True, viz=viz)


def _clkdiv(args: list[Number], ctx: EvalContext) -> Value:
    """Nearest integer divider from a reference clock to a target rate."""
    f_clk = mpmath.mpf(args[0])
    f_target = mpmath.mpf(args[1])
    if f_clk <= 0 or f_target <= 0:
        raise FunctionDomainError("clkdiv: frequencies must be positive")
    divisor = max(1, int(mpmath.nint(f_clk / f_target)))
    achieved = f_clk / divisor
    ppm = float((achieved - f_target) / f_target * 1_000_000)
    # Past 1%, percent reads better than ppm.
    error_text = f"{ppm / 10_000:+.2f}%" if abs(ppm) >= 10_000 else f"{ppm:+.0f} ppm"
    # Divided-output shape in ref half-cycles: a /1 "divider" passes the clock
    # through; otherwise a single-edge counter stays high ceil(N/2) ref cycles,
    # so odd dividers get the classic asymmetric duty.
    if divisor == 1:
        wave_high, wave_low = 1, 1
    else:
        wave_high, wave_low = 2 * ((divisor + 1) // 2), 2 * (divisor // 2)
    viz = ClockViz(
        freq_text=format_si(f_clk),
        period_text=format_si(1 / f_clk),
        divisor=divisor,
        target_text=format_si(f_target),
        achieved_text=format_si(achieved),
        error_text=error_text,
        error_ppm=ppm,
        wave_high=wave_high,
        wave_low=wave_low,
        duty_text=f"{100 * wave_high / (wave_high + wave_low):.3g}%",
    )
    note = f"actual {format_si(achieved)}, error {error_text}"
    return Value(divisor, note=note, viz=viz)


# -- memory sizing ---------------------------------------------------------------


def _binary_size(bits: int) -> str:
    size = bits / 8
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024:
            return f"{size:.4g} {unit}"
        size /= 1024
    return f"{size:.4g} PiB"


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
        bytes_text=_binary_size(total_bits),
        utilization=utilization,
        util_text=f"{utilization * 100:.0f}%",
    )
    note = f"addr {addr_bits} bits, {viz.bytes_text}"
    return Value(total_bits, note=note, viz=viz)


# -- fixed-point Qm.n --------------------------------------------------------------


def _q_format(args: list[Number], what: str) -> tuple[int, int, int]:
    m = _int_arg(args, 1, what)
    n = _int_arg(args, 2, what)
    if m < 0 or n < 0 or m + n == 0 or m + n > 128:
        raise FunctionDomainError(f"{what}: need 0 <= m, n and 0 < m+n <= 128")
    return m, n, m + n


def _fix(args: list[Number], ctx: EvalContext) -> Value:
    """Real → Qm.n two's-complement raw value (round to nearest)."""
    m, n, total = _q_format(args, "fix")
    x = mpmath.mpf(args[0])
    scaled = int(mpmath.nint(x * (1 << n)))
    lo, hi = -(1 << (total - 1)), (1 << (total - 1)) - 1
    if not lo <= scaled <= hi:
        raise FunctionDomainError(
            f"fix: {mpmath.nstr(x, 8)} does not fit Q{m}.{n} (range {lo}..{hi} raw)"
        )
    raw = scaled & ((1 << total) - 1)
    quantized = mpmath.mpf(scaled) / (1 << n)
    err = x - quantized
    note = f"Q{m}.{n}, quantization error = {mpmath.nstr(err, 3)}"
    viz = FixedPointViz(
        m=m,
        n=n,
        raw=raw,
        exact_text=mpmath.nstr(x, 8),
        stored_text=mpmath.nstr(quantized, 8),
        error_text=mpmath.nstr(err, 3),
        error_lsb=float(abs(err) * (1 << n)),
    )
    return Value(raw, declared_width=total, note=note, viz=viz)


def _unfix(args: list[Number], ctx: EvalContext) -> Value:
    """Qm.n two's-complement raw value → real."""
    raw = _int_arg(args, 0, "unfix")
    m, n, total = _q_format(args, "unfix")
    wrapped = raw & ((1 << total) - 1)
    signed = wrapped - (1 << total) if wrapped >> (total - 1) else wrapped
    real = mpmath.mpf(signed) / (1 << n)
    text = mpmath.nstr(real, 8)
    viz = FixedPointViz(
        m=m,
        n=n,
        raw=wrapped,
        exact_text=text,
        stored_text=text,  # decoding is exact: no quantization step
        error_text="0",
        error_lsb=0.0,
    )
    return Value(real, note=f"from Q{m}.{n}", viz=viz)


# -- IEEE-754 ----------------------------------------------------------------------


def _float_pack(width: int) -> Handler:
    fmt = ">f" if width == 32 else ">d"

    def handler(args: list[Number], ctx: EvalContext) -> Value:
        name = f"float{width}"
        x = mpmath.mpf(args[0])
        try:
            fv = float_views(x, width)
        except OverflowError:
            raise FunctionDomainError(f"{name}: value does not fit the format") from None
        assert fv is not None  # width is always 32 or 64
        stored = struct.unpack(fmt, fv.bits.to_bytes(width // 8, "big"))[0]
        if math.isinf(stored):  # finite input packed to inf: out of range
            raise FunctionDomainError(f"{name}: value does not fit the format")
        stored_text = mpmath.nstr(mpmath.mpf(stored), 9)
        viz = FloatBitsViz(
            width=width,
            exp_width=fv.exp_width,
            man_width=fv.man_width,
            bits=fv.bits,
            hex_text=fv.hex,
            exact_text=mpmath.nstr(x, 9),
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
        fv = float_views(real, width)
        assert fv is not None  # width is always 32 or 64
        text = mpmath.nstr(real, 9)
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
     "Real → fixed-point Qm.n raw value (two's complement).",
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


register_fpga_functions()
