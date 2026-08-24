"""SCL line coverage: which lines of a block the tests actually executed.

`plc code test --coverage` sets `PLC_SCL_COVERAGE`; every default-options
compile inside the pytest subprocesses instruments each statement with a
`touch(block, line)`, and the runtime merges executable and touched lines into
the named file at interpreter exit.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from plc_code.cli import _line_ranges
from plc_code.executor import PLCRuntime, compile_block
from plc_code.executor.models import TranspileOptions
from plc_code.parser.lexer import tokenize_with_newlines
from plc_code.parser.parser import SCLParser

_SOURCE = """FUNCTION_BLOCK "CovProbe"
    VAR_INPUT
        a : Int;
    END_VAR
    VAR_OUTPUT
        b : Int;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Logic
            IF #a > 0 THEN
                #b := 1;
            ELSE
                #b := -1;
            END_IF;
            #b := #b * 2;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


def _block():
    return SCLParser(tokenize_with_newlines(_SOURCE)).parse()


class TestInstrumentation:
    def test_executable_lines_cover_headers_and_both_branches(self) -> None:
        result = compile_block(_block(), options=TranspileOptions(instrument_coverage=True))
        assert result.success
        # IF header (11), then branch (12), else branch (14), trailing statement (16)
        assert result.transpile_result.executable_lines == [11, 12, 14, 16]

    def test_only_the_branch_that_ran_is_touched(self) -> None:
        from plc_code.executor import runtime as runtime_module

        runtime_module._COVERAGE_TOUCHED.clear()
        result = compile_block(_block(), options=TranspileOptions(instrument_coverage=True))
        assert result.fb_class is not None
        instance = result.fb_class(_runtime=PLCRuntime())
        instance.a = 5
        instance.execute()
        assert runtime_module._COVERAGE_TOUCHED["CovProbe"] == {11, 12, 16}
        instance.a = -5
        instance.execute()
        assert runtime_module._COVERAGE_TOUCHED["CovProbe"] == {11, 12, 14, 16}

    def test_without_the_option_nothing_is_instrumented(self) -> None:
        result = compile_block(_block())
        assert "touch(" not in result.transpile_result.python_code
        assert result.transpile_result.executable_lines == []


class TestExitTimeDump:
    def test_two_processes_merge_their_shares_into_one_file(self, tmp_path: Path) -> None:
        coverage_file = tmp_path / "cov.json"
        source_file = tmp_path / "CovProbe.s7dcl"
        source_file.write_text(_SOURCE, encoding="utf-8")
        script = (
            "import sys\n"
            "from pathlib import Path\n"
            "from plc_code.executor.harness import create_harness\n"
            "harness = create_harness(Path(sys.argv[1]))\n"
            "harness.set_inputs(a=int(sys.argv[2]))\n"
            "harness.execute()\n"
        )
        for value in ("5", "-5"):
            run = subprocess.run(
                [sys.executable, "-c", script, str(source_file), value],
                env={"PLC_SCL_COVERAGE": str(coverage_file), "PATH": "/usr/bin:/bin"},
                capture_output=True,
                text=True,
                cwd=Path.cwd(),
            )
            assert run.returncode == 0, run.stderr
        # One shard per process (safe under parallel workers); merge like the CLI does.
        merged: dict[str, set[int]] = {"executable": set(), "touched": set()}
        shards = list(tmp_path.glob("cov.json.*"))
        assert len(shards) == 2, "one shard per process"
        for shard in shards:
            part = json.loads(shard.read_text(encoding="utf-8"))
            merged["executable"] |= set(part["CovProbe"]["executable"])
            merged["touched"] |= set(part["CovProbe"]["touched"])
        assert sorted(merged["executable"]) == [11, 12, 14, 16]
        assert sorted(merged["touched"]) == [11, 12, 14, 16]  # both branches, across processes


def test_line_ranges_read_like_a_human_wrote_them() -> None:
    assert _line_ranges([3, 4, 5, 9, 11, 12]) == "3-5, 9, 11-12"
    assert _line_ranges([7]) == "7"
    assert _line_ranges([]) == ""
