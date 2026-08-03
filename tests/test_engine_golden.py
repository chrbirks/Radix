"""Golden-table tests: the executable spec for the engine.

Each case is (input, expected) evaluated on a fresh default session
(32-bit, unsigned, radians, auto notation) unless a settings dict is given.
`expected` compares against the formatted primary text, so these cases pin
both semantics and display.
"""

from __future__ import annotations

import pytest

from engine_harness import run
from radix.engine.errors import CalcError, EvalError, IncompleteError, LexError, ParseError
from radix.session import Session

# -- literals and suffixes ----------------------------------------------------

LITERALS = [
    ("123", "123"),
    ("1.5", "1.5"),
    ("1.5e-9", "1.5e-9"),
    ("1.5E-9", "1.5e-9"),
    ("0.1 + 0.2", "0.3"),  # no float64 artifacts
    ("0xFF", "255"),
    ("0b1010", "10"),
    ("0o17", "15"),
    ("0xFFFF_0000", "4294901760"),
    ("1_000_000", "1000000"),
    (".5", "0.5"),
    ("4k", "4000"),
    ("4.7k", "4700"),
    ("100n", "1e-7"),
    ("2p", "2e-12"),
    ("3.3M", "3300000"),
    ("1T", "1000000000000"),
    ("32Ki", "32768"),
    ("4Mi", "4194304"),
    ("2Gi", "2147483648"),
    ("1.5Ki", "1536"),
    ("2pi", "6.28318530718"),  # suffix run 'pi' is an identifier, not p·i
    ("2e", "5.43656365692"),  # e as constant when not an exponent
    ("2e3", "2000"),
    ("1.5e+2", "150"),
    # SI suffixes previously untested: f, u, µ, m, G
    ("1f", "1e-15"),
    ("1.5f", "1.5e-15"),
    ("3.3u", "3.3e-6"),
    ("3.3µ", "3.3e-6"),  # micro sign, same key as 'u' in the suffix table
    ("10u", "0.00001"),  # exponent -5: last value auto shows plain
    ("1m", "0.001"),
    ("2.5G", "2500000000"),
]


@pytest.mark.parametrize(("text", "expected"), LITERALS)
def test_literals(text: str, expected: str) -> None:
    assert run(text) == expected


# -- HDL literals ---------------------------------------------------------------

HDL = [
    ("8'hFF", "255"),
    ("12'b1010_1010", "170"),
    ("4'd9", "9"),
    ("8'o17", "15"),
    ('x"FF"', "255"),
    ('x"DEAD_BEEF"', "3735928559"),
    # Prefixed literal forms
    ("hFF", "255"),
    ("xFF", "255"),
    ("hDEAD_BEEF", "3735928559"),
    ("b1010", "10"),
    ("b1010_1010", "170"),
    ("hFF + b1010", "265"),
    ("h12[3:0]", "2"),
]


def test_prefixed_literal_lookalikes_stay_identifiers() -> None:
    # Tails that aren't digits of the base are ordinary (undefined) identifiers.
    for name in ("bad", "h2o", "b102", "x", "h", "b"):
        with pytest.raises(EvalError):
            run(name)
    session = Session()
    session.evaluate("h2o = 3")  # assignable: not a literal shape
    assert session.evaluate("h2o * 2").primary_text == "6"


def test_prefixed_literal_shapes_are_not_assignable() -> None:
    with pytest.raises(ParseError):
        run("b1 = 5")  # b1 lexes as the literal 1


@pytest.mark.parametrize(("text", "expected"), HDL)
def test_hdl_literals(text: str, expected: str) -> None:
    assert run(text) == expected


def test_hdl_literal_width_attached() -> None:
    session = Session()
    outcome = session.evaluate("8'hFF")
    assert outcome.value is not None and outcome.value.declared_width == 8
    outcome = session.evaluate('x"FF"')
    assert outcome.value is not None and outcome.value.declared_width == 8


def test_hdl_value_must_fit_width() -> None:
    with pytest.raises(LexError):
        run("8'h1FF")


# -- precedence and operators ---------------------------------------------------

PRECEDENCE = [
    ("1 + 2 * 3", "7"),
    ("2**10", "1024"),
    ("2**-2", "0.25"),
    ("-2**2", "-4"),  # ** binds tighter than unary minus
    ("2**3**2", "512"),  # right-associative
    ("2^10", "8"),  # XOR, never power
    ("1 | 2 ^ 3 & 4 << 5", "3"),  # | < ^ < & < <<  →  1 | (2 ^ (3 & (4<<5)))
    ("1 + 2 << 3", "24"),  # shifts bind looser than +
    ("7 & 3 + 1", "4"),  # & binds looser than +
    ("10 / 4", "2.5"),
    ("10 / 2", "5"),  # exact division stays int
    ("7 // 2", "3"),
    ("-7 // 2", "-3"),  # truncation toward zero
    ("7 // -2", "-3"),
    ("-7 % 2", "-1"),  # sign of dividend
    ("7 % -2", "1"),
    # real-operand // and % follow the same truncate-toward-zero pair
    ("7.5 // 2", "3"),
    ("-7.5 // 2", "-3"),
    ("7.5 % 2", "1.5"),
    ("-7.5 % 2", "-1.5"),
    # standalone bitwise values (previously only exercised inside one chain)
    ("5 | 2", "7"),
    ("6 ^ 3", "5"),
    ("1 | 2 ^ 4", "7"),  # ^ binds tighter: 1 | (2 ^ 4)
    ("~5", "4294967290"),  # 0xFFFF_FFFA at the 32-bit default
    ("~~5", "5"),
    ("(-2)**3", "-8"),
    # negative real base is fine while the exponent is an integer
    ("(-1.5)**2", "2.25"),
    ("(-1.5)**3", "-3.375"),
    ("(-2)**2.0", "4"),  # integral literal lexes as an exact int
    ("(-2)**(2*1.5)", "-8"),  # integral mpf exponent counts as an integer too
    ("(-0.5)**-2", "4"),
    ("2pi", "6.28318530718"),
    ("3(1+1)", "6"),
    ("(1+1)(2+2)", "8"),
    ("1/2pi", "1.57079632679"),  # implicit mult binds like *
    ("2 3", "6"),  # adjacency with space is still implicit mult
    ("+5", "5"),
    ("--5", "5"),
    ("~0", "4294967295"),  # default word size is 32 bits
    ("~0", "255", {"word_size": 8}),
]


@pytest.mark.parametrize(
    ("text", "expected", "settings"),
    [c if len(c) == 3 else (*c, {}) for c in PRECEDENCE],
)
def test_precedence(text: str, expected: str, settings: dict[str, object]) -> None:
    assert run(text, **settings) == expected


# -- word size, signedness, masking ----------------------------------------------

BITS = [
    ("0xFF << 2", "1020", {}),
    ("0xFF << 2", "252", {"word_size": 8}),  # wraps register-like
    ("1 << 100", "0", {"word_size": 64}),
    ("0x80 >> 4", "8", {"word_size": 8}),  # logical shift when unsigned
    ("0x80 >> 4", "248", {"word_size": 8, "signed": True}),  # arithmetic shift
    ("-1 & 0xFF", "255", {}),  # negative operand wraps into the word first
    ("4.7k * 2", "9400", {"word_size": 8}),  # plain arithmetic is never masked
]


@pytest.mark.parametrize(("text", "expected", "settings"), BITS)
def test_bit_semantics(text: str, expected: str, settings: dict[str, object]) -> None:
    assert run(text, **settings) == expected


def test_bit_op_on_float_is_error() -> None:
    with pytest.raises(EvalError, match="integer"):
        run("1.5 & 3")
    with pytest.raises(EvalError, match="integer"):
        run("~1.5")
    session = Session()
    session.evaluate("4.7n")
    with pytest.raises(EvalError, match="integer"):
        session.evaluate("ans << 2")


# -- functions and constants ------------------------------------------------------

def test_trig_radians_and_degrees() -> None:
    assert run("sin(pi/2)") == "1"
    assert run("sin(90)", angle_deg=True) == "1"
    assert run("asin(1)", angle_deg=True) == "90"
    assert run("cos(0)") == "1"


def test_logs_and_roots() -> None:
    assert run("log(1000)") == "3"
    assert run("ln(e)") == "1"
    assert run("log2(1024)") == "10"
    assert run("sqrt(16)") == "4"
    assert run("floor(2.7)") == "2"
    assert run("ceil(2.1)") == "3"
    assert run("round(2.5)") == "2"  # nint rounds half to even
    assert run("abs(-4)") == "4"


def test_working_precision_exceeds_display_precision() -> None:
    # 1e20 + 1 needs 67 mantissa bits: float64 (53 bits) silently drops the +1,
    # the 25-dps (~83-bit) working precision must not.
    assert run("1e20 + 1 - 1e20") == "1"
    assert run("1/3") == "0.333333333333"  # exactly 12 significant digits


def test_domain_errors() -> None:
    for text in ("sqrt(-1)", "asin(2)", "log(-1)", "ln(0)"):
        with pytest.raises(EvalError):
            run(text)


def test_negative_base_needs_integer_exponent() -> None:
    for text in ("(-2)**0.5", "(-1.5)**2.5"):
        with pytest.raises(EvalError, match="complex"):
            run(text)


def test_operand_guards() -> None:
    with pytest.raises(EvalError):
        run("10**10**10")
    with pytest.raises(EvalError):
        run("1 << 10**9")
    with pytest.raises(EvalError, match="zero"):
        run("1/0")
    with pytest.raises(EvalError, match="zero"):
        run("1//0")


# -- variables and ans -------------------------------------------------------------

def test_variables_and_ans_flow() -> None:
    session = Session()
    outcome = session.evaluate("x = 4.7k")
    assert outcome.kind == "assign" and outcome.target == "x"
    assert session.evaluate("x * 2").primary_text == "9400"
    assert session.evaluate("ans / 2").primary_text == "4700"
    session.evaluate("y = x + 300")
    assert session.evaluate("y").primary_text == "5000"


def test_ans_without_history_is_error() -> None:
    with pytest.raises(EvalError, match="no previous result"):
        Session().evaluate("ans")


def test_reserved_names_cannot_be_assigned() -> None:
    session = Session()
    for name in ("ans", "pi", "e", "sin", "help", "clear"):
        with pytest.raises(EvalError, match="reserved"):
            session.evaluate(f"{name} = 1")


def test_variable_k_needs_explicit_multiply() -> None:
    session = Session()
    session.evaluate("k = 5")
    assert session.evaluate("4k").primary_text == "4000"  # suffix always wins
    assert session.evaluate("4*k").primary_text == "20"


def test_undefined_variable_message() -> None:
    with pytest.raises(EvalError, match="undefined variable 'pk'"):
        run("2pk")


def test_clear_wipes_state() -> None:
    session = Session()
    session.evaluate("x = 1")
    session.evaluate("clear")
    with pytest.raises(EvalError):
        session.evaluate("x")
    with pytest.raises(EvalError):
        session.evaluate("ans")


def test_preview_has_no_side_effects() -> None:
    session = Session()
    session.preview("x = 42")
    with pytest.raises(EvalError):
        session.evaluate("x")
    session.preview("1 + 1")
    with pytest.raises(EvalError):
        session.evaluate("ans")


# -- errors: spans, incompleteness --------------------------------------------------

def test_parse_error_has_caret_position() -> None:
    try:
        run("1 + )")
    except ParseError as exc:
        assert exc.span.start == 4
    else:  # pragma: no cover
        pytest.fail("expected ParseError")


def test_incomplete_input_is_distinguished() -> None:
    for text in ("1 +", "(1 + 2", "sin(", "2 **"):
        with pytest.raises(IncompleteError):
            run(text)
    with pytest.raises(ParseError):
        run("1 + ) 2")


def test_assignment_only_at_line_start() -> None:
    with pytest.raises(CalcError):
        run("1 + (x = 2)")


# -- slicing ---------------------------------------------------------------------

def test_bit_slicing() -> None:
    assert run("0xAB[7:4]") == "10"
    assert run("0xAB[3:0]") == "11"
    assert run("0xAB[3]") == "1"
    assert run("0xAB[2]") == "0"
    session = Session()
    session.evaluate("x = 0xFF")
    assert session.evaluate("x[7:4]").primary_text == "15"


def test_slice_range_errors() -> None:
    with pytest.raises(EvalError, match="invalid bit range"):
        run("0xAB[0:4]")
    with pytest.raises(EvalError, match="outside"):
        run("0xAB[8:0]", word_size=8)
    with pytest.raises(EvalError, match="integer"):
        run("1.5[3]")


# -- CSR field layouts -------------------------------------------------------

def test_csr_define_and_decode() -> None:
    session = Session()
    session.evaluate("csr CTRL = EN[31] IRQ[30:28] ADDR[27:8] CMD[7:0]")
    outcome = session.evaluate("CTRL(0x8C01A0F3)")
    assert outcome.value is not None
    assert outcome.value.note == "EN=1 IRQ=0b000 ADDR=0xC01A0 CMD=0xF3"


def test_csr_bare_command_lists_definitions() -> None:
    session = Session()
    outcome = session.evaluate("csr")
    assert outcome.kind == "csr"
    assert outcome.help_text == "no csrs defined"
    session.evaluate("csr CTRL = EN[31]")
    outcome = session.evaluate("csr")
    assert outcome.help_text == "CTRL = csr EN[31]"


def test_vars_lists_variables_then_csrs() -> None:
    session = Session()
    session.evaluate("x = 5")
    session.evaluate("csr CTRL = EN[31]")
    outcome = session.evaluate("vars")
    assert outcome.help_text == "x = 5\nCTRL = csr EN[31]"


def test_del_removes_csr_and_regresses_on_variables() -> None:
    session = Session()
    session.evaluate("csr CTRL = EN[31]")
    session.evaluate("del CTRL")
    assert session.csrs == {}
    with pytest.raises(EvalError, match="unknown function 'CTRL'"):
        session.evaluate("CTRL(1)")
    session.evaluate("x = 1")
    session.evaluate("del x")
    with pytest.raises(EvalError):
        session.evaluate("x")
    with pytest.raises(EvalError, match="no variable or csr named 'nope'"):
        session.evaluate("del nope")


def test_clear_wipes_csrs_too() -> None:
    session = Session()
    session.evaluate("x = 1")
    session.evaluate("csr CTRL = EN[31]")
    session.evaluate("clear")
    assert session.variables == {}
    assert session.csrs == {}


def test_csr_redefinition_overwrites_silently() -> None:
    session = Session()
    session.evaluate("csr CTRL = A[3:0]")
    session.evaluate("csr CTRL = B[7:0]")
    assert session.csrs["CTRL"].spec_text() == "B[7:0]"
    outcome = session.evaluate("CTRL(0xFF)")
    assert outcome.value is not None
    assert outcome.value.note == "B=0xFF"


def test_csr_variable_collision_both_directions() -> None:
    session = Session()
    session.evaluate("x = 5")
    with pytest.raises(EvalError, match="'x' is already a variable — del it first"):
        session.evaluate("csr x = A[3:0]")
    session.evaluate("csr CTRL = A[3:0]")
    with pytest.raises(EvalError, match="'CTRL' is already a csr — del it first"):
        session.evaluate("CTRL = 5")


def test_csr_reserved_names() -> None:
    session = Session()
    with pytest.raises(EvalError, match="'ans' is reserved and cannot be assigned"):
        session.evaluate("csr ans = A[3:0]")
    with pytest.raises(EvalError, match="'csr' is reserved and cannot be assigned"):
        session.evaluate("csr csr = A[3:0]")
    # No space / bare "=" forms fall through to the ordinary Assign path.
    with pytest.raises(EvalError, match="'csr' is reserved and cannot be assigned"):
        session.evaluate("csr = 3")
    with pytest.raises(EvalError, match="'csr' is reserved and cannot be assigned"):
        session.evaluate("csr=3")


def test_csr_bad_forms_have_exact_spans() -> None:
    session = Session()

    line = "csr CTRL EN[31]"  # missing '='
    with pytest.raises(EvalError) as exc_info:
        session.evaluate(line)
    exc = exc_info.value
    assert exc.message == "csr: expected 'NAME = FIELD[msb:lsb] ...', e.g. csr CTRL = EN[31]"
    assert (exc.span.start, exc.span.end) == (4, 15)

    line = "csr CTRL ="  # empty spec
    with pytest.raises(EvalError) as exc_info:
        session.evaluate(line)
    exc = exc_info.value
    assert exc.message == "csr: expected at least one field, e.g. csr CTRL = EN[31]"
    assert (exc.span.start, exc.span.end) == (10, 10)

    line = "csr 5CTRL = EN[31]"  # not a valid identifier
    with pytest.raises(EvalError) as exc_info:
        session.evaluate(line)
    exc = exc_info.value
    assert exc.message == "'5CTRL' is not a valid csr name"
    assert (exc.span.start, exc.span.end) == (4, 9)

    line = "csr hFF = EN[31]"  # collides with the literal-prefix lexer rule
    with pytest.raises(EvalError) as exc_info:
        session.evaluate(line)
    exc = exc_info.value
    assert exc.message == "'hFF' is not a valid csr name"
    assert (exc.span.start, exc.span.end) == (4, 7)

    line = "csr CTRL = EN[31] EN[7:0]"  # duplicate field name, span shifted into full line
    with pytest.raises(EvalError) as exc_info:
        session.evaluate(line)
    exc = exc_info.value
    assert exc.message == "duplicate field name 'EN'"
    assert (exc.span.start, exc.span.end) == (18, 20)
    assert line[exc.span.start : exc.span.end] == "EN"


def test_csr_word_size_interplay() -> None:
    session = Session()
    assert session.word_size == 32
    session.evaluate("csr CTRL = EN[63]")  # wider than the current word size — fine to define
    with pytest.raises(EvalError, match="field EN\\[63\\] is outside the 32-bit word"):
        session.evaluate("CTRL(1)")
    while session.word_size != 64:
        session.cycle_word_size()
    outcome = session.evaluate("CTRL(1)")
    assert outcome.value is not None


def test_csr_preview_has_no_side_effects() -> None:
    session = Session()
    outcome = session.preview("csr CTRL = EN[31]")
    assert session.csrs == {}
    assert outcome.kind == "csr"
    assert outcome.target == "CTRL"
    assert outcome.help_text == "csr CTRL = EN[31]"
