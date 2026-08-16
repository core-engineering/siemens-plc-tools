"""Bit-exact replay of the 18 001 a·sin(b) test vectors through the ladder interpreter.

Fixture paths are anchored to this file's location so the suite passes from
both the repo root and the package directory.  The fixture directory is
auto-registered as a sub-block search path by ``create_harness``, so
``ABS``/``SIGN`` and the ``DataSafetyKinematics`` constant DB (with its
``LutSinQ14`` array initialisers) resolve automatically — no manual
registration.
"""

import csv
from collections.abc import Generator
from pathlib import Path

from plc_code.executor import FBTestHarness, create_harness

FIX = Path(__file__).parent.parent / "fixtures" / "ladder"


def _make_harness() -> FBTestHarness:
    """Create a harness; the LUT DB auto-loads from the fixture search path."""
    h = create_harness(FIX / "SinCalculation.s7dcl")
    # Touch the auto-loaded DB so a load failure fails loudly here, not as a
    # silently-wrong replay (indices 0..901 -> 902 cells).
    assert (
        len(h.runtime.global_dbs["DataSafetyKinematics"].LutSinQ14) == 902
    ), "DataSafetyKinematics.LutSinQ14 did not auto-load with 902 entries"
    return h


def _vectors() -> Generator[tuple[int, int, int, bool], None, None]:
    with open(FIX / "test_vectors.csv", newline="") as f:
        for row in csv.DictReader(f):
            yield (
                int(row["angleCenti"]),
                int(row["lengthMm"]),
                int(row["expectedMm"]),
                bool(int(row["fault"])),
            )


def test_spot_checks() -> None:
    """Verify hand-picked angle→result pairs and the fault boundary."""
    h = _make_harness()
    for angle, expected in [(3000, 6553), (-4500, -9267), (4567, 9375), (9000, 13106)]:
        h.set_inputs(angle=angle, length=13106)
        h.execute()
        assert h.get_output("result") == expected, f"angle={angle}"
        assert not h.get_output("fault")
    h.set_inputs(angle=9050, length=13106)
    h.execute()
    assert h.get_output("fault")


def test_full_18001_vectors_bit_exact() -> None:
    """Replay all 18 001 CSV vectors and confirm bit-exact agreement."""
    h = _make_harness()
    mismatches: list[tuple[int, int, int, object, bool]] = []
    n = 0
    for angle, length, expected, fault in _vectors():
        h.set_inputs(angle=angle, length=length)
        h.execute()
        n += 1
        got_result = h.get_output("result")
        got_fault = bool(h.get_output("fault"))
        if got_result != expected or got_fault != fault:
            mismatches.append((angle, got_result, expected, got_fault, fault))
    assert n == 18001, f"expected 18001 vectors, replayed {n}"
    assert not mismatches, f"bit-exact mismatches (first 10 of {len(mismatches)}): {mismatches[:10]}"
