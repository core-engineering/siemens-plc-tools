"""Fixed-point DInt (signed 32-bit) arithmetic for the F-LAD interpreter.

Semantics match Siemens DInt: 32-bit signed range, division truncates toward
zero (unlike Python's floor `//`), and any result outside the 32-bit range is
an overflow. The Safety design must prove overflow never happens, so an overflow
is raised (not wrapped) — a test that triggers it is a real finding.
"""

from __future__ import annotations

DINT_MIN = -(2**31)
DINT_MAX = 2**31 - 1


class DIntOverflowError(Exception):
    """Raised when a DInt operation produces a value outside the 32-bit range."""


def to_dint(x: int) -> int:
    """Return x if it fits in signed 32-bit, else raise DIntOverflowError."""
    if x < DINT_MIN or x > DINT_MAX:
        raise DIntOverflowError(f"value {x} outside DInt range [{DINT_MIN}, {DINT_MAX}]")
    return x


def div_trunc(a: int, b: int) -> int:
    """Integer division truncating toward zero (Siemens DInt semantics).

    Parameters
    ----------
    a : int
        Dividend.
    b : int
        Divisor.

    Returns
    -------
    int
        Quotient, truncated toward zero, checked for overflow.

    Raises
    ------
    ZeroDivisionError
        If b == 0.
    DIntOverflowError
        If the result overflows the 32-bit signed range.
    """
    if b == 0:
        raise ZeroDivisionError("DInt division by zero")
    q = abs(a) // abs(b)
    return to_dint(q if (a >= 0) == (b >= 0) else -q)


def mul(a: int, b: int) -> int:
    """Multiply two DInts, checking for overflow.

    Raises
    ------
    DIntOverflowError
        If the result overflows the 32-bit signed range.
    """
    return to_dint(a * b)


def add(a: int, b: int) -> int:
    """Add two DInts, checking for overflow.

    Raises
    ------
    DIntOverflowError
        If the result overflows the 32-bit signed range.
    """
    return to_dint(a + b)


def sub(a: int, b: int) -> int:
    """Subtract two DInts, checking for overflow.

    Raises
    ------
    DIntOverflowError
        If the result overflows the 32-bit signed range.
    """
    return to_dint(a - b)


def neg(a: int) -> int:
    """Negate a DInt, checking for overflow.

    Raises
    ------
    DIntOverflowError
        If the result overflows the 32-bit signed range.
    """
    return to_dint(-a)
