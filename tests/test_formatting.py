"""Tests for formatting utilities."""

from agenttop.formatting import human_cost, human_duration_ms, human_number, human_tokens


def test_human_number_billions():
    assert human_number(2_574_001_093) == "2.6B"
    assert human_number(1_000_000_000) == "1.0B"


def test_human_number_millions():
    assert human_number(85_605_600) == "85.6M"
    assert human_number(1_512_626) == "1.5M"
    assert human_number(1_000_000) == "1.0M"


def test_human_number_thousands():
    assert human_number(1_234) == "1.2K"
    assert human_number(5_266) == "5.3K"
    assert human_number(1_000) == "1.0K"


def test_human_number_small():
    assert human_number(500) == "500"
    assert human_number(0) == "0"
    assert human_number(999) == "999"


def test_human_number_negative():
    assert human_number(-1_500_000) == "-1.5M"
    assert human_number(-2_500) == "-2.5K"


def test_human_cost_small():
    assert human_cost(0.50) == "$0.50"
    assert human_cost(513.63) == "$513.63"
    assert human_cost(0) == "$0.00"


def test_human_cost_large():
    assert human_cost(1234.5) == "$1.2K"
    assert human_cost(5_000_000) == "$5.0M"


def test_human_tokens_zero():
    assert human_tokens(0) == "0"


def test_human_tokens_nonzero():
    assert human_tokens(85_605_600) == "85.6M"
    assert human_tokens(1_234) == "1.2K"


def test_human_duration_ms():
    assert human_duration_ms(668_922_566) == "7.7 days"
    assert human_duration_ms(7_200_000) == "2.0 hours"
    assert human_duration_ms(180_000) == "3 min"
    assert human_duration_ms(5_000) == "5s"
