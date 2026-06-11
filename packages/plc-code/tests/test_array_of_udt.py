"""Array[..] of _.UDT must compile (no NameError from list[UndefinedName])."""

from pathlib import Path

from plc_code.executor import create_harness
from plc_code.executor.runtime import PLCRuntime

FIX = Path(__file__).parent / "fixtures" / "array_udt"


def test_array_of_udt_compiles_and_indexes():
    runtime = PLCRuntime(block_search_paths=[FIX])
    harness = create_harness(FIX / "ArrayUser.s7dcl", runtime=runtime)
    harness.execute()
    out = harness.get_output("buf")
    assert out[1].v == 3.5


def test_array_of_udt_elements_are_independent():
    """Distinct indices must not alias a shared _AutoStruct instance.

    The fixture writes different values to ``buf[1]`` and ``buf[2]``; if the
    array default used ``[_AutoStruct()] * N`` (shared reference) both would end
    up at the last-written value. The ``[_AutoStruct() for _ in range(N)]`` fix
    keeps them independent.
    """
    runtime = PLCRuntime(block_search_paths=[FIX])
    harness = create_harness(FIX / "ArrayUser.s7dcl", runtime=runtime)
    harness.execute()
    out = harness.get_output("buf")
    assert out[1].v == 3.5
    assert out[2].v == 9.0
