import pytest

from plc_code.executor.ladder.fixedpoint import (
    DINT_MAX,
    DINT_MIN,
    DIntOverflowError,
    add,
    div_trunc,
    mul,
    neg,
    sub,
    to_dint,
)


class TestDivTrunc:
    """DInt division truncates toward zero (not floor)."""

    def test_negative_dividend_truncates_toward_zero(self) -> None:
        assert div_trunc(-7, 2) == -3  # floor would give -4

    def test_negative_divisor_truncates_toward_zero(self) -> None:
        assert div_trunc(7, -2) == -3

    def test_both_negative(self) -> None:
        assert div_trunc(-7, -2) == 3

    def test_positive_is_plain_floor(self) -> None:
        assert div_trunc(7, 2) == 3

    def test_exact_division(self) -> None:
        assert div_trunc(8192, 16384) == 0
        assert div_trunc(-16384, 16384) == -1


class TestOverflow:
    """32-bit overflow raises; in-range values pass through."""

    def test_to_dint_in_range_ok(self) -> None:
        assert to_dint(DINT_MAX) == DINT_MAX
        assert to_dint(DINT_MIN) == DINT_MIN

    def test_to_dint_overflow_raises(self) -> None:
        with pytest.raises(DIntOverflowError):
            to_dint(DINT_MAX + 1)

    def test_mul_overflow_raises(self) -> None:
        with pytest.raises(DIntOverflowError):
            mul(2_000_000, 2_000_000)  # 4e12 > 2^31

    def test_mul_in_range_ok(self) -> None:
        # the Q14 worst-case product of the kinematics design stays in range
        assert mul(25_560, 16_384) == 25_560 * 16_384


class TestArithmetic:
    def test_add_sub_neg(self) -> None:
        assert add(2, 3) == 5
        assert sub(2, 3) == -1
        assert neg(5) == -5
