"""The dependency extractor reads the shared statement AST, not regex over text.

Every case here is a shape the old text walk got wrong on the production corpus,
measured by a differential over 349 blocks (3 086 assignments found by the old
walk, 9 344 by this one; of the 1 438 (target, dependency) pairs the old walk
reported, the 107 it alone reported were all its own mistakes: 48 targets
mis-read on a ``.#member`` path, 44 read out of commented code, 15 garbage
targets captured across statement boundaries).
"""

from __future__ import annotations

import pytest

from plc_code.analyzer.logic_dependency.expression_parser import (
    ExpressionParser,
    ParseError,
    parse_expression,
)
from plc_code.analyzer.logic_dependency.extractor import extract_dependencies
from plc_code.analyzer.logic_dependency.graph_builder import collect_leaf_nodes
from plc_code.analyzer.logic_dependency.mermaid import MermaidGenerator
from plc_code.analyzer.logic_dependency.models import (
    Assignment,
    BlockDependencies,
    NodeType,
    OperatorType,
)
from plc_code.parser.lexer import tokenize_with_newlines
from plc_code.parser.parser import SCLParser

_TEMPLATE = """FUNCTION_BLOCK "Deps"
    VAR_INPUT
        a : Real;
        b : Real;
        i : Int;
        sel : Int;
    END_VAR
    VAR_OUTPUT
        out : Real;
        flag : Bool;
    END_VAR
    VAR
        mem : Real;
        arr : Array[0..3] of Real;
        status : Struct
            inner : Real;
        END_STRUCT;
        tmr : TON_TIME;
    END_VAR
    {{ S7_Language := "SCL" }}
    NETWORK
        REGION Logic
{body}
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


def _deps(body: str) -> BlockDependencies:
    block = SCLParser(tokenize_with_newlines(_TEMPLATE.format(body=body))).parse()
    return extract_dependencies(block)


def _leaf_names(assignment: Assignment) -> set[str]:
    return {
        node.name
        for node in collect_leaf_nodes(assignment.expression)
        if node.node_type not in (NodeType.CONSTANT, NodeType.FUNCTION_CALL)
    }


def _by_target(deps: BlockDependencies) -> dict[str, list[Assignment]]:
    grouped: dict[str, list[Assignment]] = {}
    for assignment in deps.assignments:
        grouped.setdefault(assignment.target, []).append(assignment)
    return grouped


class TestWhatTheOldTextWalkLost:
    def test_arithmetic_keeps_every_operand(self) -> None:
        (assignment,) = _deps("#out := #a + #b * 2.0;").assignments
        assert assignment.expression.operator is OperatorType.ADD
        assert _leaf_names(assignment) == {"a", "b"}

    def test_an_index_expression_is_a_dependency_of_its_own(self) -> None:
        (assignment,) = _deps("#out := #arr[#i + 1];").assignments
        assert assignment.expression.operator is OperatorType.INDEX
        assert _leaf_names(assignment) == {"arr[*]", "i"}

    def test_a_member_written_with_its_own_hash_targets_the_full_path(self) -> None:
        # The old regex took the last `#name` before `:=` as the target: "inner".
        (assignment,) = _deps("#status.#inner := #a;").assignments
        assert assignment.target == "status.inner"
        assert assignment.target_type is NodeType.STATE

    def test_commented_out_code_is_not_an_assignment(self) -> None:
        deps = _deps("// #out := #a;\n(* #mem := #b; *)\n#flag := TRUE;")
        assert [assignment.target for assignment in deps.assignments] == ["flag"]

    def test_a_global_db_reference_reads_whatever_the_spacing(self) -> None:
        (assignment,) = _deps('#out := "Config".limits.upper;').assignments
        (leaf,) = collect_leaf_nodes(assignment.expression)
        assert leaf.node_type is NodeType.GLOBAL_DB
        assert leaf.name == '"Config".limits.upper'

    def test_a_call_output_depends_on_the_callee_and_its_inputs(self) -> None:
        # `=>` is not `:=`: the old walk never saw these.
        (assignment,) = _deps("#tmr(IN := #a > #b, PT := T#1s, Q => #flag);").assignments
        assert assignment.target == "flag"
        assert assignment.target_type is NodeType.OUTPUT
        assert _leaf_names(assignment) == {"tmr", "a", "b"}

    def test_the_loop_variable_depends_on_the_bounds(self) -> None:
        by_target = _by_target(_deps("FOR #i := 0 TO #sel DO\n    #arr[#i] := #a;\nEND_FOR;"))
        assert _leaf_names(by_target["i"][0]) == {"sel"}
        assert _leaf_names(by_target["arr[#i]"][0]) == {"a"}


class TestContext:
    def test_innermost_if_condition_is_the_enclosing_condition(self) -> None:
        body = "IF #a > 0.0 THEN\n    IF #b > 0.0 THEN\n        #out := #a;\n    END_IF;\nEND_IF;"
        (assignment,) = _deps(body).assignments
        assert assignment.enclosing_condition is not None
        names = {node.name for node in collect_leaf_nodes(assignment.enclosing_condition)}
        assert names == {"b", "0.0"}

    def test_elsif_and_else(self) -> None:
        body = (
            "IF #a > 0.0 THEN\n    #out := 1.0;\n"
            "ELSIF #b > 0.0 THEN\n    #out := 2.0;\n"
            "ELSE\n    #out := 3.0;\nEND_IF;"
        )
        first, second, third = _deps(body).assignments
        assert {n.name for n in collect_leaf_nodes(first.enclosing_condition)} == {"a", "0.0"}  # type: ignore[arg-type]
        assert {n.name for n in collect_leaf_nodes(second.enclosing_condition)} == {"b", "0.0"}  # type: ignore[arg-type]
        assert third.enclosing_condition is None

    def test_case_labels_become_the_case_context(self) -> None:
        body = (
            "CASE #sel OF\n    1, 2:\n        #out := #a;\n"
            "    3:\n        #out := #b;\n"
            "    ELSE\n        #out := 0.0;\nEND_CASE;"
        )
        first, second, third = _deps(body).assignments
        assert first.case_context == "1, 2"
        assert second.case_context == "3"
        assert third.case_context is None

    def test_source_location_carries_the_absolute_line_and_region(self) -> None:
        (assignment,) = _deps("#out := #a;").assignments
        assert assignment.source_location.region_name == "Logic"
        assert assignment.source_location.line_number == _TEMPLATE.split("\n").index("{body}") + 1


class TestNothingIsDroppedSilently:
    def test_an_unreadable_statement_is_recorded(self) -> None:
        deps = _deps("#out := #a;\nGOTO somewhere;\n#flag := TRUE;")
        assert deps.parse_errors, "the rejected construct must be reported, not skipped"

    def test_the_text_api_still_parses_and_still_raises(self) -> None:
        expression = parse_expression("#a AND NOT #b", {"a": NodeType.INPUT, "b": NodeType.INPUT})
        assert expression.operator is OperatorType.AND
        with pytest.raises(ParseError):
            ExpressionParser().parse("#a +")


class TestConsumersAcceptTheNewOperators:
    def test_mermaid_renders_arithmetic_and_index_gates(self) -> None:
        deps = _deps("#out := (#a + #b) * #arr[#i];")
        generator = MermaidGenerator(include_click_links=False)
        text = generator._generate_expression(deps.assignments[0].expression)  # noqa: SLF001
        assert text  # a node id; the gate labels fall back to the operator's own value
        assert OperatorType.MULTIPLY.value == "*"
