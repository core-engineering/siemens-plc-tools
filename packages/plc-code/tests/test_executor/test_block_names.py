"""A block whose TIA name is not a Python identifier still compiles and runs.

An OB is routinely named ``"Main Loop"`` or ``"Cyclic interrupt"``; the generated
``class Main Loop:`` did not parse, which put 35 of 349 production code blocks
out of reach of the harness and of ``plc code transpile --check``.
"""

from __future__ import annotations

from plc_code.executor import PLCRuntime, compile_block
from plc_code.executor.models import python_class_name
from plc_code.parser.lexer import tokenize_with_newlines
from plc_code.parser.parser import SCLParser


def test_the_python_class_name_is_an_identifier() -> None:
    assert python_class_name("Main Loop") == "Main_Loop"
    assert python_class_name("Cyclic interrupt [OB30]") == "Cyclic_interrupt_OB30"
    assert python_class_name("1stScan") == "_1stScan"
    assert python_class_name("Plain_Name") == "Plain_Name"


def test_a_block_named_with_spaces_compiles_and_runs() -> None:
    source = """FUNCTION_BLOCK "Main Loop"
    VAR_INPUT
        a : Int;
    END_VAR
    VAR_OUTPUT
        b : Int;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Logic
            #b := #a + 1;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
    result = compile_block(SCLParser(tokenize_with_newlines(source)).parse())
    assert result.success, result.transpile_result.errors
    assert result.transpile_result.class_name == "Main_Loop"
    assert result.fb_class is not None
    instance = result.fb_class(_runtime=PLCRuntime())
    instance.a = 4
    instance.execute()
    assert instance.b == 5
