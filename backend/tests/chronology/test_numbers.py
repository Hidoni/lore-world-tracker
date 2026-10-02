"""Unit and property tests of ``lore.chronology.numbers`` (vectors: cases/numbers/)."""

import decimal
from collections.abc import Callable
from fractions import Fraction
from math import gcd
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from lore.chronology import numbers
from lore.chronology.numbers import NumberError

MAX = 10**numbers.MAX_DIGITS - 1
moments = st.one_of(st.integers(0, 10**6), st.integers(0, MAX))
signed = st.one_of(st.integers(-(10**6), 10**6), st.integers(-MAX, MAX))
nonzero = signed.filter(lambda n: n != 0)
rationals = st.builds(Fraction, st.integers(-(10**30), 10**30), st.integers(1, 10**30))


def _code(error: pytest.ExceptionInfo[NumberError]) -> str:
    return error.value.code


# --- integer strings -----------------------------------------------------------------------------


@given(moments)
def test_moment_round_trip(n: int) -> None:
    assert numbers.parse_moment(numbers.format_moment(n)) == n


@given(signed)
def test_signed_round_trip(n: int) -> None:
    assert numbers.parse_signed(numbers.format_signed(n)) == n


@pytest.mark.parametrize("text", ["", "01", "-1", "+1", " 1", "1 ", chr(0x661), "1" * 1001])
def test_parse_moment_rejects(text: str) -> None:
    with pytest.raises(NumberError) as error:
        numbers.parse_moment(text)
    assert _code(error) == "invalid_number"


@pytest.mark.parametrize("text", ["-0", "-01", "--1", "-", "-" + "1" * 1001, "1" * 1001])
def test_parse_signed_rejects(text: str) -> None:
    with pytest.raises(NumberError, match="signed"):
        numbers.parse_signed(text)


def test_format_rejects_out_of_range() -> None:
    calls: list[Callable[[], object]] = [
        lambda: numbers.format_moment(-1),
        lambda: numbers.format_moment(MAX + 1),
        lambda: numbers.format_signed(-MAX - 1),
    ]
    for call in calls:
        with pytest.raises(NumberError):
            call()
    assert numbers.format_signed(-MAX) == "-" + "9" * 1000


# --- sortable keys -------------------------------------------------------------------------------


@given(moments, moments)
def test_key_order_is_numeric_order(a: int, b: int) -> None:
    ka, kb = numbers.sortable_key(a), numbers.sortable_key(b)
    assert (ka < kb) == (a < b)
    assert (ka == kb) == (a == b)
    # SQLite's BINARY collation compares UTF-8 bytes.
    assert (ka.encode() < kb.encode()) == (a < b)


@given(moments)
def test_key_round_trip(n: int) -> None:
    assert numbers.from_sortable_key(numbers.sortable_key(n)) == n


def test_key_examples() -> None:
    assert [numbers.sortable_key(n) for n in (0, 7, 1023)] == ["00010", "00017", "00041023"]


@pytest.mark.parametrize(
    "key", ["", "0001", "00021", "000201", "00000", "0001x", "1001" + "1" * 1001]
)
def test_from_sortable_key_rejects(key: str) -> None:
    with pytest.raises(NumberError) as error:
        numbers.from_sortable_key(key)
    assert _code(error) == "invalid_key"


# --- floor division ------------------------------------------------------------------------------


@given(signed, nonzero)
def test_floor_identities(a: int, b: int) -> None:
    q, r = numbers.floor_div(a, b), numbers.floor_mod(a, b)
    assert a == b * q + r
    assert 0 <= r < b if b > 0 else b < r <= 0
    assert q == numbers.rational_floor(Fraction(a, b))


def test_floor_examples() -> None:
    assert (numbers.floor_div(-7, 2), numbers.floor_mod(-7, 2)) == (-4, 1)
    assert numbers.floor_mod(-1, 7) == 6
    assert numbers.floor_mod(1, -7) == -6


@pytest.mark.parametrize("operation", [numbers.floor_div, numbers.floor_mod])
def test_floor_division_by_zero(operation: Callable[[int, int], int]) -> None:
    with pytest.raises(NumberError) as error:
        operation(1, 0)
    assert _code(error) == "division_by_zero"


# --- rationals -----------------------------------------------------------------------------------


@given(st.integers(-(10**30), 10**30), st.integers(-(10**30), 10**30).filter(lambda d: d != 0))
def test_rational_is_normalized(num: int, den: int) -> None:
    value = numbers.rational(num, den)
    assert value.denominator > 0
    assert gcd(value.numerator, value.denominator) == 1
    assert value.numerator * den == num * value.denominator
    assert numbers.parse_rational(**numbers.format_rational(value)) == value


@given(rationals, rationals, rationals)
def test_rational_field_laws(a: Fraction, b: Fraction, c: Fraction) -> None:
    zero, one = numbers.rational_from_int(0), numbers.rational_from_int(1)
    assert (a + b) + c == a + (b + c)
    assert a + b == b + a
    assert (a * b) * c == a * (b * c)
    assert a * b == b * a
    assert a * (b + c) == a * b + a * c
    assert a + zero == a
    assert a * one == a
    assert a - a == zero
    if a != 0:
        assert a * numbers.rational_div(one, a) == one
    assert numbers.rational_compare(a, b) == -numbers.rational_compare(b, a)


@given(rationals)
def test_floor_and_frac(a: Fraction) -> None:
    floor, frac = numbers.rational_floor(a), numbers.rational_frac(a)
    assert floor + frac == a
    assert 0 <= frac < 1


def test_rational_errors() -> None:
    with pytest.raises(NumberError) as error:
        numbers.rational(1, 0)
    assert _code(error) == "division_by_zero"
    with pytest.raises(NumberError) as error:
        numbers.rational_div(Fraction(1), Fraction(0))
    assert _code(error) == "division_by_zero"
    with pytest.raises(NumberError) as error:
        numbers.parse_rational("1", "02")
    assert _code(error) == "invalid_number"


# --- display -------------------------------------------------------------------------------------


def _decimal_scientific(n: int, digits: int) -> str:
    value = decimal.Context(prec=digits, rounding=decimal.ROUND_HALF_EVEN, Emax=10**6).plus(
        decimal.Decimal(n)
    )
    sign, mantissa_digits, exponent = value.as_tuple()
    assert isinstance(exponent, int)
    exponent += len(mantissa_digits) - 1
    mantissa = "".join(map(str, mantissa_digits)).rstrip("0") or "0"
    text = mantissa[0] + ("." + mantissa[1:] if len(mantissa) > 1 else "")
    return f"{'-' if sign else ''}{text}e{exponent}"


@given(signed, st.integers(1, 30), st.integers(1, 1001))
def test_scientific_matches_decimal_half_even(n: int, significant: int, threshold: int) -> None:
    text = numbers.format_integer(
        n, scientific_threshold=threshold, significant_digits=significant, plain=True
    )
    if len(str(abs(n))) < threshold:
        assert text.replace(",", "") == str(n)
    else:
        assert text == _decimal_scientific(n, significant)


@given(signed, st.sampled_from(["", ",", " ", ".", "'"]))
def test_grouping_keeps_the_digits(n: int, separator: str) -> None:
    text = numbers.format_integer(n, digit_group=separator, scientific_threshold=1002)
    digits = text.removeprefix("-")
    if not separator:
        assert digits == str(abs(n))
        return
    groups = digits.split(separator)
    assert "".join(groups) == str(abs(n))
    assert all(len(group) == 3 for group in groups[1:])
    assert 1 <= len(groups[0]) <= 3


def test_display_examples() -> None:
    assert (
        numbers.format_integer(317 * 10**97, significant_digits=3) == f"3.17{numbers.TIMES_TEN}99"
    )
    assert numbers.format_integer(0, scientific_threshold=1) == f"0{numbers.TIMES_TEN}0"
    assert numbers.format_integer(-1234567) == "-1,234,567"


@pytest.mark.parametrize(
    ("n", "options"),
    [(5, {"scientific_threshold": 0}), (5, {"significant_digits": 0}), (MAX + 1, {})],
)
def test_display_rejects(n: int, options: dict[str, Any]) -> None:
    with pytest.raises(NumberError):
        numbers.format_integer(n, **options)
