"""Regression tests for the CASE default branch (``ELSE:``).

Background
----------
:meth:`ControlFlowTranslator._translate_case_block` recognises ``ELSE`` as a case
label, but then pushed it through the same path as a value label: the label text
was translated as an expression and emitted as a comparison, producing
``elif self.state == ELSE:``.  The generated module compiled — ``ELSE`` is a
valid Python identifier — and blew up only at execution time with
``NameError: name 'ELSE' is not defined``.

Observed in the field: every ``SafetyAlarm`` unit test of the project-A program
(42 failures), and any block whose state machine carries a default branch.

These tests pin:
    * ``ELSE:`` emits a Python ``else:``, never a comparison against a name,
    * the default body actually runs when no label matches (harness execution),
    * a matching label still wins over the default,
    * degenerate shapes — ``ELSE`` as the only label, and an empty default body —
      produce runnable Python.
"""

from plc_code.executor.control_flow import translate_control_flow
from plc_code.executor.harness import FBTestHarness
from plc_code.parser.lexer import tokenize_with_newlines
from plc_code.parser.parser import SCLParser


def _harness(scl: str) -> FBTestHarness:
    """Compile inline SCL source into a test harness."""
    block = SCLParser(tokenize_with_newlines(scl)).parse()
    return FBTestHarness.from_block(block)


# A three-state machine with a default branch — the shape that failed.
_FB_CASE_ELSE = """
FUNCTION_BLOCK "CaseWithElse"
    VAR_INPUT
        state : Int;
    END_VAR
    VAR_OUTPUT
        out : Int;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Logic
            CASE #state OF
                0:
                    #out := 10;
                1:
                    #out := 20;
                ELSE:
                    #out := 99;
            END_CASE;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""

# Degenerate: the default is the only branch.
_FB_CASE_ELSE_ONLY = """
FUNCTION_BLOCK "CaseElseOnly"
    VAR_INPUT
        state : Int;
    END_VAR
    VAR_OUTPUT
        out : Int;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Logic
            CASE #state OF
                ELSE:
                    #out := 42;
            END_CASE;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""

# Degenerate: an explicitly empty default body, the idiom used to say
# "every other state is deliberately ignored".
_FB_CASE_ELSE_EMPTY = """
FUNCTION_BLOCK "CaseElseEmpty"
    VAR_INPUT
        state : Int;
    END_VAR
    VAR_OUTPUT
        out : Int;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Logic
            CASE #state OF
                0:
                    #out := 10;
                ELSE:
                    ;
            END_CASE;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


# Symbolic constant labels — the shape every state machine in the field uses.
# Region-content reconstruction emits these as ``# NO_ALARM :``, with a space after
# the ``#`` and before the colon, which the label pattern used to reject.
_FB_CASE_SYMBOLIC = """
FUNCTION_BLOCK "CaseSymbolicLabels"
    VAR_INPUT
        state : Int;
    END_VAR
    VAR_OUTPUT
        out : Int;
    END_VAR
    VAR CONSTANT
        IDLE : Int := 0;
        BUSY : Int := 1;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Logic
            CASE #state OF
                #IDLE:
                    #out := 10;
                #BUSY:
                    #out := 20;
                ELSE:
                    #out := 99;
            END_CASE;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""

# Symbolic labels whose branch bodies carry nested REGIONs, as the project's
# state machines are written.
_FB_CASE_SYMBOLIC_REGIONS = """
FUNCTION_BLOCK "CaseSymbolicRegions"
    VAR_INPUT
        state : Int;
    END_VAR
    VAR_OUTPUT
        out : Int;
    END_VAR
    VAR CONSTANT
        IDLE : Int := 0;
        BUSY : Int := 1;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Logic
            CASE #state OF
                #IDLE:
                    REGION Idle state
                        #out := 10;
                    END_REGION

                #BUSY:
                    REGION Busy state
                        #out := 20;
                    END_REGION
                ELSE:
                    #out := 99;
            END_CASE;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


class TestCaseElseTranslation:
    """Unit level: what the translator emits for a default branch."""

    def test_else_emits_python_else(self) -> None:
        """``ELSE:`` becomes ``else:``, not a comparison."""
        scl = """
        CASE #state OF
            0:
                #out := 10;
            ELSE:
                #out := 99;
        END_CASE;
        """
        result = translate_control_flow(scl)

        assert any(line.strip() == "else:" for line in result)

    def test_else_is_never_emitted_as_a_name(self) -> None:
        """No generated line may reference a bare ``ELSE`` identifier."""
        scl = """
        CASE #state OF
            0:
                #out := 10;
            ELSE:
                #out := 99;
        END_CASE;
        """
        result = translate_control_flow(scl)

        assert not any("ELSE" in line for line in result)

    def test_value_branches_are_unchanged(self) -> None:
        """Adding a default must not disturb the value branches."""
        scl = """
        CASE #state OF
            0:
                #out := 10;
            1:
                #out := 20;
            ELSE:
                #out := 99;
        END_CASE;
        """
        result = translate_control_flow(scl)

        assert any("if self.state == 0:" in line for line in result)
        assert any("elif self.state == 1:" in line for line in result)


class TestCaseElseHarness:
    """End-to-end: the default branch effect must actually occur."""

    def test_default_branch_runs_for_unmatched_value(self) -> None:
        """No label matches -> the default body runs.

        Before the fix this raised ``NameError: name 'ELSE' is not defined``.
        """
        h = _harness(_FB_CASE_ELSE)
        h.set_inputs(state=7)
        h.execute()
        assert h.get_output("out") == 99

    def test_matching_label_wins_over_default(self) -> None:
        """A matching value branch runs and the default does not."""
        h = _harness(_FB_CASE_ELSE)
        h.set_inputs(state=1)
        h.execute()
        assert h.get_output("out") == 20

    def test_first_label_still_matches(self) -> None:
        """The first branch keeps its ``if`` keyword with a default present."""
        h = _harness(_FB_CASE_ELSE)
        h.set_inputs(state=0)
        h.execute()
        assert h.get_output("out") == 10

    def test_else_only_case_runs(self) -> None:
        """A CASE whose only label is the default must still be valid Python."""
        h = _harness(_FB_CASE_ELSE_ONLY)
        h.set_inputs(state=3)
        h.execute()
        assert h.get_output("out") == 42

    def test_empty_default_body_is_a_no_op(self) -> None:
        """An empty default body runs without raising and changes nothing."""
        h = _harness(_FB_CASE_ELSE_EMPTY)
        h.set_inputs(state=5)
        h.execute()
        assert h.get_output("out") == 0

    def test_empty_default_body_does_not_swallow_value_branch(self) -> None:
        """The value branch still fires when the default body is empty."""
        h = _harness(_FB_CASE_ELSE_EMPTY)
        h.set_inputs(state=0)
        h.execute()
        assert h.get_output("out") == 10


class TestCaseSymbolicLabels:
    """Labels written as constants, through the real parser reconstruction.

    Region-content reconstruction separates the ``#`` from the identifier and the
    identifier from the colon (``# IDLE :``).  The label pattern used to require
    them glued, so every symbolic branch was silently dropped and only the default
    survived — a state machine that never left its default branch.
    """

    def test_first_symbolic_branch_runs(self) -> None:
        """``#IDLE:`` must be recognised as a label, not swallowed as a body line."""
        h = _harness(_FB_CASE_SYMBOLIC)
        h.set_inputs(state=0)
        h.execute()
        assert h.get_output("out") == 10

    def test_second_symbolic_branch_runs(self) -> None:
        """The second symbolic branch is reached for its own value."""
        h = _harness(_FB_CASE_SYMBOLIC)
        h.set_inputs(state=1)
        h.execute()
        assert h.get_output("out") == 20

    def test_default_still_reached_with_symbolic_labels(self) -> None:
        """An unmatched value still falls through to the default."""
        h = _harness(_FB_CASE_SYMBOLIC)
        h.set_inputs(state=5)
        h.execute()
        assert h.get_output("out") == 99

    def test_symbolic_branch_with_nested_region_runs(self) -> None:
        """A branch body wrapped in a REGION must still execute."""
        h = _harness(_FB_CASE_SYMBOLIC_REGIONS)
        h.set_inputs(state=0)
        h.execute()
        assert h.get_output("out") == 10

    def test_second_symbolic_branch_with_nested_region_runs(self) -> None:
        """The REGION of one branch must not swallow the next branch."""
        h = _harness(_FB_CASE_SYMBOLIC_REGIONS)
        h.set_inputs(state=1)
        h.execute()
        assert h.get_output("out") == 20

    def test_default_reached_with_nested_regions(self) -> None:
        """Nested REGIONs must not break the default branch either."""
        h = _harness(_FB_CASE_SYMBOLIC_REGIONS)
        h.set_inputs(state=9)
        h.execute()
        assert h.get_output("out") == 99
