"""Tests for the ``plc code transpile`` command.

Two modes:

- bare: print the generated Python. This is the debugging move that found the
  July batch of transpiler defects — being able to read what the block actually
  became.
- ``--check``: report blocks that fail to transpile, whose generated Python will
  not load, or will raise NameError, and exit non-zero so a downstream project
  can gate on it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from plc_code.cli import cli

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CLEAN_BLOCK = FIXTURES / "SignalDebounce.s7dcl"


def _block(name: str, body: str) -> str:
    return f"""
FUNCTION_BLOCK "{name}"
    VAR_INPUT
        a : Int;
    END_VAR
    VAR_OUTPUT
        b : Int;
    END_VAR
    {{ S7_Language := "SCL" }}
    NETWORK
        REGION Logic
{body}
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


# Deliberately broken SCL lives here, not in fixtures/: every block in that
# directory must stay clean, which is what test_diagnostics_corpus.py asserts.
#
# REPEAT/UNTIL has no node in the statement AST, so the statement parser
# rejects it outright and transpilation fails before any Python is generated
# for that construct -> TRANSPILE, an error.
_TRANSPILE_DEFECT = _block(
    "RepeatUser",
    "            REPEAT\n                #b := #b + 1;\n            UNTIL #b > 5\n            END_REPEAT;",
)

# SEL is not in BUILTIN_MAP, so the call survives into Python as a global read
# -> UNDEFINED_NAME, a warning: it only fails when that line runs.
_UNDEFINED_NAME_DEFECT = _block(
    "SelUser",
    "            #b := SEL(G := TRUE, IN0 := 1, IN1 := 2);",
)

# A bare (non-quoted) system builtin binding a parameter with `=>` as the whole
# right-hand side of an assignment. `render` refuses this shape outright (a
# positional call has nowhere to route an output binding to -- see
# `renderer._render_builtin_call`'s own docstring), and `generate_statements` no
# longer catches that refusal for a plain Assignment (Task 9 step 3): it propagates
# out of transpilation entirely -> TRANSPILE, an error, same category as
# `_TRANSPILE_DEFECT` above, not a warning caught only at run time like SEL.
_OUTPUT_BINDING_DEFECT = _block(
    "RdSysTUser",
    "            #b := RD_SYS_T(OUT => #b);",
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def unsupported_block(tmp_path: Path) -> Path:
    """A block using a construct the statement parser cannot read."""
    path = tmp_path / "RepeatUser.s7dcl"
    path.write_text(_TRANSPILE_DEFECT, encoding="utf-8")
    return path


@pytest.fixture
def undefined_name_block(tmp_path: Path) -> Path:
    """A block whose generated Python parses but reads an undefined name."""
    path = tmp_path / "SelUser.s7dcl"
    path.write_text(_UNDEFINED_NAME_DEFECT, encoding="utf-8")
    return path


@pytest.fixture
def output_binding_defect_block(tmp_path: Path) -> Path:
    """A block whose only assignment binds a bare system builtin's `=>` output."""
    path = tmp_path / "RdSysTUser.s7dcl"
    path.write_text(_OUTPUT_BINDING_DEFECT, encoding="utf-8")
    return path


@pytest.fixture
def mixed_dir(tmp_path: Path) -> Path:
    """A directory holding one clean block and one broken one."""
    directory = tmp_path / "blocks"
    directory.mkdir()
    (directory / "SelUser.s7dcl").write_text(_UNDEFINED_NAME_DEFECT, encoding="utf-8")
    (directory / "Fine.s7dcl").write_text(
        _block("Fine", "            IF #a > 1 THEN\n                #b := 2;\n            END_IF;"),
        encoding="utf-8",
    )
    return directory


# A VAR_INPUT declaration missing its colon. This is what really trips the
# structural parser in customer code (project-C's FCT_GEST_2PPES.s7dcl:
# "ParseError: Expected COLON at line 35, got SEMICOLON") — here reduced to a
# minimal block that raises the same ParseError class, without copying any
# customer source into this repo.
_UNREADABLE_BLOCK = """
FUNCTION_BLOCK "Unparseable"
    VAR_INPUT
        a Int;
    END_VAR
    VAR_OUTPUT
        b : Int;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Logic
            IF #a > 1 THEN
                #b := 2;
            END_IF;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


@pytest.fixture
def dir_with_unreadable_file(tmp_path: Path) -> Path:
    """One well-formed block plus one file the structural parser cannot read.

    ``mixed_dir`` above holds two blocks that both parse structurally — one
    just fails ``--check`` diagnostics. This fixture is the case
    ``test_json_is_the_only_thing_on_stdout`` missed: ``parse_scl_file`` itself
    raises, which is what triggers the "Skipped" warning in ``transpile``.
    """
    directory = tmp_path / "blocks"
    directory.mkdir()
    (directory / "Unparseable.s7dcl").write_text(_UNREADABLE_BLOCK, encoding="utf-8")
    (directory / "Fine.s7dcl").write_text(
        _block("Fine", "            IF #a > 1 THEN\n                #b := 2;\n            END_IF;"),
        encoding="utf-8",
    )
    return directory


class TestCommandIsRegistered:
    def test_listed_in_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "transpile" in result.output

    def test_has_check_flag(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["transpile", "--help"])
        assert result.exit_code == 0
        assert "--check" in result.output


class TestEmitMode:
    """Bare ``transpile`` prints the generated Python."""

    def test_prints_generated_python(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["transpile", str(CLEAN_BLOCK)])
        assert result.exit_code == 0
        assert "class " in result.output
        assert "def execute" in result.output

    def test_emit_mode_succeeds_on_a_defective_block(
        self, runner: CliRunner, unsupported_block: Path
    ) -> None:
        """Emitting is for reading the output, not judging it.

        REPEAT/UNTIL has no statement-AST node, so the rejected construct
        contributes no lines rather than being copied into the output — the
        rest of the block (the class, its fields) still prints, and the
        keywords the parser could not read do not appear in valid Python.
        """
        result = runner.invoke(cli, ["transpile", str(unsupported_block)])
        assert result.exit_code == 0
        assert "class RepeatUser" in result.stdout
        assert "UNTIL" not in result.stdout
        # ...but the failure is said out loud, on stderr, not left to be noticed.
        assert "transpile failed" in result.stderr

    def test_missing_path_is_an_error(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(cli, ["transpile", str(tmp_path / "nope.s7dcl")])
        assert result.exit_code != 0


class TestCheckMode:
    """``--check`` reports and gates."""

    def test_clean_block_passes(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["transpile", "--check", str(CLEAN_BLOCK)])
        assert result.exit_code == 0

    def test_defective_block_exits_non_zero(self, runner: CliRunner, undefined_name_block: Path) -> None:
        result = runner.invoke(cli, ["transpile", "--check", str(undefined_name_block)])
        assert result.exit_code == 1

    def test_defective_block_names_the_symbol(self, runner: CliRunner, undefined_name_block: Path) -> None:
        result = runner.invoke(cli, ["transpile", "--check", str(undefined_name_block)])
        assert "SEL" in result.output

    def test_unsupported_construct_is_reported(self, runner: CliRunner, unsupported_block: Path) -> None:
        result = runner.invoke(cli, ["transpile", "--check", str(unsupported_block)])
        assert result.exit_code == 1
        assert "RepeatUser" in result.output
        # The parser's message states its own line; no second location is added.
        assert "line 14, column" in result.output
        assert "(SCL line" not in result.output

    def test_output_binding_on_a_bare_builtin_fails_the_transpile(
        self, runner: CliRunner, output_binding_defect_block: Path
    ) -> None:
        """Task 9 step 3: what used to be a silently-broken fallback is now a hard failure."""
        result = runner.invoke(cli, ["transpile", "--check", str(output_binding_defect_block)])
        assert result.exit_code == 1
        assert "RdSysTUser" in result.output

        # This message does not state its own line, so text mode adds it from the
        # diagnostic's `source_line` -- a parser message ("line 14, column 19: ...")
        # already does and gets no doubled location.
        assert "(SCL line 12)" in result.output
        json_result = runner.invoke(
            cli, ["transpile", "--check", "-f", "json", str(output_binding_defect_block)]
        )
        payload = json.loads(json_result.output)
        (finding,) = payload["diagnostics"]
        assert finding["code"] == "TRANSPILE"
        assert finding["source_line"] == 12
        assert finding["line"] is None  # no generated Python to point into

    def test_whole_fixture_corpus_is_clean(self, runner: CliRunner) -> None:
        """The shipped fixtures are blocks the toolchain handles — all of them."""
        result = runner.invoke(cli, ["transpile", "--check", str(FIXTURES)])
        assert result.exit_code == 0, result.output

    def test_directory_scan_reports_only_the_broken_block(self, runner: CliRunner, mixed_dir: Path) -> None:
        result = runner.invoke(cli, ["transpile", "--check", str(mixed_dir)])
        assert result.exit_code == 1
        assert "SelUser" in result.output
        assert "Fine" not in result.output

    def test_check_does_not_print_generated_python(self, runner: CliRunner) -> None:
        """The report is the output; the code would drown it."""
        result = runner.invoke(cli, ["transpile", "--check", str(CLEAN_BLOCK)])
        assert "def execute" not in result.output


class TestJsonOutput:
    def test_clean_block_json_shape(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["transpile", "--check", "-f", "json", str(CLEAN_BLOCK)])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["blocks_checked"] == 1
        assert payload["diagnostics"] == []

    def test_defective_block_json_carries_the_finding(
        self, runner: CliRunner, undefined_name_block: Path
    ) -> None:
        result = runner.invoke(cli, ["transpile", "--check", "-f", "json", str(undefined_name_block)])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["blocks_checked"] == 1
        assert len(payload["diagnostics"]) >= 1
        finding = next(f for f in payload["diagnostics"] if "SEL" in f["message"])
        assert finding["code"] == "UNDEFINED_NAME"
        assert finding["severity"] == "warning"
        assert finding["block"] == "SelUser"
        assert finding["line"] > 0
        assert finding["source"].endswith("SelUser.s7dcl")

    def test_transpile_defect_json_is_an_error(self, runner: CliRunner, unsupported_block: Path) -> None:
        result = runner.invoke(cli, ["transpile", "--check", "-f", "json", str(unsupported_block)])
        assert result.exit_code == 1
        finding = json.loads(result.output)["diagnostics"][0]
        assert finding["code"] == "TRANSPILE"
        assert finding["severity"] == "error"

    def test_json_is_the_only_thing_on_stdout(self, runner: CliRunner) -> None:
        """Parseable without stripping a banner."""
        result = runner.invoke(cli, ["transpile", "--check", "-f", "json", str(CLEAN_BLOCK)])
        json.loads(result.output)


class TestSkippedFileDoesNotCorruptJson:
    """A file the structural parser cannot read must not land on stdout in -f json.

    ``CliRunner`` (Click 8.4) exposes ``result.output`` as stdout and stderr
    merged together, and ``result.stdout`` / ``result.stderr`` as the same two
    streams kept separate — no special runner construction is needed to get
    them apart, just reading the right attribute.
    """

    def test_check_json_still_parses(self, runner: CliRunner, dir_with_unreadable_file: Path) -> None:
        result = runner.invoke(cli, ["transpile", "--check", "-f", "json", str(dir_with_unreadable_file)])
        payload = json.loads(result.stdout)
        assert payload["blocks_checked"] == 1

    def test_conformance_json_still_parses(self, runner: CliRunner, dir_with_unreadable_file: Path) -> None:
        result = runner.invoke(
            cli, ["transpile", "--conformance", "-f", "json", str(dir_with_unreadable_file)]
        )
        payload = json.loads(result.stdout)
        assert payload["blocks"] == 1

    def test_skip_warning_is_still_emitted_on_stderr(
        self, runner: CliRunner, dir_with_unreadable_file: Path
    ) -> None:
        """A silently dropped warning would be a worse bug than the stdout leak."""
        result = runner.invoke(cli, ["transpile", "--check", "-f", "json", str(dir_with_unreadable_file)])
        assert "Skipped" in result.stderr
        assert "Unparseable.s7dcl" in result.stderr
        # And it must not have leaked back onto stdout alongside the JSON.
        assert "Skipped" not in result.stdout

    def test_text_mode_skip_warning_stays_on_stdout(
        self, runner: CliRunner, dir_with_unreadable_file: Path
    ) -> None:
        """Text mode is unchanged: the warning is still where a human looks."""
        result = runner.invoke(cli, ["transpile", "--check", str(dir_with_unreadable_file)])
        assert "Skipped" in result.stdout
        assert "Unparseable.s7dcl" in result.stdout
