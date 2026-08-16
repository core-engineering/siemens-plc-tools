"""Generated FUNCTION_BLOCK classes must be callable: instance(**inputs) sets
inputs, runs execute(), leaving outputs as attributes (timer-style protocol)."""

from pathlib import Path

from plc_code.executor import create_harness
from plc_code.executor.runtime import PLCRuntime

FIX = Path(__file__).parent / "fixtures" / "callable_fb"


def test_compiled_fb_is_callable():
    runtime = PLCRuntime(block_search_paths=[FIX])
    harness = create_harness(FIX / "Doubler.s7dcl", runtime=runtime)
    inst = harness.instance  # the compiled FB instance
    inst(x=21.0)  # __call__: set x, then execute()
    assert inst.y == 42.0
