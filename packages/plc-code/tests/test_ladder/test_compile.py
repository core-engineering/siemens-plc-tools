"""Integration tests for compiling F-LAD blocks through the harness.

Fixture paths are anchored to this file's location so the suite passes from
both the repo root and the package directory. The fixture directory is the
sub-block / constant-DB search path: ``from_scl_file`` registers the directory
containing the entry block automatically, so ``ABS``, ``SIGN`` and the constant
``DataSafetyKinematics`` DB all resolve without an explicit ``search_paths``
argument.
"""

from pathlib import Path

from plc_code.executor import create_harness

FIX = Path(__file__).parent.parent / "fixtures" / "ladder"


def test_abs_via_harness() -> None:
    h = create_harness(FIX / "ABS.s7dcl")
    h.set_inputs(x=-5)
    h.execute()
    assert h.get_output("y") == 5


def test_sin_calls_subblocks_and_db() -> None:
    # The fixture directory is auto-registered as a block search path, so the
    # sub-blocks ABS/SIGN AND the constant DataSafetyKinematics DB (LUT array
    # initialisers included) all resolve automatically — no manual registration.
    h = create_harness(FIX / "SinCalculation.s7dcl")
    h.set_inputs(angle=3000, length=13106)
    h.execute()
    assert h.get_output("result") == 6553
    assert not h.get_output("fault")
