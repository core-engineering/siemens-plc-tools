"""The semantic diff: what changed, at edit granularity — never the formatting.

`plc code diff` exists because a text diff of TIA re-exports drowns a one-line
logic change in re-spaced expressions and shifted comments.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from plc_code.analyzer.block_diff import diff_blocks, diff_trees
from plc_code.cli import code_group as cli
from plc_code.parser.lexer import tokenize_with_newlines
from plc_code.parser.parser import SCLParser

_TEMPLATE = """FUNCTION_BLOCK "Probe"
    VAR_INPUT
        a : Int;
        threshold : Real := 1.5;
    END_VAR
    VAR_OUTPUT
        out : Int;
    END_VAR
    {{ S7_Language := "SCL" }}
    NETWORK
        REGION Logic
{body}
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""

_BODY = """            // computes the output
            IF #a > 0 THEN
                #out := #a + 1;
            ELSE
                #out := 0;
            END_IF;
            #out := #out * 2;
"""


def _block(source: str):
    return SCLParser(tokenize_with_newlines(source)).parse()


def _write(directory: Path, name: str, source: str) -> None:
    directory.mkdir(exist_ok=True)
    (directory / f"{name}.s7dcl").write_text(source, encoding="utf-8")


class TestFormattingIsInvisible:
    def test_respacing_and_comments_are_no_change(self) -> None:
        old = _TEMPLATE.format(body=_BODY)
        new = old.replace("// computes the output\n            ", "").replace("#a > 0", "#a   >   0")
        diff = diff_blocks(_block(old), _block(new))
        assert not diff.is_change

    def test_a_self_diff_of_a_real_fixture_tree_is_empty(self) -> None:
        fixtures = Path(__file__).parent / "fixtures"
        report = diff_trees(fixtures, fixtures)
        assert not report.has_changes


class TestEditGranularity:
    def test_one_branch_edit_reports_that_line_only(self) -> None:
        old = _TEMPLATE.format(body=_BODY)
        new = old.replace("#out := 0;", "#out := -1;")
        diff = diff_blocks(_block(old), _block(new))
        assert [(c.kind, c.text) for c in diff.statements] == [
            ("added", "#out := -1;"),
            ("removed", "#out := 0;"),
        ]
        assert all(c.region == "Logic" for c in diff.statements)

    def test_a_changed_condition_reports_the_header_not_the_body(self) -> None:
        old = _TEMPLATE.format(body=_BODY)
        new = old.replace("IF #a > 0 THEN", "IF #a >= 0 THEN")
        diff = diff_blocks(_block(old), _block(new))
        assert {c.text for c in diff.statements} == {"IF #a > 0 THEN", "IF #a >= 0 THEN"}

    def test_an_added_statement_is_one_addition(self) -> None:
        old = _TEMPLATE.format(body=_BODY)
        new = old.replace("            #out := #out * 2;", "            #out := #out * 2;\n            #a := 0;")
        diff = diff_blocks(_block(old), _block(new))
        assert [(c.kind, c.text) for c in diff.statements] == [("added", "#a := 0;")]


class TestInterface:
    def test_added_removed_retyped_redefaulted(self) -> None:
        old = _TEMPLATE.format(body=_BODY)
        new = (
            old.replace("a : Int;", "a : DInt;")
            .replace("threshold : Real := 1.5;", "threshold : Real := 2.0;\n        enable : Bool;")
        )
        diff = diff_blocks(_block(old), _block(new))
        kinds = {(c.name, c.kind) for c in diff.interface}
        assert kinds == {("a", "retyped"), ("threshold", "redefaulted"), ("enable", "added")}


class TestTrees:
    def test_added_and_removed_blocks(self, tmp_path: Path) -> None:
        source = _TEMPLATE.format(body=_BODY)
        _write(tmp_path / "old", "Probe", source)
        _write(tmp_path / "new", "Probe", source)
        _write(tmp_path / "new", "Fresh", source.replace('"Probe"', '"Fresh"'))
        report = diff_trees(tmp_path / "old", tmp_path / "new")
        assert [(b.name, b.kind) for b in report.blocks] == [("Fresh", "added")]

    def test_an_unreadable_export_is_an_error_not_a_crash(self, tmp_path: Path) -> None:
        _write(tmp_path / "old", "Broken", "FUNCTION_BLOCK \x00")
        _write(tmp_path / "new", "Probe", _TEMPLATE.format(body=_BODY))
        report = diff_trees(tmp_path / "old", tmp_path / "new")
        assert report.has_changes  # Probe is "added"; a parse crash lands in errors instead of raising


class TestCli:
    def test_identical_exits_zero_and_a_change_exits_one(self, tmp_path: Path) -> None:
        source = _TEMPLATE.format(body=_BODY)
        _write(tmp_path / "old", "Probe", source)
        _write(tmp_path / "new", "Probe", source.replace("#out := 0;", "#out := -1;"))
        runner = CliRunner()
        same = runner.invoke(cli, ["diff", str(tmp_path / "old"), str(tmp_path / "old")])
        assert same.exit_code == 0 and "Identical" in same.output
        changed = runner.invoke(cli, ["diff", str(tmp_path / "old"), str(tmp_path / "new")])
        assert changed.exit_code == 1
        assert "#out := -1;" in changed.output and "1 changed" in changed.output

    def test_json_output_is_machine_readable(self, tmp_path: Path) -> None:
        source = _TEMPLATE.format(body=_BODY)
        _write(tmp_path / "old", "Probe", source)
        _write(tmp_path / "new", "Probe", source.replace("a : Int;", "a : DInt;"))
        result = CliRunner().invoke(
            cli, ["diff", "-f", "json", str(tmp_path / "old"), str(tmp_path / "new")]
        )
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["identical"] is False
        (block,) = payload["blocks"]
        assert block["interface"][0]["kind"] == "retyped"
