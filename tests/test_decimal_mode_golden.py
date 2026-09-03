"""Golden tests for comma mode: `,` decimal, `;` argument separator, and the
localized output that reaches results, notes, viz payloads, and signatures.

Period mode is the harness default and is covered by the other golden files;
here every case opts into ``decimal_mode="comma"`` so the shipped app default is
pinned down end to end.
"""

from __future__ import annotations

import pytest

from engine_harness import make_session, run
from radix.engine.errors import CalcError, IncompleteError, LexError
from radix.engine.functions import FUNCTIONS
from radix.engine.help import general_help_html, topic_help
from radix.session import Session
from radix.ui_qt.completer import completions

COMMA = {"decimal_mode": "comma"}


# -- input: both `,` and `.` are decimals in comma mode ------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("3,14 * 2", "6,28"),
        ("3.14 * 2", "6,28"),  # `.` still accepted on input, comma on output
        (",5", "0,5"),  # leading-comma decimal
        ("1/3", "0,333333333333"),
        ("1,5e-9", "1,5e-9"),  # exponent literal
        ("4,7k", "4700"),  # SI suffix, exact int
    ],
)
def test_comma_input_and_output(text: str, expected: str) -> None:
    assert run(text, **COMMA) == expected


@pytest.mark.parametrize(
    "text, settings, expected",
    [
        ("1234", {"notation": "sci"}, "1,234e+3"),
        ("1234", {"notation": "eng"}, "1,234e+3"),
        ("0,00047", {"notation": "eng_si"}, "470u"),
    ],
)
def test_comma_notation(text: str, settings: dict[str, object], expected: str) -> None:
    assert run(text, **COMMA, **settings) == expected


# -- argument separator is `;` in comma mode ----------------------------------

def test_semicolon_separates_arguments() -> None:
    assert run("clkdiv(50M; 115200)", **COMMA) == "434"


def test_comma_in_a_call_is_a_decimal_not_a_separator() -> None:
    # `1,5` is the single value 1.5, so a one-arg call to a two-arg function is
    # an arity error — proof the comma bound into the number, not the arg list.
    with pytest.raises(CalcError):
        run("clkdiv(1,5)", **COMMA)


def test_period_mode_still_uses_comma_arguments() -> None:
    assert run("clkdiv(50M, 115200)", decimal_mode="period") == "434"


# -- mixed separators are malformed -------------------------------------------

def test_mixed_decimal_is_an_error() -> None:
    with pytest.raises(CalcError):
        run("3,1.4", **COMMA)


# -- localized notes and viz payloads -----------------------------------------

def test_note_localizes_its_decimal() -> None:
    session = make_session(**COMMA)
    outcome = session.evaluate("clkdiv(50M; 115200)")
    assert outcome.value is not None
    assert outcome.value.note == "actual 115,207373272k, error +64 ppm"


def test_fixed_point_viz_localizes_but_keeps_the_q_tag() -> None:
    session = make_session(**COMMA)
    outcome = session.evaluate("fix(3,14; 4; 12)")
    assert outcome.value is not None
    viz = outcome.value.viz
    assert viz is not None
    # The Q-format tag keeps its dot; the numbers switch to commas.
    assert outcome.value.note == "Q4.12, quantization error = 0,000107"
    assert viz.exact_text == "3,14"
    assert "," in viz.stored_text and "." not in viz.stored_text


def test_period_mode_viz_keeps_the_period() -> None:
    session = make_session(decimal_mode="period")
    outcome = session.evaluate("fix(3.14, 4, 12)")
    assert outcome.value is not None
    viz = outcome.value.viz
    assert viz is not None
    assert viz.exact_text == "3.14"


# -- field access still parses in comma mode ----------------------------------

def test_field_access_survives_comma_mode() -> None:
    assert run("csr(0xF3; MODE[7:4] CMD[3:0]).MODE", **COMMA) == "15"


# -- round-trip: comma output re-parses in comma mode -------------------------

def test_output_round_trips_through_a_comma_session() -> None:
    session = make_session(**COMMA)
    first = session.evaluate("1/8")
    assert first.value is not None
    text = session.format_value(first.value)  # "0,125"
    again = session.evaluate(text)
    assert again.value is not None
    assert again.value.number == first.value.number


# -- preview renders with the active separators -------------------------------

def test_preview_localizes_separators() -> None:
    outcome = make_session(**COMMA).preview("3,14*2")
    assert outcome.normalized == "3,14 × 2"


# -- signatures use `;` in comma mode -----------------------------------------

def test_topic_help_signature_uses_semicolon() -> None:
    text = topic_help("fix", "; ")
    assert text is not None
    assert text.startswith("fix(value; m; n)")


def test_completer_signature_uses_semicolon() -> None:
    session = Session(decimal_mode="comma")
    displays = {c.name: c.display for c in completions(session)}
    assert displays["fix"] == "fix(value; m; n)"


# -- a decimal comma must be followed by a digit -------------------------------

def test_comma_needs_a_digit_after_it() -> None:
    # The classic typo: `,` between arguments in comma mode. It must not lex
    # `1,` as 1.0 and then implicitly multiply by 2 (= sin(2) = 0.909…).
    with pytest.raises(CalcError) as exc:
        run("sin(1, 2)", **COMMA)
    assert not isinstance(exc.value, IncompleteError)
    assert "';'" in exc.value.message  # points at the separator that was meant
    # A trailing comma at the end of the line is "still typing".
    for text in ("1,", "sin(1,"):
        with pytest.raises(IncompleteError):
            run(text, **COMMA)
    with pytest.raises(LexError):
        run("1e5,5", **COMMA)
    assert run("1,5 + 1", **COMMA) == "2,5"
    assert run("sin(1,5)", **COMMA) == "0,997494986604"


# -- help examples are written in the active syntax ---------------------------

def test_help_examples_are_localized_to_comma_mode() -> None:
    session = Session(decimal_mode="comma")
    text = session.evaluate("help fix").help_text
    assert text is not None
    assert "fix(0,7071; 1; 15) = 0x5A82" in text  # decimal, separator; hex untouched
    csr_text = session.evaluate("help csr").help_text
    assert csr_text is not None and "csr(x; EN[7] CMD[3:0])" in csr_text
    overview = session.evaluate("help").help_text
    assert overview is not None
    assert "4,7k = 4700" in overview and "1,5e-9" in overview
    assert "e.g." in overview  # prose punctuation is not a decimal point
    # The GUI pane builds its overview from the same sources, keyed on the separator.
    assert "4,7k = 4700" in general_help_html(None, "; ")


def test_every_help_example_evaluates_in_comma_mode() -> None:
    session = Session(decimal_mode="comma")
    for spec in FUNCTIONS.values():
        text = session.evaluate(f"help {spec.name}").help_text
        assert text is not None, spec.name
        examples = [line for line in text.splitlines() if line.startswith("Example: ")]
        # `help csr` shows the command block instead (its one-shot form is
        # checked above); every other function must show a runnable example.
        assert examples or spec.name == "csr", spec.name
        for example in examples:
            expression = example.removeprefix("Example: ").split(" = ")[0]
            session.evaluate(expression, commit=False)  # must not raise
