"""Golden tests for the session's mode axes: signedness, word size, integer
display base, and notation — the combinations the main golden file leaves at
their defaults.

SIGNED rows assert both the primary text (the stored, masked bit pattern) and
the ``dec_signed`` lane of the integer views, since signedness is exactly the
difference between those two readings.
"""

from __future__ import annotations

import pytest

from engine_harness import run, run_views

WS8 = {"word_size": 8}
WS16 = {"word_size": 16}
WS64 = {"word_size": 64}

# (input, settings, primary text, dec_signed lane)
SIGNED = [
    # >> is the one operator whose semantics change with the flag
    ("-8 >> 1", {"signed": True}, "4294967292", "-4"),  # 0xFFFF_FFF8, arithmetic
    ("-8 >> 1", {}, "2147483644", "2147483644"),  # logical: 0x7FFF_FFFC
    ("-8 >> 1", {"signed": True, **WS8}, "252", "-4"),  # 0xF8 >> 1 keeps the sign
    ("-8 >> 1", WS8, "124", "124"),  # 0xF8 >> 1 logical
    ("0x80 >> 4", {"signed": True, **WS8}, "248", "-8"),
    ("0x80 >> 4", WS8, "8", "8"),
    (
        "0x8000_0000_0000_0000 >> 8",
        {"signed": True, **WS64},
        str(0xFF80_0000_0000_0000),
        str(-(1 << 55)),
    ),
    (
        "0x8000_0000_0000_0000 >> 8",
        WS64,
        str(1 << 55),
        str(1 << 55),
    ),
    # ~ & | ^ are pattern operations: the flag changes only the signed reading
    ("~0", {"signed": True}, "4294967295", "-1"),
    ("-5 & 0xFF", {"signed": True}, "251", "251"),  # (-5 & mask) & 0xFF = 0xFB
    ("-1 ^ 0", {"signed": True, **WS16}, "65535", "-1"),
    ("-1 | 0", {"signed": True, **WS8}, "255", "-1"),
]


@pytest.mark.parametrize(
    ("text", "settings", "primary", "dec_signed"),
    SIGNED,
    ids=[f"{c[0]}|{c[1]}" for c in SIGNED],
)
def test_signedness(
    text: str, settings: dict[str, object], primary: str, dec_signed: str
) -> None:
    got_primary, views = run_views(text, **settings)
    assert got_primary == primary
    assert views.dec_signed == dec_signed


# -- word sizes 16 and 64 (8 and 32 are covered elsewhere) --------------------

WORD_SIZES = [
    ("~0", WS16, "65535"),
    ("~0", WS64, str(2**64 - 1)),
    ("1 << 16", WS16, "0"),  # shifted out of the word entirely
    ("1 << 16", {}, "65536"),
    ("1 << 63", WS64, str(1 << 63)),
    ("1 << 15 >> 15", WS16, "1"),
    # plain arithmetic never masks, at any word size
    ("2**64", WS16, str(2**64)),
    ("2**64 + 1", WS8, str(2**64 + 1)),
]


@pytest.mark.parametrize(
    ("text", "settings", "expected"),
    WORD_SIZES,
    ids=[f"{c[0]}|{c[1]}" for c in WORD_SIZES],
)
def test_word_sizes(text: str, settings: dict[str, object], expected: str) -> None:
    assert run(text, **settings) == expected


# -- integer display base ------------------------------------------------------

INT_BASE = [
    # negative results wrap to word-size two's complement, matching the panel
    ("-1", {"int_base": "hex"}, "0xFFFF_FFFF"),
    ("-1", {"int_base": "hex", **WS8}, "0xFF"),
    ("-1", {"int_base": "hex", "signed": True}, "0xFFFF_FFFF"),  # flag-independent
    ("-2", {"int_base": "bin", **WS8}, "0b1111_1110"),
    # non-negative values render at natural width, nibble-grouped
    ("255", {"int_base": "hex"}, "0xFF"),
    ("4096", {"int_base": "hex"}, "0x1000"),
    ("10", {"int_base": "bin"}, "0b1010"),
    ("1.5", {"int_base": "hex"}, "1.5"),  # reals ignore the integer base
]


@pytest.mark.parametrize(
    ("text", "settings", "expected"),
    INT_BASE,
    ids=[f"{c[0]}|{c[1]}" for c in INT_BASE],
)
def test_int_base_display(text: str, settings: dict[str, object], expected: str) -> None:
    assert run(text, **settings) == expected


# -- notation ------------------------------------------------------------------

NOTATION = [
    ("1234", {"notation": "sci"}, "1.234e+3"),
    ("1234", {"notation": "eng_si"}, "1.234k"),
    ("12345", {"notation": "eng"}, "12.345e+3"),
    ("0.000005", {"notation": "eng"}, "5e-6"),
    ("0.05", {"notation": "sci"}, "5e-2"),
]


@pytest.mark.parametrize(
    ("text", "settings", "expected"),
    NOTATION,
    ids=[f"{c[0]}|{c[1]}" for c in NOTATION],
)
def test_notation(text: str, settings: dict[str, object], expected: str) -> None:
    assert run(text, **settings) == expected
