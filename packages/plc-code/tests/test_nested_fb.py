"""A parent FB nesting a stateful child FB: the child's VAR state must persist
across the parent's execute() cycles (same member instance, not fresh)."""

from pathlib import Path

from plc_code.executor import create_harness
from plc_code.executor.runtime import PLCRuntime

FIX = Path(__file__).parent / "fixtures" / "nested_fb"


def _h():
    runtime = PLCRuntime(block_search_paths=[FIX])
    return create_harness(FIX / "Parent.s7dcl", runtime=runtime)


def test_nested_child_state_persists_across_cycles():
    h = _h()
    for _ in range(5):  # add 2.0 five times
        h.set_inputs(step=2.0)
        h.execute()
    assert h.get_output("sum") == 10.0  # accumulation proves same instance persists


def test_nested_child_output_binds_each_cycle():
    h = _h()
    h.set_inputs(step=3.0)
    h.execute()
    assert h.get_output("sum") == 3.0
    h.set_inputs(step=4.0)
    h.execute()
    assert h.get_output("sum") == 7.0


def _h_udt():
    runtime = PLCRuntime(block_search_paths=[FIX])
    return create_harness(FIX / "ParentUdt.s7dcl", runtime=runtime)


def test_nested_udt_input_copy_in_change_detection():
    """A UDT VAR_INPUT must be copied by value into the child (S7 copy-in), so a
    child that snapshots it into a retained ``prevCfg`` sees real changes when
    the parent mutates its single ``childCfg`` member in place each cycle.

    Regression: previously the child's ``cfg`` aliased the parent's ``childCfg``
    (and ``prevCfg := cfg`` aliased it further), so ``cfg.target`` always equaled
    ``prevCfg.target`` and no change was ever detected.
    """
    h = _h_udt()
    for tgt in (1.0, 1.0, 2.0, 2.0, 5.0):  # 2 transitions after 1st cycle: 1->2, 2->5
        h.set_inputs(target=tgt)
        h.execute()
    assert h.get_output("changes") == 2
