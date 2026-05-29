"""Tests for 1-based array indexing in SCL transpilation.

SCL arrays can be declared with a non-zero lower bound (e.g. Array[1..6] of Real).
Python lists are 0-based, so direct SCL index access must work without offset adjustment.
The executor allocates hi+1 elements when lo>0 so that arr[1]..arr[hi] is valid.
"""

from pathlib import Path

import pytest

from plc_code.executor.harness import create_harness

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestOneBasedArrays:
    """Tests for 1-based and non-zero-lower-bound arrays."""

    def test_one_based_1d_read_write(self) -> None:
        """Array[1..3] of Real: can write and read all elements."""
        harness = create_harness(FIXTURES_DIR / "OneBased1D.s7dcl")
        harness.set_inputs(x=5.0)
        harness.execute()
        out = harness.get_outputs()
        # arr[1]=5, arr[2]=10, arr[3]=15 -> result = 30
        assert out["result"] == pytest.approx(30.0)

    def test_one_based_3d_read_write(self) -> None:
        """Array[1..2, 0..1, 0..1] of Real: can read cube[2,1,1]."""
        harness = create_harness(FIXTURES_DIR / "OneBased3D.s7dcl")
        harness.set_inputs(val=7.0)
        harness.execute()
        out = harness.get_outputs()
        # cube[2,1,1] = val * 2 = 14.0
        assert out["readBack"] == pytest.approx(14.0)
