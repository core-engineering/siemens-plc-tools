"""Regression tests for transpiler limitations found while porting Ruckig to SCL.

Each test reproduces a real-world SCL construct that previously transpiled to
broken Python and forced a workaround in downstream projects. They are the
RED tests for the limitation fixes; see the matching root-cause notes in the
parser / executor modules.

Limitations covered:
    L1 — quoted-name block call used in an expression (IF condition / RHS)
    L2 — global DB reference ``"DbName".MEMBER`` with parser-inserted spaces
    L3 — REGION name containing a hyphen
    L5 — assignment whose right-hand side continues over several source lines
    L6 — REGION name containing a digit
"""

from pathlib import Path

import pytest

from plc_code.executor.harness import FBTestHarness
from plc_code.executor.runtime import PLCRuntime
from plc_code.parser.lexer import tokenize_with_newlines
from plc_code.parser.parser import SCLParser

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _harness(scl: str, runtime: PLCRuntime | None = None) -> FBTestHarness:
    """Compile inline SCL source into a test harness."""
    block = SCLParser(tokenize_with_newlines(scl)).parse()
    return FBTestHarness.from_block(block, runtime)


# --------------------------------------------------------------------------- #
# L3 — REGION name with a hyphen
# --------------------------------------------------------------------------- #
def test_region_name_with_hyphen_does_not_leak_into_code() -> None:
    """``REGION Per-axis validation`` must not leak ``- axis validation`` as code."""
    scl = """
FUNCTION "T3" : Void
    VAR_OUTPUT
        y : LReal;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Per-axis validation
            #y := 42.0;
        END_REGION
    END_NETWORK
END_FUNCTION
"""
    block = SCLParser(tokenize_with_newlines(scl)).parse()
    region = block.networks[0].regions[0]
    # The full hyphenated name is captured, nothing leaks into region content.
    assert "axis" in region.name
    assert "validation" in region.name
    assert "axis" not in region.content

    harness = FBTestHarness.from_block(block)
    harness.execute()
    assert harness.get_output("y") == pytest.approx(42.0)


# --------------------------------------------------------------------------- #
# L6 — REGION name with a digit
# --------------------------------------------------------------------------- #
def test_region_name_with_digit_does_not_leak_into_code() -> None:
    """``REGION Set 7 phase durations`` must not leak ``7 phase durations`` as code."""
    scl = """
FUNCTION "T6" : Void
    VAR_OUTPUT
        y : LReal;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Set 7 phase durations
            #y := 7.0;
        END_REGION
    END_NETWORK
END_FUNCTION
"""
    block = SCLParser(tokenize_with_newlines(scl)).parse()
    region = block.networks[0].regions[0]
    assert "7" in region.name
    assert "phase" in region.name
    assert "phase" not in region.content

    harness = FBTestHarness.from_block(block)
    harness.execute()
    assert harness.get_output("y") == pytest.approx(7.0)


# --------------------------------------------------------------------------- #
# L5 — multi-line right-hand side inside a REGION
# --------------------------------------------------------------------------- #
def test_multiline_expression_in_region() -> None:
    """An RHS continued across lines (operator-led continuation) must stay one statement."""
    scl = """
FUNCTION "T5" : Void
    VAR_INPUT
        a : LReal;
        b : LReal;
        c : LReal;
    END_VAR
    VAR_OUTPUT
        s : LReal;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Integrate
            #s := #a
                + #b * 2.0
                + #c * 3.0;
        END_REGION
    END_NETWORK
END_FUNCTION
"""
    harness = _harness(scl)
    harness.set_inputs(a=1.0, b=2.0, c=3.0)
    harness.execute()
    # 1 + 2*2 + 3*3 = 1 + 4 + 9 = 14
    assert harness.get_output("s") == pytest.approx(14.0)


# --------------------------------------------------------------------------- #
# L2 — global DB reference with parser-inserted spaces around the dot
# --------------------------------------------------------------------------- #
def test_external_db_reference_resolves() -> None:
    """``"dbConst".RESULT_WORKING`` must read the registered global DB member."""
    scl = """
FUNCTION "T2" : Word
    { S7_Language := "SCL" }
    NETWORK
        #T2 := "dbConst".RESULT_WORKING;
    END_NETWORK
END_FUNCTION
"""

    class _Db:
        RESULT_WORKING = 0x7000

    runtime = PLCRuntime()
    runtime.register_db("dbConst", _Db())
    harness = _harness(scl, runtime)
    harness.execute()
    assert harness.get_output("T2") == 0x7000


# --------------------------------------------------------------------------- #
# L7 — hex literal used in an in-code expression (not just a var default)
# --------------------------------------------------------------------------- #
def test_hex_literal_in_assignment() -> None:
    """``#status := 16#8201;`` must keep the hex value, not be eaten by ``#``-vars."""
    scl = """
FUNCTION "T7" : Word
    { S7_Language := "SCL" }
    NETWORK
        #T7 := 16#8201;
    END_NETWORK
END_FUNCTION
"""
    harness = _harness(scl)
    harness.execute()
    assert harness.get_output("T7") == 0x8201


# --------------------------------------------------------------------------- #
# L1 — quoted-name block call inside an expression (IF condition)
# --------------------------------------------------------------------------- #
def test_named_block_call_in_condition() -> None:
    """``IF NOT "IsFiniteLreal"(x := #v) THEN`` must call the sub-block and use its return."""
    scl = """
FUNCTION "UsesIsFinite" : Word
    VAR_INPUT
        v : LReal;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        #UsesIsFinite := 16#0000;
        IF NOT "IsFiniteLreal"(x := #v) THEN
            #UsesIsFinite := 16#8201;
        END_IF;
    END_NETWORK
END_FUNCTION
"""
    runtime = PLCRuntime(block_search_paths=[FIXTURES_DIR])

    # Finite input -> condition false -> stays 0x0000
    h1 = _harness(scl, runtime)
    h1.set_inputs(v=5.0)
    h1.execute()
    assert h1.get_output("UsesIsFinite") == 0x0000

    # Infinite input -> IsFiniteLreal returns false -> NOT false -> error code
    h2 = _harness(scl, runtime)
    h2.set_inputs(v=1.0e309)  # +inf in IEEE-754 double
    h2.execute()
    assert h2.get_output("UsesIsFinite") == 0x8201


# --------------------------------------------------------------------------- #
# Two ``:=`` statements on one source line — both must be assigned
# --------------------------------------------------------------------------- #
def test_two_assignments_on_one_source_line_both_assign() -> None:
    """``#a := 1; #b := 2;`` on a single line must assign BOTH outputs.

    The parser emits one statement per ``;`` (each on its own line), so neither
    assignment is silently dropped end to end.
    """
    scl = """{ S7_EditorMode := "SCL" }
FUNCTION_BLOCK "TwoAssign"
    VAR_OUTPUT
        a : Int;
        b : Int;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        #a := 1; #b := 2;
    END_NETWORK
END_FUNCTION_BLOCK"""
    harness = _harness(scl)
    harness.execute()
    assert harness.get_output("a") == 1
    assert harness.get_output("b") == 2
