"""Help generation: categorized overview and signatures from the live tables."""

from __future__ import annotations

from radix.engine.functions import FUNCTIONS
from radix.engine.help import general_help, topic_help
from radix.session import Session


def test_general_help_is_categorized_with_signatures() -> None:
    text = general_help()
    for category in (
        "Trigonometry",
        "Hyperbolic",
        "Logarithms & exponentials",
        "Roots & rounding",
        "Bit utilities",
        "Clock & units",
        "Fixed-point",
        "Floating point",
        "Time",
    ):
        assert category in text
    clog2_line = next(
        line for line in text.splitlines() if line.strip().startswith("clog2(")
    )
    assert "clog2(n)" in clog2_line
    assert "address width" in clog2_line


def test_topic_help_shows_real_signature() -> None:
    fix_help = topic_help("fix")
    assert fix_help is not None and fix_help.startswith("fix(value, m, n)")
    rol_help = topic_help("rol")
    assert rol_help is not None and rol_help.startswith("rol(v, n)")


def test_every_function_declares_params_and_category() -> None:
    for spec in FUNCTIONS.values():
        assert spec.category, spec.name
        n_params = len([p for p in spec.params.split(",") if p.strip()])
        assert n_params == spec.arity[1], spec.name  # names match max arity


def test_topic_help_csr() -> None:
    csr_help = topic_help("csr")
    assert csr_help is not None
    assert csr_help.startswith("csr NAME = FIELD[msb:lsb]")
    assert "csr(x, EN[7] CMD[3:0])" in csr_help  # one-shot form documented inline


def test_general_help_contains_csr() -> None:
    text = general_help()
    assert "csr" in text


def test_every_function_example_evaluates() -> None:
    session = Session()
    for spec in FUNCTIONS.values():
        expression = spec.example.split(" = ")[0]
        session.evaluate(expression, commit=False)  # must not raise


def test_topic_help_counts_arguments_in_plain_english() -> None:
    assert "(1 argument)" in (topic_help("sin") or "")
    assert "(2 arguments)" in (topic_help("clkdiv") or "")
    assert "(1–2 arguments)" in (topic_help("revbits") or "")
    assert "argument(s)" not in (topic_help("fix") or "")


def test_general_help_intro_can_be_replaced_for_a_front_end_with_keys() -> None:
    # The phone has a keypad: "keyboard-first — no buttons" is the desktop's line.
    text = general_help(intro="Type an expression and press =.")
    assert "Type an expression and press =." in text
    assert "keyboard-first" not in text
    assert "keyboard-first" in general_help()  # the desktop default is unchanged
