"""PLC tags read and written by name, and variables whose names are not identifiers.

``"DI_START"`` used to render as the Python string literal ``"DI_START"`` --
always true in a condition, silently -- and ``"DO_PUMP" := x`` did not parse.
A variable named ``1X02-01`` (a terminal strip's naming, 157 references in the
corpus) was refused by the expression parser and emitted as an invalid field.
"""

from __future__ import annotations

from pathlib import Path

from plc_code.executor.harness import create_harness
from plc_code.executor.runtime import UnsetTag

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_an_unset_tag_is_false_and_zero_but_only_equal_to_itself() -> None:
    harness = create_harness(FIXTURES / "TagsAndOddNames.s7dcl")
    harness.set_inputs(**{"1X02-01": True, "gain": 2.0})
    harness.execute()
    assert harness.get_output("started") is False  # "DI_START" never set
    assert harness.get_output("Out Value") == 0.0  # "AI_LEVEL" reads as 0
    assert harness.runtime.tags["DO_PUMP"] is False
    assert UnsetTag("A") == UnsetTag("A") and UnsetTag("A") != UnsetTag("B") and UnsetTag("A") != 0


def test_tags_set_on_the_runtime_drive_the_block_and_are_written_back() -> None:
    harness = create_harness(FIXTURES / "TagsAndOddNames.s7dcl")
    harness.runtime.tags["DI_START"] = True
    harness.runtime.tags["AI_LEVEL"] = 21.0
    harness.set_inputs(**{"1X02-01": True, "gain": 2.0})
    harness.execute()
    assert harness.get_output("started") is True
    assert harness.get_output("Out Value") == 42.0
    assert harness.runtime.tags["DO_PUMP"] is True
    assert harness.instance._1X02_01 is True  # the attribute the odd name compiles to
