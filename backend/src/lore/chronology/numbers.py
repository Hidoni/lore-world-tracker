"""Exact numeric utilities shared by the whole chronology engine (``chronology-engine.md`` §2).

- Strict parsing/formatting of moment and signed integer strings (``time-model.md`` §2.2).
- Sortable keys (``time-model.md`` §2.3).
- Floor division and modulo (floor semantics for negatives).
- Rationals (``time-model.md`` §2.4): :class:`fractions.Fraction` is exact and always normalized
  (gcd 1, positive denominator), so it is the rational type; helpers add the wire format and the
  error codes the TypeScript twin (``packages/chronology/src/numbers.ts``) shares.
- Big-number display: digit grouping and scientific notation with half-even rounding.

Errors raise :class:`NumberError` with a stable ``code`` (``invalid_number``, ``invalid_key``,
``division_by_zero``), the same codes the conformance vectors use.
"""

import math
import re
from fractions import Fraction
from typing import Literal

MAX_DIGITS = 1000
"""Every moment, duration and offset has at most 1000 decimal digits (``time-model.md`` §2.2)."""

KEY_PREFIX_LENGTH = 4

TIMES_TEN = " \u00d7 10^"
"""Separator between mantissa and exponent in display notation: ``3.17 × 10^99``."""  # noqa: RUF001

_MOMENT = re.compile(r"(0|[1-9][0-9]*)", re.ASCII)
_SIGNED = re.compile(r"(0|-?[1-9][0-9]*)", re.ASCII)
_KEY = re.compile(r"([0-9]{4})(0|[1-9][0-9]*)", re.ASCII)
_MAX_VALUE = 10**MAX_DIGITS  # exclusive bound on magnitudes

type NumberErrorCode = Literal["invalid_number", "invalid_key", "division_by_zero"]

Rational = Fraction
"""The rational type: exact, always normalized. Never construct it from a ``float``."""


class NumberError(ValueError):
    """A numeric input the engine rejects. ``code`` is shared with the TypeScript engine."""

    def __init__(self, code: NumberErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: NumberErrorCode = code


def _check_magnitude(n: int) -> None:
    if not -_MAX_VALUE < n < _MAX_VALUE:
        raise NumberError("invalid_number", f"more than {MAX_DIGITS} digits")


# --- integer strings -----------------------------------------------------------------------------


def parse_moment(text: str) -> int:
    """Parse a canonical non-negative decimal string (no sign, leading zeros or whitespace)."""
    if len(text) > MAX_DIGITS or _MOMENT.fullmatch(text) is None:
        raise NumberError("invalid_number", f"not a moment string: {text[:40]!r}")
    return int(text)


def format_moment(n: int) -> str:
    """Format a moment (``0 ≤ n < 10^1000``) as its canonical decimal string."""
    if n < 0:
        raise NumberError("invalid_number", "a moment cannot be negative")
    _check_magnitude(n)
    return str(n)


def parse_signed(text: str) -> int:
    """Parse a canonical signed decimal string (``-0`` and leading zeros are rejected)."""
    if len(text.removeprefix("-")) > MAX_DIGITS or _SIGNED.fullmatch(text) is None:
        raise NumberError("invalid_number", f"not a signed integer string: {text[:40]!r}")
    return int(text)


def format_signed(n: int) -> str:
    """Format a signed integer (``|n| < 10^1000``) as its canonical decimal string."""
    _check_magnitude(n)
    return str(n)


# --- sortable keys -------------------------------------------------------------------------------


def sortable_key(n: int) -> str:
    """Encode ``n ≥ 0`` so that byte-wise order equals numeric order: 4-digit length + digits."""
    digits = format_moment(n)
    return f"{len(digits):0{KEY_PREFIX_LENGTH}d}{digits}"


def from_sortable_key(key: str) -> int:
    """Decode a sortable key, rejecting any string :func:`sortable_key` cannot produce."""
    match = _KEY.fullmatch(key)
    if match is None or int(match[1]) != len(match[2]) or len(match[2]) > MAX_DIGITS:
        raise NumberError("invalid_key", f"not a sortable key: {key[:40]!r}")
    return int(match[2])


# --- floor division ------------------------------------------------------------------------------


def floor_div(a: int, b: int) -> int:
    """``⌊a / b⌋`` (rounds towards -infinity, unlike truncating division)."""
    if b == 0:
        raise NumberError("division_by_zero", "division by zero")
    return a // b


def floor_mod(a: int, b: int) -> int:
    """``a - b*⌊a / b⌋``: the result has the sign of ``b`` (``-1 mod 7 = 6``)."""
    if b == 0:
        raise NumberError("division_by_zero", "division by zero")
    return a % b


# --- rationals -----------------------------------------------------------------------------------


def rational(num: int, den: int = 1) -> Rational:
    """The normalized rational ``num/den`` (``den`` may be negative, not zero)."""
    if den == 0:
        raise NumberError("division_by_zero", "rational with a zero denominator")
    return Fraction(num, den)


def rational_from_int(n: int) -> Rational:
    return Fraction(n)


def rational_div(a: Rational, b: Rational) -> Rational:
    if b == 0:
        raise NumberError("division_by_zero", "division by zero")
    return a / b


def rational_compare(a: Rational, b: Rational) -> Literal[-1, 0, 1]:
    return -1 if a < b else 1 if a > b else 0


def rational_floor(a: Rational) -> int:
    return math.floor(a)


def rational_frac(a: Rational) -> Rational:
    """``a - ⌊a⌋``, in ``[0, 1)``."""
    return a - math.floor(a)


def parse_rational(num: str, den: str) -> Rational:
    """Parse integer strings into a normalized rational (non-normalized input is normalized)."""
    return rational(parse_signed(num), parse_signed(den))


def format_rational(value: Rational) -> dict[str, str]:
    """The wire form ``{"num": …, "den": …}`` (normalized)."""
    return {"num": format_signed(value.numerator), "den": format_signed(value.denominator)}


# --- display -------------------------------------------------------------------------------------


def _group(digits: str, separator: str) -> str:
    if not separator:
        return digits
    head = len(digits) % 3 or 3
    groups = [digits[:head]] + [digits[i : i + 3] for i in range(head, len(digits), 3)]
    return separator.join(groups)


def _round_half_even(digits: str, keep: int) -> tuple[str, int]:
    """Round the digit string ``digits`` to ``keep`` digits; returns (digits, exponent carry)."""
    kept, rest = digits[:keep], digits[keep:]
    first, tail = rest[:1], rest[1:]
    round_up = first > "5" or (first == "5" and (tail.strip("0") != "" or int(kept[-1]) % 2 == 1))
    if not round_up:
        return kept, 0
    bumped = str(int(kept) + 1)
    if len(bumped) > keep:  # 999… → 1000…: one more digit before the point
        return bumped[:keep], 1
    return bumped, 0


def format_integer(
    n: int,
    *,
    digit_group: str = ",",
    scientific_threshold: int = 16,
    significant_digits: int = 4,
    plain: bool = False,
) -> str:
    """Display an integer: grouped digits, or scientific notation from a number of digits on.

    Scientific notation rounds to ``significant_digits`` significant digits, **half to even**,
    drops trailing zeros of the mantissa and joins it with :data:`TIMES_TEN` (``3.17e99`` when
    ``plain``).
    The mantissa is never grouped. Negative numbers get a leading ``-``. Display options are
    ``chronology-engine.md`` §3.11 ``display`` values (defaults match).
    """
    if scientific_threshold < 1 or significant_digits < 1:
        raise NumberError("invalid_number", "threshold and significant digits must be ≥ 1")
    _check_magnitude(n)
    sign = "-" if n < 0 else ""
    digits = str(abs(n))
    if len(digits) < scientific_threshold:
        return sign + _group(digits, digit_group)
    exponent = len(digits) - 1
    if len(digits) > significant_digits:
        mantissa, carry = _round_half_even(digits, significant_digits)
        exponent += carry
    else:
        mantissa = digits
    mantissa = mantissa.rstrip("0") or "0"
    text = mantissa[0] + ("." + mantissa[1:] if len(mantissa) > 1 else "")
    return f"{sign}{text}e{exponent}" if plain else f"{sign}{text}{TIMES_TEN}{exponent}"
