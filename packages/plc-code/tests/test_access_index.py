"""The access index: every read and write of a path, from the SCL and ladder ASTs.

The cross-block tracers used to run their own regexes over the block's re-spaced
text; they now filter this index. Each case here is a shape the text walk got
wrong or could not see.
"""

from __future__ import annotations

from pathlib import Path

from plc_code.analyzer.logic_dependency.access_index import READ, build_access_index
from plc_code.analyzer.logic_dependency.field_tracer import (
    find_field_readers,
    find_field_writers,
    find_inout_struct_binding,
    find_local_subfield_writer,
)
from plc_code.analyzer.logic_dependency.forward_tracer import find_field_usages
from plc_code.analyzer.logic_dependency.index_resolver import TagIndexInfo
from plc_code.analyzer.logic_dependency.state_detector import detect_state_variables_in_block
from plc_code.analyzer.logic_dependency.tag_assignment import find_assignments_in_block
from plc_code.parser import parse_scl_file
from plc_code.parser.expression_parser import parse_expression
from plc_code.parser.lexer import TokenType, tokenize, tokenize_with_newlines
from plc_code.parser.parser import SCLParser
from plc_code.parser.scl_text import expression_text

FIXTURES = Path(__file__).parent / "fixtures"

_TEMPLATE = """FUNCTION_BLOCK "Idx"
    VAR_INPUT
        a : Real;
        i : Int;
    END_VAR
    VAR_IN_OUT
        io : Struct
            sub : Real;
        END_STRUCT;
    END_VAR
    VAR
        tmr : TON_TIME;
        drive : _.MotorDrive;
        arr : Array[0..3] of Real;
    END_VAR
    {{ S7_Language := "SCL" }}
    NETWORK
        REGION Logic
{body}
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


def _block(body: str):
    return SCLParser(tokenize_with_newlines(_TEMPLATE.format(body=body))).parse()


def _index(body: str):
    return build_access_index(_block(body))


class TestTheSclPrinter:
    def test_round_trips_every_shape(self) -> None:
        for source in (
            '#a AND NOT #b.c[#i + 1] OR "DB".x.y >= 3',
            "(#a + #b) * -#c",
            "- 1 / #t",
            '"Scale"(input := #a, gain := 2.0)',
            "%I0.0",
            "T#5s",
            "#st.#sub",
        ):
            tree = parse_expression([t for t in tokenize(source) if t.type is not TokenType.EOF]).expression
            assert tree is not None, source
            text = expression_text(tree)
            again = parse_expression([t for t in tokenize(text) if t.type is not TokenType.EOF]).expression
            assert again is not None and expression_text(again) == text, source


class TestAssignments:
    def test_a_write_lists_what_it_reads(self) -> None:
        index = _index('"DB".x.y[#i] := #a + "DB".z;')
        (write,) = list(index.writes())
        assert (write.path, write.dependencies) == ('"DB".x.y[#i]', ["#a", '"DB".z'])
        assert {r.path for r in index.reads()} == {"#i", "#a", '"DB".z'}
        assert all(r.dependencies == ['"DB".x.y[#i]'] for r in index.reads())

    def test_a_member_with_its_own_hash_is_spelled_as_written(self) -> None:
        index = _index("#io.#sub := #a;")
        (write,) = list(index.writes())
        assert write.path == "#io.#sub"

    def test_commented_code_is_not_an_access(self) -> None:
        index = _index("// #arr[0] := #a;\n(* #arr[1] := #a; *)\n#arr[2] := #a;")
        assert [w.path for w in index.writes()] == ["#arr[2]"]


class TestCalls:
    def test_an_output_binding_is_a_write_with_the_calls_inputs_as_dependencies(self) -> None:
        index = _index('#tmr(IN := "TAG_1", PT := T#1s, Q => "DB".q);')
        q = next(w for w in index.writes() if w.path == '"DB".q')
        assert q.call is not None and (q.call.parameter, q.call.direction) == ("Q", "=>")
        assert q.call.instance == "tmr"
        assert q.dependencies == ["TAG_1"]
        assert q.call.inputs == {"IN": '"TAG_1"', "PT": "T#1s"} and q.call.outputs == {"Q": '"DB".q'}

    def test_an_input_binding_is_a_read_in_call_context(self) -> None:
        index = _index('"Scale"(input := "DB".raw, result => "DB".out);')
        raw = next(r for r in index.reads() if r.path == '"DB".raw')
        assert raw.call is not None and raw.call.parameter == "input" and raw.call.instance is None
        assert raw.dependencies == ['"DB".out']

    def test_calling_an_instance_writes_its_own_state(self) -> None:
        index = _index("#drive(speed := #a);")
        assert any(w.path == "#drive" for w in index.writes())


class TestReviewedShapes:
    def test_a_call_output_inside_an_expression_is_a_write_not_a_read(self) -> None:
        index = _index('#arr[0] := "Scale"(in := #a, out => "DB".y);')
        assert [w.path for w in index.writes()] == ["#arr[0]", '"DB".y']
        assert '"DB".y' not in {r.path for r in index.reads()}
        y = next(w for w in index.writes() if w.path == '"DB".y')
        assert y.call is not None and y.call.parameter == "out" and y.dependencies == ["#a"]

    def test_a_call_output_targets_index_is_read(self) -> None:
        index = _index('#tmr(IN := #a, PT := T#1s, Q => "DB".q[#i]);')
        assert ("#i", READ) in {(r.path, r.kind) for r in index.reads()}

    def test_the_for_variable_is_written_from_its_bounds(self) -> None:
        index = _index('FOR #i := 0 TO "DB".n DO #arr[#i] := 1.0; END_FOR;')
        i = next(w for w in index.writes() if w.path == "#i")
        assert i.dependencies == ['"DB".n'] and i.element == "bounds"

    def test_a_case_selectors_index_is_not_a_selector(self) -> None:
        body = 'CASE "DB".arms[#i].mode OF 1: #arr[0] := 1.0; END_CASE;'
        by_element = {(r.path, r.element) for r in _index(body).reads()}
        assert ('"DB".arms[#i].mode', "selector") in by_element
        assert ("#i", "selector_index") in by_element
        assert [v.name for v in detect_state_variables_in_block(_block(body))] == ['"DB".arms[#i].mode']

    def test_a_global_instance_db_call_writes_the_instance(self) -> None:
        index = _index('"TON_DB"(IN := #a, PT := T#1s);')
        assert any(w.path == '"TON_DB"' for w in index.writes())

    def test_the_cache_never_serves_a_dropped_blocks_index(self) -> None:
        import gc

        from plc_code.analyzer.logic_dependency.access_index import access_index

        for n in range(40):
            block = _block(f'"DB".v{n} := #a;')
            (write,) = list(access_index(block).writes())
            assert write.path == f'"DB".v{n}'
            del block
            gc.collect()


class TestControlFlow:
    def test_conditions_selectors_and_bounds_are_reads(self) -> None:
        body = (
            'IF "DB".flag THEN #arr[0] := 1.0; END_IF;\n'
            "CASE #i OF 1: #arr[1] := 2.0; END_CASE;\n"
            'FOR #i := 0 TO "DB".n DO #arr[#i] := 3.0; END_FOR;\n'
            'WHILE "DB".go DO #arr[2] := 4.0; END_WHILE;'
        )
        elements = {(r.path, r.element) for r in _index(body).reads()}
        assert {
            ('"DB".flag', "condition"),
            ("#i", "selector"),
            ('"DB".n', "bounds"),
            ('"DB".go', "condition"),
        } <= elements


class TestLadder:
    def test_a_coil_depends_on_its_rung_contacts_and_literals_are_not_paths(self) -> None:
        for ladder in (FIXTURES / "ladder").glob("*.s7dcl"):
            index = build_access_index(parse_scl_file(ladder))
            assert index.parse_errors == [], ladder.name
            for access in index.accesses:
                assert not access.path.lstrip("-").isdigit(), (ladder.name, access.path)
                assert all(not d.lstrip("-")[:1].isdigit() for d in access.dependencies), (
                    ladder.name,
                    access,
                )
            assert all(a.line >= 1 for a in index.accesses), "ladder accesses carry their network's ordinal"

    def test_ladder_is_indexed_from_the_networks_not_the_language_pragma(self) -> None:
        ladder = next(p for p in (FIXTURES / "ladder").glob("*.s7dcl"))
        block = parse_scl_file(ladder)
        block.attributes.preferred_language = "FBD"
        assert not block.is_ladder
        assert build_access_index(block).accesses


class TestTheTracersOnTopOfIt:
    def test_writers_and_readers_of_a_global_field(self) -> None:
        block = _block('"DB".x := #a;\n#arr[0] := "DB".x * 2.0;')
        (writer,) = find_field_writers([block], '"DB".x')
        assert (writer.block_name, writer.dependencies, writer.expression) == ("Idx", ["#a"], "#a")
        (reader,) = find_field_readers([block], '"DB".x')
        assert reader.dependencies == ["#arr[0]"]

    def test_a_spaced_or_indexed_spelling_still_matches(self) -> None:
        block = _block('"DB".arms[#i].x := #a;')
        assert find_field_writers([block], '"DB" . arms [ 1 ] . x')

    def test_an_inout_struct_binding_and_its_inner_writer(self) -> None:
        caller = _block('#drive(status := "DB".arm.output, speed := "DB".sp);')
        (binding,) = find_inout_struct_binding([caller], '"DB".arm.output')
        assert (binding.instance_name, binding.param_name) == ("drive", "status")
        assert binding.param_mapping == {"status": '"DB".arm.output', "speed": '"DB".sp'}
        callee = _block("#tmr(IN := #io.sub, PT := T#1s, Q => #io.sub);")
        assert find_local_subfield_writer(callee, "io", "sub") is not None

    def test_forward_usages_carry_call_metadata(self) -> None:
        block = _block('#drive(speed := "DB".sp, out => "DB".res);')
        (node,) = list(find_field_usages([block], '"DB".sp', TagIndexInfo()))
        assert (node.called_block_name, node.input_param_name) == ("MotorDrive", "speed")
        assert node.output_param_map == {'"DB".res': "out"}

    def test_state_variables_and_tag_assignments(self) -> None:
        block = _block(
            'CASE "DB".status.mode OF 1: #arr[0] := 1.0; END_CASE;\n'
            '"DO_PUMP" := #a > 0.0;\n'
            '"DB".in.x := "DI_START";'
        )
        assert [v.name for v in detect_state_variables_in_block(block)][0] == '"DB".status.mode'
        found = {(t.tag_name, t.direction, t.mapped_field) for t in find_assignments_in_block(block, set())}
        assert found == {("DO_PUMP", "write", "#a > 0.0"), ("DI_START", "read", '"DB".in.x')}

    def test_the_primary_tag_mapping_is_a_write_before_a_read(self) -> None:
        from plc_code.analyzer.logic_dependency.tag_assignment import find_all_tag_assignments

        block = _block('#arr[0] := "DO_PUMP";\n"DO_PUMP" := #a > 0.0;')
        (mapping,) = find_all_tag_assignments([block]).values()
        assert (mapping.direction, mapping.mapped_field) == ("write", "#a > 0.0")
