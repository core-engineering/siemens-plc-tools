"""PLC tags read and written by name, and variables whose names are not identifiers.

``"DI_START"`` used to render as the Python string literal ``"DI_START"`` --
always true in a condition, silently -- and ``"DO_PUMP" := x`` did not parse.
A variable named ``1X02-01`` (a terminal strip's naming, 157 references in the
corpus) was refused by the expression parser and emitted as an invalid field.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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


def test_get_outputs_is_keyed_by_the_scl_name() -> None:
    harness = create_harness(FIXTURES / "TagsAndOddNames.s7dcl")
    harness.execute()
    assert set(harness.get_outputs()) == {"Out Value", "started"}


def test_a_quoted_parameter_and_an_odd_block_name_bind_through_call_named_block() -> None:
    from plc_code.executor.runtime import PLCRuntime

    runtime = PLCRuntime(block_search_paths=[FIXTURES])
    result = runtime.call_named_block("FC-Odd", {"Set Point": 41}, {})
    assert result["FC-Odd"] == 42  # the FUNCTION's return value, under its SCL name


def test_two_names_compiling_to_one_attribute_are_refused() -> None:
    from plc_code.executor import transpile_block
    from plc_code.parser.lexer import tokenize_with_newlines
    from plc_code.parser.parser import SCLParser

    source = (
        'FUNCTION_BLOCK "Clash"\n    VAR_INPUT\n        "a-b" : Int;\n        a_b : Int;\n    END_VAR\n'
        '    { S7_Language := "SCL" }\n    NETWORK\n        REGION L\n            #a_b := #"a-b";\n'
        "        END_REGION\n    END_NETWORK\nEND_FUNCTION_BLOCK\n"
    )
    result = transpile_block(SCLParser(tokenize_with_newlines(source)).parse())
    assert not result.success
    assert "both compile to the attribute 'a_b'" in result.errors[0]


def test_tags_are_cleared_by_reset_and_an_unset_tag_behaves_as_zero() -> None:
    from plc_code.executor.runtime import PLCRuntime

    runtime = PLCRuntime()
    runtime.tags["X"] = 5
    runtime.reset()
    unset = runtime.tags["X"]
    assert isinstance(unset, UnsetTag)
    assert unset + 1 == 1 and unset * 3 == 0 and unset % 3 == 0 and abs(unset) == 0 and (unset & 0xFF) == 0
    assert unset < 1 and unset <= 0 and not unset > 0 and unset != 0
    assert runtime.tags.get("X") is unset and "X" in runtime.tags  # remembered after first read
    with pytest.raises(ZeroDivisionError):
        _ = 5 / unset


def test_a_tag_name_that_is_a_loaded_db_cannot_be_shadowed() -> None:
    from plc_code.executor.runtime import PLCRuntime

    runtime = PLCRuntime()
    runtime.register_db("MyDb", {"x": 1})
    assert runtime.tags["MyDb"] == {"x": 1}
    with pytest.raises(KeyError):
        runtime.tags["MyDb"] = 3


def test_a_quoted_parameter_in_an_fb_instance_call_and_an_odd_callee_name() -> None:
    from plc_code.executor.generator import generate_statements
    from plc_code.parser.lexer import TokenType, tokenize
    from plc_code.parser.statement_parser import parse_statements

    tokens = [
        t
        for t in tokenize('#inst("Set Point" := #x, o => #y); "FC-Odd"("Set Point" := #x);')
        if t.type is not TokenType.EOF
    ]
    lines = generate_statements(parse_statements(tokens).statements)
    assert lines[0] == "self.inst(Set_Point=self.x)"
    assert lines[1] == "self.y = self.inst.o"
    assert lines[2].startswith("_sub_FC_Odd_result = ")


def test_generated_python_that_does_not_parse_is_a_located_problem() -> None:
    from plc_code.executor import transpiler as t
    from plc_code.executor.models import TranspileResult
    from plc_code.parser.lexer import tokenize_with_newlines
    from plc_code.parser.parser import SCLParser

    source = 'FUNCTION_BLOCK "Probe"\n    { S7_Language := "SCL" }\n    NETWORK\n    END_NETWORK\n'
    block = SCLParser(tokenize_with_newlines(source + "END_FUNCTION_BLOCK\n")).parse()
    bad = TranspileResult(success=True, python_code="class Probe:\n    a b c\n", class_name="Probe")
    original = t.transpile_block
    try:
        t.transpile_block = lambda *a, **k: bad  # type: ignore[assignment]
        result = t.compile_block(block)
    finally:
        t.transpile_block = original
    assert not result.success
    assert "generated Python does not parse" in result.transpile_result.errors[0]
    assert "a b c" in result.transpile_result.errors[0]
