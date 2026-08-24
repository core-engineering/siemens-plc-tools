"""Command-line interface for PLC Code tools.

This module provides the CLI commands for the plc code subgroup.

Example
-------
$ plc code status
$ plc code lint
$ plc code docs
$ plc code export pdf -o report.pdf
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from plc_code import __version__
from plc_code.docmap.loader import load_docmap
from plc_code.docmap.resolver import Resolver
from plc_code.docmap.schema import DocMap
from plc_code.drawio_generator.page_builder import build_sheet
from plc_code.drawio_generator.xml_writer import write_drawio

console = Console()
console_err = Console(stderr=True)


# =============================================================================
# Code CLI Group (Plugin for plc-tools)
# =============================================================================


@click.group(name="code")
@click.version_option(version=__version__, prog_name="plc-code")
@click.pass_context
def code_group(ctx: click.Context) -> None:
    """PLC code analysis and documentation tools.

    Provides commands for analyzing, linting, and documenting TIA Portal exports
    (SCL, LADDER, and other PLC languages).
    """
    ctx.ensure_object(dict)


# Alias for backwards compatibility
cli = code_group


# =============================================================================
# Init Command
# =============================================================================


@code_group.command()
@click.option("--name", "-n", default="PLC Project", help="Project name")
@click.option("--code", "-c", default="", help="Project code/identifier")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing files")
@click.option("--with-tests", is_flag=True, help="Set up unit testing support (creates pyproject.toml)")
def init(name: str, code: str, force: bool, with_tests: bool) -> None:
    """Initialize a new PLC project configuration.

    Creates a plc.yaml file in the current directory with default settings.
    Use --with-tests to also create pyproject.toml for unit testing support.
    """
    from plc_code.core.config import generate_default_config

    cwd = Path.cwd()
    config_path = cwd / "plc.yaml"

    if config_path.exists() and not force:
        console.print(f"[red]Error:[/red] {config_path} already exists.")
        console.print("Use --force to overwrite.")
        raise SystemExit(1)

    content = generate_default_config(name=name, code=code)
    config_path.write_text(content, encoding="utf-8")
    console.print(f"[green]Created:[/green] {config_path}")

    if with_tests:
        pyproject_path = cwd / "pyproject.toml"
        if pyproject_path.exists() and not force:
            console.print(f"[yellow]Skipped:[/yellow] {pyproject_path} already exists.")
        else:
            # Generate a minimal pyproject.toml for testing
            project_slug = name.lower().replace(" ", "-").replace("_", "-")

            # Check if 203-plc-tools is a sibling directory
            plc_tools_path = cwd.parent / "203-plc-tools"
            if plc_tools_path.exists():
                source_line = 'plc-tools = { path = "../203-plc-tools", editable = true }'
            else:
                source_line = '# plc-tools = { path = "../path-to-plc-tools", editable = true }'

            pyproject_content = f"""[project]
name = "{project_slug}"
version = "0.1.0"
description = "{name}"
requires-python = ">=3.12"
dependencies = [
    "plc-tools",
]

[dependency-groups]
dev = [
    "pytest>=9.0.0",
]

[tool.pytest.ini_options]
testpaths = ["test-cases"]
python_files = ["test_*.py"]

[tool.uv.sources]
{source_line}
"""
            pyproject_path.write_text(pyproject_content, encoding="utf-8")
            console.print(f"[green]Created:[/green] {pyproject_path}")

        # Create test-cases directory
        test_dir = cwd / "test-cases"
        if not test_dir.exists():
            test_dir.mkdir()
            console.print(f"[green]Created:[/green] {test_dir}/")

        console.print("\n[bold]Testing setup complete![/bold]")
        console.print("Run 'uv sync' to install dependencies, then 'plc test' to run tests.")
    else:
        console.print("\nEdit plc.yaml to configure paths for your project.")
        console.print("Then run 'plc status' to verify the configuration.")
        console.print("\n[dim]Tip: Use 'plc init --with-tests' to enable unit testing.[/dim]")


# =============================================================================
# Status Command
# =============================================================================


@code_group.command()
def status() -> None:
    """Show project status and configuration."""
    from plc_code.core.config import load_config

    try:
        config = load_config()
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1) from e

    console.print(f"[bold]Project:[/bold] {config.name}")
    if config.code:
        console.print(f"[bold]Code:[/bold] {config.code}")
    console.print(f"[bold]Root:[/bold] {config.root_path}")

    console.print("\n[bold]Paths:[/bold]")
    _print_path_status("  Source", config.source_path, config.paths.source)
    _print_path_status("  Tags", config.tags_path, config.paths.tags)
    _print_path_status("  Docs", config.docs_path, config.paths.docs)
    _print_path_status("  Tests", config.tests_path, config.paths.tests)

    # Count source files
    source_files = config.get_source_files()
    if source_files:
        console.print(f"\n[bold]Source Files:[/bold] {len(source_files)} .s7dcl files")

    # Show quality/testing status
    console.print(f"\n[bold]Quality Analysis:[/bold] {'enabled' if config.quality.enabled else 'disabled'}")
    console.print(f"[bold]Testing:[/bold] {'enabled' if config.testing.enabled else 'disabled'}")


def _print_path_status(label: str, abs_path: Path, rel_path: str) -> None:
    """Print path status with checkmark or X."""
    if abs_path.exists():
        console.print(f"{label}: [green]✓[/green] {rel_path}")
    else:
        console.print(f"{label}: [red]✗[/red] {rel_path} [dim](not found)[/dim]")


# =============================================================================
# Lint Command
# =============================================================================


@code_group.command()
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format",
)
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
def lint(output_format: str, verbose: bool, no_color: bool, path: Path | None) -> None:
    """Run code quality analysis on SCL files.

    If PATH is not specified, uses source path from plc.yaml.
    """
    from plc_code.analyzer.quality import AnalysisRunner, CLIReporter, Severity
    from plc_code.parser import Block, parse_scl_file
    from plc_code.project.discovery import discover_blocks

    # Status/diagnostic chatter must not land on stdout in JSON mode, or it would
    # corrupt the JSON payload printed there. Same pattern as `transpile --check`.
    diag_console = console_err if output_format == "json" else console

    # Determine source path
    safety_path_pattern = "safety"
    # Only a loaded plc.yaml can turn the gate off; an explicit PATH argument
    # never reads config at all, so it keeps the strict default.
    fail_on_error = True
    if path is None:
        try:
            from plc_code.core.config import load_config

            config = load_config()
            path = config.source_path
            safety_path_pattern = config.quality.safety_path_pattern
            fail_on_error = config.quality.fail_on_error
        except FileNotFoundError:
            diag_console.print("[red]Error:[/red] No plc.yaml found and no path specified.")
            diag_console.print("Run 'plc init' or specify a path: plc lint <path>")
            raise SystemExit(1) from None

    if not path.exists():
        diag_console.print(f"[red]Error:[/red] Source not found: {path}")
        raise SystemExit(1)

    # Discover blocks
    try:
        if path.is_file():
            block_files = [path]
        else:
            blocks_found = discover_blocks(path)
            block_files = [bf.source_path for bf in blocks_found]

        if not block_files:
            diag_console.print("[yellow]No .s7dcl files found to analyze.[/yellow]")
            raise SystemExit(1)

        diag_console.print(f"Analyzing {len(block_files)} block(s)...", style="dim")

        # Parse all blocks
        blocks = []
        sources: list[tuple[Path, Block]] = []
        for block_path in block_files:
            try:
                block = parse_scl_file(Path(block_path))
                blocks.append(block)
                sources.append((Path(block_path), block))
            except Exception as e:
                if verbose:
                    diag_console.print(f"[yellow]Warning:[/yellow] Failed to parse {block_path}: {e}")

        if not blocks:
            diag_console.print("[red]No blocks could be parsed.[/red]")
            raise SystemExit(1)

        # Run analysis
        runner = AnalysisRunner(safety_path_pattern=safety_path_pattern)
        result = runner.analyze_blocks(blocks, sources=sources)

        # Output results
        if output_format == "json":
            output = {
                "passed": result.passed,
                "total_blocks": len(result.block_results),
                "blocks_passed": result.blocks_passed,
                "total_errors": result.total_errors,
                "total_warnings": result.total_warnings,
                "total_info": result.total_info,
                "blocks": [
                    {
                        "name": br.block_name,
                        "type": br.block_type,
                        "source": str(br.source_file),
                        "passed": br.passed,
                        "errors": br.error_count,
                        "warnings": br.warning_count,
                        "info": br.info_count,
                        "violations": [
                            {
                                "rule": v.rule_code,
                                "severity": v.severity.value,
                                "message": v.message,
                                "context": v.context,
                                "suggestion": v.suggestion,
                            }
                            for v in br.violations
                        ],
                        "metrics": br.metrics,
                    }
                    for br in result.block_results
                ],
                "project_violations": [
                    {
                        "rule": v.rule_code,
                        "severity": v.severity.value,
                        "message": v.message,
                        "context": v.context,
                        "suggestion": v.suggestion,
                    }
                    for v in result.project_violations
                ],
            }
            print(json.dumps(output, indent=2))
        else:
            reporter = CLIReporter()
            use_color = not no_color
            print(reporter.report(result, use_color=use_color))

            if result.project_violations:
                console.print("\n[bold]Project-level findings[/bold]")
                for violation in result.project_violations:
                    marker = "[red]✗[/red]" if violation.severity is Severity.ERROR else "[yellow]⚠[/yellow]"
                    console.print(
                        f"  {marker} {violation.rule_code} {violation.context}: " f"{violation.message}"
                    )

        # Exit code. `code.quality.fail_on_error: false` reports every finding and
        # still exits 0 — what the bundled example project asks for, and what its
        # own plc.yaml has always claimed to do.
        raise SystemExit(0 if result.passed or not fail_on_error else 1)

    except SystemExit:
        raise
    except Exception as e:
        diag_console.print(f"[red]Error during analysis:[/red] {e}")
        raise SystemExit(1) from e


@code_group.command()
@click.option(
    "--check",
    is_flag=True,
    help="Report blocks that fail to transpile, will not load, or will raise NameError",
)
@click.option(
    "--conformance",
    is_flag=True,
    help="Report how much SCL the statement parser reads (always exits 0)",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format for --check/--conformance",
)
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
def transpile(check: bool, conformance: bool, output_format: str, path: Path | None) -> None:
    """Show or check the Python generated from SCL blocks.

    Without --check, prints the generated Python. That is the fastest way to see
    what a block actually became when it misbehaves in the harness.

    With --check, reports blocks that fail to transpile (a construct the
    statement parser cannot read, reported with its SCL location), blocks whose
    generated Python does not parse, or blocks that read a name nothing defines.
    Exits 1 if anything is reported.

    With --conformance, reports how much SCL the token-driven statement parser
    can read, in more detail than a --check pass does (per-region and
    per-network breakdown, a count by statement kind, separate expression-slice
    coverage). This is a report, not a gate, and always exits 0.

    If PATH is not specified, uses source path from plc.yaml.
    """
    from plc_core.reporting import Severity

    from plc_code.executor.diagnostics import check_block
    from plc_code.executor.transpiler import transpile_block
    from plc_code.parser import parse_scl_file
    from plc_code.project.discovery import discover_blocks

    # In JSON mode, stdout must carry only the JSON payload. Anything that can
    # appear before it — or instead of it, on an early exit — is routed to
    # stderr so it stays visible without corrupting a machine reader's stdout.
    # In text mode this is exactly `console`, so nothing changes for a human.
    diag_console = console_err if output_format == "json" else console

    if path is None:
        try:
            from plc_code.core.config import load_config

            path = load_config().source_path
        except FileNotFoundError:
            diag_console.print("[red]Error:[/red] No plc.yaml found and no path specified.")
            diag_console.print("Specify a path: plc code transpile <path>")
            raise SystemExit(1) from None

    if not path.exists():
        diag_console.print(f"[red]Error:[/red] Source not found: {path}")
        raise SystemExit(1)

    if path.is_file():
        block_files = [path]
    else:
        block_files = [bf.source_path for bf in discover_blocks(path)]

    if not block_files:
        diag_console.print("[yellow]No .s7dcl files found.[/yellow]")
        raise SystemExit(1)

    blocks: list[tuple[Path, Any]] = []
    for block_file in block_files:
        try:
            block = parse_scl_file(block_file)
        except Exception as e:  # noqa: BLE001 - a bad file must not abort the run
            diag_console.print(f"[yellow]Skipped[/yellow] {block_file.name}: {type(e).__name__}: {e}")
            continue
        if block is not None and block.name:
            blocks.append((block_file, block))

    if conformance:
        from plc_code.parser.conformance import build_report

        report = build_report(blocks)
        if output_format == "json":
            print(
                json.dumps(
                    {
                        "blocks": report.blocks,
                        "clean_blocks": report.clean_blocks,
                        "block_clean_rate": round(report.block_clean_rate, 4),
                        "regions": report.regions,
                        "clean_regions": report.clean_regions,
                        "region_clean_rate": round(report.region_clean_rate, 4),
                        "networks": report.networks,
                        "clean_networks": report.clean_networks,
                        "network_clean_rate": round(report.network_clean_rate, 4),
                        "statements": report.statements,
                        "tokens": report.tokens,
                        "consumed": report.consumed,
                        "coverage": round(report.coverage, 4),
                        "by_statement_kind": report.by_statement_kind,
                        "errors": [
                            {
                                "block": name,
                                "line": e.line,
                                "column": e.column,
                                "token": e.token_value,
                                "expected": e.expected,
                            }
                            for name, e in report.errors
                        ],
                        "silent_loss": report.silent_loss,
                        "expression_slices": report.expression_slices,
                        "expression_slices_parsed": report.expression_slices_parsed,
                        "expression_rate": round(report.expression_rate, 4),
                        "expression_errors": [
                            {
                                "block": name,
                                "line": e.line,
                                "column": e.column,
                                "token": e.token_value,
                                "expected": e.expected,
                            }
                            for name, e in report.expression_errors
                        ],
                    },
                    indent=2,
                )
            )
        else:
            console.print(
                f"[bold]{report.blocks}[/bold] block(s), "
                f"[bold]{report.regions}[/bold] region(s), "
                f"[bold]{report.networks}[/bold] network(s) with SCL outside any region, "
                f"[bold]{report.statements}[/bold] statement(s) parsed"
            )
            console.print(
                f"token coverage: [bold]{report.coverage:.1%}[/bold] " f"({report.consumed}/{report.tokens})"
            )
            console.print(
                f"clean blocks: [bold]{report.block_clean_rate:.1%}[/bold] "
                f"({report.clean_blocks}/{report.blocks}); "
                f"clean regions: [bold]{report.region_clean_rate:.1%}[/bold] "
                f"({report.clean_regions}/{report.regions}); "
                f"clean networks: [bold]{report.network_clean_rate:.1%}[/bold] "
                f"({report.clean_networks}/{report.networks})"
            )
            if report.by_statement_kind:
                console.print("\n[bold]Statements read[/bold]")
                for kind, count in report.by_statement_kind.items():
                    console.print(f"  {count:6}  {kind}")
            console.print(
                f"\nexpression rate: [bold]{report.expression_rate:.1%}[/bold] "
                f"({report.expression_slices_parsed}/{report.expression_slices})"
            )
            if report.errors:
                console.print(f"\n[bold]Not read[/bold] ({len(report.errors)})")
                for name, error in report.errors[:40]:
                    console.print(f"  {name}: {error.message}")
                if len(report.errors) > 40:
                    console.print(f"  ... and {len(report.errors) - 40} more", style="dim")
            if report.expression_errors:
                console.print(f"\n[bold]Expressions not read[/bold] ({len(report.expression_errors)})")
                for name, error in report.expression_errors[:40]:
                    console.print(f"  {name}: {error.message}")
                if len(report.expression_errors) > 40:
                    console.print(f"  ... and {len(report.expression_errors) - 40} more", style="dim")
            if report.silent_loss:
                console.print(
                    f"\n[bold red]Silent loss[/bold red] ({len(report.silent_loss)}) "
                    "— tokens dropped rather than read, rejected, or flagged:"
                )
                for problem in report.silent_loss[:40]:
                    console.print(f"  {problem}")
                if len(report.silent_loss) > 40:
                    console.print(f"  ... and {len(report.silent_loss) - 40} more", style="dim")
        # A report, not a gate. Nothing generates from the AST yet, so an
        # unparsed statement does not mean a broken block.
        raise SystemExit(0)

    # Positional call arguments bind against the callee's declaration, read from the
    # same tree the blocks came from (searched recursively).
    from plc_code.executor.runtime import PLCRuntime

    search_root = path.parent if path.is_file() else path
    resolver = PLCRuntime(block_search_paths=[search_root]).block_signature

    if not check:
        # Emitting is for reading the output, not judging it: whatever was generated
        # prints and the exit code stays 0, but a failed transpile is said out loud on
        # stderr rather than left to be noticed from the code alone.
        for block_file, block in blocks:
            if len(blocks) > 1:
                console.print(f"[bold]# {block_file.name} — {block.name}[/bold]")
            result = transpile_block(block, signature_resolver=resolver)
            if not result.success:
                for message in result.errors or ["Transpilation failed"]:
                    console_err.print(f"[yellow]{block_file.name}: transpile failed:[/yellow] {message}")
            print(result.python_code)
        raise SystemExit(0)

    diagnostics = [
        d
        for block_file, block in blocks
        for d in check_block(block, source_file=block_file, signature_resolver=resolver)
    ]

    if output_format == "json":
        print(
            json.dumps(
                {
                    "blocks_checked": len(blocks),
                    "diagnostics": [
                        {
                            "block": d.block_name,
                            "source": str(d.source_file) if d.source_file else None,
                            "code": d.code,
                            "severity": d.severity.value,
                            "message": d.message,
                            "line": d.line,
                            "generated_line": d.generated_line,
                            "source_line": d.source_line,
                        }
                        for d in diagnostics
                    ],
                },
                indent=2,
            )
        )
        raise SystemExit(1 if diagnostics else 0)

    if not diagnostics:
        console.print(f"[green]OK[/green] {len(blocks)} block(s) transpile to loadable Python.")
        raise SystemExit(0)

    by_block: dict[str, list[Any]] = {}
    for diagnostic in diagnostics:
        by_block.setdefault(diagnostic.block_name, []).append(diagnostic)

    for block_name, found in by_block.items():
        console.print(f"\n[bold]{block_name}[/bold]")
        for diagnostic in found:
            marker = "[red]✗[/red]" if diagnostic.severity is Severity.ERROR else "[yellow]⚠[/yellow]"
            # A TRANSPILE finding points into the SCL source; the parser's own
            # messages already state "line N, column M", so the location is only
            # added when the message does not carry it. The other codes point into
            # the generated Python.
            location = ""
            if diagnostic.line:
                location = f" (generated line {diagnostic.line})"
            elif diagnostic.source_line and f"line {diagnostic.source_line}" not in diagnostic.message:
                location = f" (SCL line {diagnostic.source_line})"
            console.print(f"  {marker} {diagnostic.code}{location}: {diagnostic.message}")
            if diagnostic.generated_line:
                console.print(f"      {diagnostic.generated_line}", style="dim")

    console.print(
        f"\n{len(by_block)} of {len(blocks)} block(s) would misbehave at run time "
        f"({len(diagnostics)} finding(s))."
    )
    if any(d.code == "UNDEFINED_NAME" for d in diagnostics):
        console.print(
            "An undefined name is normally an SCL builtin or statement the transpiler "
            "does not support, copied through to the generated Python unchanged.",
            style="dim",
        )
    raise SystemExit(1)


# =============================================================================
# Export Command Group
# =============================================================================


@code_group.group()
def export() -> None:
    """Export reports and documentation."""
    pass


@export.command(name="pdf")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("report.pdf"),
    help="Output PDF file path",
)
@click.option("--title", default="PLC Code Analysis Report", help="Report title")
@click.option("--company", default="", help="Company name for header/footer")
@click.option("--logo", type=click.Path(exists=True, path_type=Path), default=None, help="Path to logo image")
@click.option("--author", default="", help="Report author name")
@click.option("--no-quality", is_flag=True, help="Exclude quality analysis")
@click.option("--no-tests", is_flag=True, help="Exclude test results")
@click.option("--no-toc", is_flag=True, help="Exclude table of contents")
@click.option("--markdown-only", is_flag=True, help="Generate only markdown (skip PDF)")
@click.option(
    "--template-dir",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Custom template directory",
)
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
def export_pdf(
    output: Path,
    title: str,
    company: str,
    logo: Path | None,
    author: str,
    no_quality: bool,
    no_tests: bool,
    no_toc: bool,
    markdown_only: bool,
    template_dir: Path | None,
    path: Path | None,
) -> None:
    """Export quality and test results as PDF report.

    If PATH is not specified, uses source path from plc.yaml.
    """
    from plc_code.analyzer.quality import AnalysisRunner
    from plc_code.analyzer.quality.models import ProjectAnalysisResult
    from plc_code.exporter import BrandingConfig, PDFExportConfig, PDFGenerator
    from plc_code.parser import parse_scl_file
    from plc_code.project.discovery import discover_blocks
    from plc_code.testing.discovery import build_test_registry
    from plc_code.testing.models import BlockTestResult, ProjectTestResult
    from plc_code.testing.runner import TestRunner

    # Determine source path
    if path is None:
        try:
            from plc_code.core.config import load_config

            config = load_config()
            path = config.source_path
            test_dirs = config.get_test_dirs()
        except FileNotFoundError:
            console.print("[red]Error:[/red] No plc.yaml found and no path specified.")
            raise SystemExit(1) from None
    else:
        test_dirs = [Path("test-cases")]

    if not path.exists():
        console.print(f"[red]Error:[/red] Source not found: {path}")
        raise SystemExit(1)

    if not path.is_dir():
        console.print(f"[red]Error:[/red] Source must be a directory: {path}")
        raise SystemExit(1)

    console.print(f"Generating PDF report from: {path}")

    try:
        # Discover and parse blocks
        blocks_found = discover_blocks(path)
        if not blocks_found:
            console.print("[red]No .s7dcl files found.[/red]")
            raise SystemExit(1)

        console.print(f"Found {len(blocks_found)} blocks")

        blocks = []
        for block_file in blocks_found:
            try:
                block = parse_scl_file(block_file.source_path)
                blocks.append(block)
            except Exception as e:
                console.print(f"[yellow]Warning:[/yellow] Failed to parse {block_file.source_path}: {e}")

        if not blocks:
            console.print("[red]No blocks could be parsed.[/red]")
            raise SystemExit(1)

        # Run quality analysis
        analysis_result: ProjectAnalysisResult | None = None
        if not no_quality:
            console.print("Running quality analysis...")
            runner = AnalysisRunner()
            analysis_result = runner.analyze_blocks(blocks)
            console.print(
                f"  {len(analysis_result.block_results)} blocks analyzed, "
                f"{analysis_result.total_errors} errors, "
                f"{analysis_result.total_warnings} warnings"
            )

        # Run tests
        test_result: ProjectTestResult | None = None
        if not no_tests:
            console.print("Running unit tests...")
            block_names = [b.name for b in blocks]
            test_registry = build_test_registry(block_names, test_dirs)

            if test_registry:
                test_runner = TestRunner(test_dirs=test_dirs)
                test_results_dict = test_runner.run_all_tests(test_registry)

                block_results: list[BlockTestResult] = list(test_results_dict.values())
                tested_names = set(test_results_dict.keys())
                for name in block_names:
                    if name not in tested_names:
                        block_results.append(BlockTestResult(block_name=name, test_file=None))
                test_result = ProjectTestResult(block_results=block_results)
                console.print(
                    f"  {test_result.blocks_tested} blocks tested, "
                    f"{test_result.total_passed}/{test_result.total_tests} tests passed"
                )
            else:
                block_results = [BlockTestResult(block_name=name, test_file=None) for name in block_names]
                test_result = ProjectTestResult(block_results=block_results)
                console.print("  No test files found")

        # Configure branding
        branding = BrandingConfig(
            company_name=company or "",
            project_title=title,
            logo_path=logo,
            author=author,
        )

        # Configure export
        export_config = PDFExportConfig(
            output_path=output,
            branding=branding,
            include_quality=not no_quality,
            include_tests=not no_tests,
            include_toc=not no_toc,
            template_dir=template_dir,
        )

        # Generate
        generator = PDFGenerator(export_config)

        if markdown_only:
            console.print("Generating markdown...")
            result = generator.generate_markdown_only(analysis_result, test_result)
            if result.success:
                md_path = output.with_suffix(".md")
                md_path.write_text(result.markdown_content, encoding="utf-8")
                console.print(f"[green]Markdown report saved to:[/green] {md_path}")
            else:
                console.print(f"[red]Error:[/red] {result.error}")
                raise SystemExit(1)
        else:
            console.print("Generating PDF...")
            result = generator.generate(analysis_result, test_result)

            if result.success:
                console.print(f"[green]PDF report saved to:[/green] {result.output_path}")
                if result.warnings:
                    for warning in result.warnings:
                        console.print(f"[yellow]Warning:[/yellow] {warning}")
            else:
                console.print(f"[red]Error:[/red] {result.error}")
                if result.markdown_content:
                    md_path = output.with_suffix(".md")
                    md_path.write_text(result.markdown_content, encoding="utf-8")
                    console.print(f"Markdown saved for debugging: {md_path}")
                raise SystemExit(1)

    except SystemExit:
        raise
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1) from e


@export.command(name="params")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to config file (default: plc.yaml → code.export.params)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output docx path (overrides config)",
)
@click.option(
    "--template",
    "-t",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Template docx path (overrides config)",
)
@click.option(
    "--no-cover",
    is_flag=True,
    help="Skip cover page, generate tables only",
)
def export_params(
    config: Path | None,
    output: Path | None,
    template: Path | None,
    no_cover: bool,
) -> None:
    """Generate parameter table document from TIA Portal XML exports.

    Parses InstanceDB XML parameter files and generates an organized Word
    document with cover page and parameter tables grouped by section.

    Configuration is loaded from plc.yaml (code.export.params section) or specified with --config.
    """
    from plc_code.exporter.param_config import load_params_config
    from plc_code.exporter.params_generator import generate_params_document

    try:
        # Load configuration
        if config is None:
            # Search for config file in current directory
            config = Path.cwd()

        params_config = load_params_config(config)

        # Apply CLI overrides
        if output is not None:
            params_config.document.output = str(output)
        if template is not None:
            params_config.document.template = str(template)
        if no_cover:
            params_config.document.template = ""

        console.print(f"Loading parameters from {len(params_config.sources)} source(s)...")
        for source in params_config.sources:
            source_path = params_config.resolve_source_path(source)
            console.print(f"  {source.prefix}: {source_path}")

        result = generate_params_document(params_config)

        if result.success:
            console.print(
                f"[green]Parameter table generated:[/green] {result.output_path} "
                f"({result.entry_count} parameters)"
            )
        else:
            console.print(f"[red]Error:[/red] {result.error}")
            raise SystemExit(1)

    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1) from e
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1) from e


# =============================================================================
# Drawio Dependency Extractor (Plan 2B: analyzer.logic_dependency integration)
# =============================================================================


@dataclass
class _ChainAdapter:
    """Wraps a real DependencyChain to expose the .root attribute.

    ``analyzer.logic_dependency.DependencyChain`` stores its root node as
    ``.dependency_tree``, but the ``extract_dependencies`` adapter Protocol
    expects ``.root``.  This lightweight wrapper bridges the two without
    modifying the analyzer.
    """

    root: Any  # real DependencyNode (has .name and .children)


def _compute_page_block_ids(page: object, resolver: Resolver) -> set[str]:
    """Return the set of block IDs that will appear on *page*.

    Instrument tags are lowercased; FB instance names are preserved exactly
    as declared in the doc-map.

    Parameters
    ----------
    page : Page
        A doc-map page (has a ``.blocks`` attribute).
    resolver : Resolver
        Resolver that maps block refs to resolved identifiers.

    Returns
    -------
    set[str]
        Block IDs keyed exactly as they will appear in the generated drawio
        XML (i.e. what ``page_block_ids`` must contain for edge filtering).
    """
    ids: set[str] = set()
    for ref in page.blocks:  # type: ignore[attr-defined]
        try:
            resolved = resolver.resolve(ref)
            if resolved.kind == "instrument_tag":
                ids.add(resolved.identifier.lower())
            else:
                ids.add(resolved.identifier)
        except Exception:
            continue
    return ids


# =============================================================================
# Drawio Command
# =============================================================================


@code_group.command("diff")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format",
)
@click.argument("old_path", type=click.Path(exists=True, path_type=Path))
@click.argument("new_path", type=click.Path(exists=True, path_type=Path))
def diff(output_format: str, old_path: Path, new_path: Path) -> None:
    """Semantic diff between two SCL exports (directories or single .s7dcl files).

    Compares what the code means -- blocks, interfaces, statements on the AST --
    so whitespace, comments and TIA re-export formatting never show as changes.
    Exit code: 0 when semantically identical, 1 when anything differs, 2 when an
    export could not be read.
    """
    import json as json_module

    from plc_code.analyzer.block_diff import diff_trees

    report = diff_trees(old_path, new_path)

    if output_format == "json":
        print(
            json_module.dumps(
                {
                    "identical": not report.has_changes,
                    "errors": report.errors,
                    "blocks": [
                        {
                            "name": block.name,
                            "kind": block.kind,
                            "notes": block.notes,
                            "interface": [vars(change) for change in block.interface],
                            "statements": [vars(change) for change in block.statements],
                            "parse_problems": block.parse_problems,
                        }
                        for block in report.blocks
                    ],
                },
                indent=2,
            )
        )
        raise SystemExit(2 if report.errors else (1 if report.has_changes else 0))

    for error in report.errors:
        console_err.print(f"[red]error:[/red] {error}")
    if not report.has_changes:
        console.print("[green]Identical[/green] — no semantic difference.")
        raise SystemExit(0)
    for block in report.blocks:
        marker = {"added": "[green]+[/green]", "removed": "[red]-[/red]"}.get(
            block.kind, "[yellow]~[/yellow]"
        )
        console.print(f"\n{marker} [bold]{block.name}[/bold] ({block.kind})")
        for note in block.notes:
            console.print(f"    {note}")
        for change in block.interface:
            detail = {
                "added": f"+ {change.name} : {change.new}",
                "removed": f"- {change.name} : {change.old}",
                "retyped": f"~ {change.name} : {change.old} -> {change.new}",
                "redefaulted": f"~ {change.name} := {change.old!r} -> {change.new!r}",
                "reattributed": f"~ {change.name} attributes: {change.old} -> {change.new}",
            }[change.kind]
            console.print(f"    [{change.section}] {detail}")
        last_region: str | None = None
        for statement in block.statements:
            if statement.region != last_region:
                console.print(f"    [dim]{statement.region}[/dim]")
                last_region = statement.region
            sign = "+" if statement.kind == "added" else "-"
            style = "green" if statement.kind == "added" else "red"
            console.print(f"      [{style}]{sign} L{statement.line}: {statement.text}[/{style}]")
        for problem in block.parse_problems:
            console_err.print(f"    [yellow]not compared:[/yellow] {problem}")
    changed = sum(1 for b in report.blocks if b.kind == "changed")
    added = sum(1 for b in report.blocks if b.kind == "added")
    removed = sum(1 for b in report.blocks if b.kind == "removed")
    console.print(f"\n{changed} changed, {added} added, {removed} removed.")
    raise SystemExit(2 if report.errors else 1)


@code_group.command("xref")
@click.option(
    "--tags",
    "tags_dir",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Directory holding the PLC tag XML exports",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format",
)
@click.option("--all", "show_all", is_flag=True, help="List every tag, not only the findings")
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
def xref(tags_dir: Path, output_format: str, show_all: bool, path: Path | None) -> None:
    """Cross-reference the tag table against the code.

    Reports the gaps commissioning trips over: an input the code never reads, an
    output it never writes, a declared tag it never touches, and quoted I/O-named
    tags the code uses that no table declares. Exit 1 when there are findings.
    """
    import json as json_module

    from plc_code.analyzer.logic_dependency.tag_parser import parse_tag_directory
    from plc_code.analyzer.tag_xref import cross_reference
    from plc_code.parser import parse_scl_file
    from plc_code.project.discovery import discover_blocks

    diag_console = console_err if output_format == "json" else console
    if path is None:
        try:
            from plc_code.core.config import load_config

            path = load_config().source_path
        except FileNotFoundError:
            diag_console.print("[red]Error:[/red] No plc.yaml found and no path specified.")
            raise SystemExit(2) from None

    blocks = []
    for block_file in [bf.source_path for bf in discover_blocks(path)]:
        try:
            block = parse_scl_file(block_file)
        except Exception as error:
            diag_console.print(f"[yellow]warning:[/yellow] {block_file.name}: {error}")
            continue
        if block is not None and block.name:
            blocks.append(block)
    tags = parse_tag_directory(tags_dir)
    report = cross_reference(blocks, tags)

    if output_format == "json":
        print(
            json_module.dumps(
                {
                    "tags": [
                        {
                            "name": usage.tag.name,
                            "address": usage.tag.address,
                            "direction": usage.tag.direction,
                            "verdict": usage.verdict,
                            "reads": usage.reads,
                            "writes": usage.writes,
                        }
                        for usage in (report.usages if show_all else report.findings)
                    ],
                    "undeclared": report.undeclared,
                },
                indent=2,
            )
        )
        raise SystemExit(1 if (report.findings or report.undeclared) else 0)

    listed = report.usages if show_all else report.findings
    for usage in listed:
        style = {"untouched": "red", "read-only": "yellow", "write-only": "yellow", "used": "green"}[
            usage.verdict
        ]
        sites = ", ".join(f"{block}:{line}" for block, line in (usage.reads + usage.writes)[:4])
        console.print(
            f"  [{style}]{usage.verdict:10}[/{style}] {usage.tag.name}  ({usage.tag.address}, "
            f"{usage.tag.direction})" + (f"  [dim]{sites}[/dim]" if sites else "")
        )
    for name, tag_sites in sorted(report.undeclared.items()):
        where = ", ".join(f"{block}:{line}" for block, line in tag_sites[:4])
        console.print(f"  [red]undeclared[/red] {name}  [dim]{where}[/dim]")
    for problem in report.parse_errors:
        console_err.print(f"  [yellow]not read:[/yellow] {problem}")
    for prefix in report.silent_prefixes:
        console_err.print(
            f"  [yellow]warning:[/yellow] no {prefix}* tag is ever accessed — the part of the "
            "program using them is probably missing from the compared export"
        )
    finding_names = {usage.tag.name for usage in report.findings}
    healthy = sum(1 for usage in report.usages if usage.tag.name not in finding_names)
    console.print(
        f"\n{len(report.usages)} declared, {healthy} healthy, {len(report.findings)} finding(s), "
        f"{len(report.undeclared)} undeclared."
    )
    raise SystemExit(1 if (report.findings or report.undeclared) else 0)


@code_group.command("drawio")
@click.option(
    "--doc-map",
    "doc_map_path",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to doc-map.yaml",
)
@click.option(
    "--xml-tags",
    "xml_tags_dir",
    required=False,
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Directory of TIA Portal XML tag exports",
)
@click.option(
    "--scl",
    "scl_dir",
    required=False,
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Directory of SCL source files (Plan 2)",
)
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Output directory for .drawio files (one per chapter)",
)
@click.option("--chapter", "chapter_filter", default=None, help="Generate only this chapter (by name)")
def drawio_command(
    doc_map_path: Path,
    xml_tags_dir: Path | None,
    scl_dir: Path | None,
    out_dir: Path,
    chapter_filter: str | None,
) -> None:
    """Generate the Control Logic .drawio files from SCL + doc-map.yaml."""
    out_dir.mkdir(parents=True, exist_ok=True)
    docmap = load_docmap(doc_map_path)
    resolver = Resolver(xml_tags_dir=xml_tags_dir, scl_dir=scl_dir)

    chapters = docmap.chapters
    if chapter_filter is not None:
        chapters = [c for c in chapters if c.name == chapter_filter]
        if not chapters:
            click.echo(f"warning: no chapter named '{chapter_filter}' in doc-map", err=True)
            raise click.exceptions.Exit(1)

    # Emit pattern definition pages (front matter) if any fb_rendering uses 'pattern'.
    # Plan 2B: SM sourced from analyzer.state_machine extraction, not hardcoded.
    # Must be called AFTER analyzer_blocks is built (below), so we defer the call.

    # Build analyzer caches once before the chapter loop.
    # These are used by build_dependency_chain to trace I/O tag dependencies.
    # Wrapped in try/except so that synthetic or unparseable SCL never crashes the CLI.
    from plc_code.analyzer.logic_dependency.chain_builder import build_dependency_chain
    from plc_code.analyzer.logic_dependency.tag_parser import parse_tag_directory
    from plc_code.drawio_generator.analyzer_adapter.dependencies import (
        extract_dependencies as _extract_deps,
    )
    from plc_code.parser.parser import parse_scl_file

    analyzer_blocks: list = []
    analyzer_tags = None

    if scl_dir is not None and chapters:
        # Collect the unique source_blocks filenames across all chapters being generated.
        source_paths: set[str] = {src for ch in chapters for src in ch.source_blocks}
        for source in source_paths:
            full = scl_dir / source
            if not full.exists():
                candidates = list(scl_dir.rglob(Path(source).name))
                if candidates:
                    full = candidates[0]
            if full.exists():
                try:
                    analyzer_blocks.append(parse_scl_file(full))
                except Exception as exc:
                    click.echo(f"warning: failed to parse {full}: {exc}", err=True)
        # What the dependency tracers could not read is absent from every chain: say so.
        from plc_code.analyzer.logic_dependency.access_index import access_index

        for analyzer_block in analyzer_blocks:
            for problem in access_index(analyzer_block).parse_errors:
                click.echo(f"warning: {analyzer_block.name}: not traced, {problem}", err=True)

    if xml_tags_dir is not None:
        try:
            analyzer_tags = parse_tag_directory(xml_tags_dir)
        except Exception as exc:
            click.echo(f"warning: failed to load tag directory {xml_tags_dir}: {exc}", err=True)

    # Emit pattern definition pages now that analyzer_blocks is available.
    _emit_pattern_def_pages(docmap, analyzer_blocks, out_dir, scl_dir=scl_dir)

    for chapter in chapters:
        sheets = []
        for idx, page in enumerate(chapter.pages, start=1):
            page_block_ids = _compute_page_block_ids(page, resolver)

            # Build dependency chains via analyzer integration (Plan 2B).
            chains: list[_ChainAdapter] = []
            if analyzer_blocks and analyzer_tags is not None:
                for tag_id in page_block_ids:
                    tag = analyzer_tags.get(tag_id) or analyzer_tags.get(tag_id.upper())
                    if tag is None:
                        # Normal for FB instances — they are not in the tag table.
                        continue
                    try:
                        chain = build_dependency_chain(tag, analyzer_blocks, analyzer_tags)
                    except Exception:
                        chain = None
                    if chain is not None:
                        chains.append(_ChainAdapter(root=chain.dependency_tree))

            page_deps = _extract_deps(chains=chains, page_block_ids=page_block_ids)  # type: ignore[arg-type]
            sheet = build_sheet(
                page=page,
                document=docmap.document,
                resolver=resolver,
                chapter_name=chapter.name,
                section_number=idx,
                fb_rendering=docmap.fb_rendering,
                dependencies=page_deps if page_deps else None,
            )
            sheets.append(sheet)

        if sheets:
            output_file = out_dir / f"{chapter.name.lower()}.drawio"
            write_drawio(sheets, output_file)
            click.echo(f"wrote {output_file} ({len(sheets)} sheets)")


def _emit_pattern_def_pages(
    docmap: DocMap,
    analyzer_blocks: list,
    out_dir: Path,
    scl_dir: Path | None = None,
) -> None:
    """Emit front-matter.drawio with one SM page per pattern FB.

    For each entry in docmap.fb_rendering with style="pattern", locate the
    FB's definition block in analyzer_blocks (already-parsed chapter blocks),
    or — if not found there — search the entire scl_dir tree by filename stem.
    Extract the state machine via analyzer.state_machine.detector.extract_state_machine
    and emit a sheet to front-matter.drawio.  If a pattern FB has no SM, skip
    with a warning.
    """
    from plc_code.analyzer.state_machine.detector import extract_state_machine
    from plc_code.drawio_generator.analyzer_adapter.state_machine import sm_to_protocol_lists
    from plc_code.drawio_generator.state_machine_page import build_state_machine_sheet
    from plc_code.parser.parser import parse_scl_file as _parse_scl

    pattern_sheets = []
    for fb_type, spec in docmap.fb_rendering.items():
        if spec.style != "pattern":
            continue
        # 1. Look in the already-parsed chapter blocks.
        # Block.name may include a leading "_."/underscore-dot library prefix.
        fb_block = next(
            (
                b
                for b in analyzer_blocks
                if getattr(b, "name", None) == fb_type or getattr(b, "name", "").lstrip("_.") == fb_type
            ),
            None,
        )
        # 2. Fallback: rglob the entire scl_dir tree by filename stem.
        if fb_block is None and scl_dir is not None:
            candidates = list(scl_dir.rglob(f"{fb_type}.s7dcl"))
            for candidate in candidates:
                try:
                    parsed = _parse_scl(candidate)
                    name = getattr(parsed, "name", "")
                    if name == fb_type or name.lstrip("_.") == fb_type:
                        fb_block = parsed
                        break
                except Exception:
                    continue
        if fb_block is None:
            click.echo(f"warning: pattern FB '{fb_type}' not found in SCL, skipping", err=True)
            continue
        try:
            sm = extract_state_machine(fb_block)
        except Exception as e:
            click.echo(f"warning: failed to extract SM for '{fb_type}': {e}", err=True)
            continue
        if sm is None:
            click.echo(f"warning: pattern FB '{fb_type}' has no state machine, skipping", err=True)
            continue
        states, transitions = sm_to_protocol_lists(sm)
        sheet = build_state_machine_sheet(
            page_num=spec.definition_page or 4,
            title=fb_type,
            document=docmap.document,
            states=states,
            transitions=transitions,
        )
        pattern_sheets.append(sheet)
    if pattern_sheets:
        out_file = out_dir / "front-matter.drawio"
        write_drawio(pattern_sheets, out_file)
        click.echo(f"wrote {out_file} ({len(pattern_sheets)} pattern definition pages)")


# =============================================================================
# Docs Command
# =============================================================================


@code_group.command()
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None, help="Output directory")
@click.option("--serve", is_flag=True, help="Serve documentation after generation")
@click.option("--port", "-p", type=int, default=8000, help="Port for serving (default: 8000)")
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
def docs(output: Path | None, serve: bool, port: int, path: Path | None) -> None:
    """Generate MkDocs documentation from SCL files.

    If PATH is not specified, uses source path from plc.yaml.
    """
    from plc_code.generator.markdown import MarkdownOptions
    from plc_code.project import DocumentationPipeline, ProjectConfig
    from plc_code.project.config import EfatConfig, ExternalDocs

    # Determine source path
    yaml_config = None
    if path is None:
        try:
            from plc_code.core.config import load_config

            yaml_config = load_config()
            path = yaml_config.source_path
            if output is None:
                output = yaml_config.docs_path
        except FileNotFoundError:
            console.print("[red]Error:[/red] No plc.yaml found and no path specified.")
            raise SystemExit(1) from None

    if output is None:
        output = Path("docs")

    if not path.exists():
        console.print(f"[red]Error:[/red] Source not found: {path}")
        raise SystemExit(1)

    console.print("[bold]Generating documentation[/bold]")
    console.print(f"  Source: {path}")
    console.print(f"  Output: {output}")

    # Create pipeline configuration
    config = ProjectConfig(
        source_dir=path,
        markdown=MarkdownOptions(
            include_changelog=True,
            include_hidden_vars=False,
            include_temp_vars=False,
            include_constants=True,
            show_access_modifiers=True,
        ),
        preserve_hierarchy=True,
        category_from_path=True,
    )
    config.output.output_dir = output
    config.output.create_index = True
    config.output.create_mkdocs_nav = True

    # Propagate plc.yaml metadata and optional features
    if yaml_config is not None:
        config.project_name = yaml_config.name
        config.project_code = yaml_config.code
        config.project_version = yaml_config.version
        config.project_root = yaml_config.root_path
        config.external_docs = [
            ExternalDocs(source=e.source, dest=e.dest, title=e.title) for e in yaml_config.external_docs
        ]
        if yaml_config.efat.test_dir:
            config.efat = EfatConfig(
                test_dir=Path(yaml_config.efat.test_dir),
                output=yaml_config.efat.output,
            )

    # Run the pipeline
    pipeline = DocumentationPipeline(config)
    results = pipeline.run()

    # Print summary
    console.print()
    console.print("[bold]Summary[/bold]")
    console.print(f"  Total: {pipeline.stats.total}")
    console.print(f"  [green]Successful: {pipeline.stats.successful}[/green]")
    if pipeline.stats.failed > 0:
        console.print(f"  [red]Failed: {pipeline.stats.failed}[/red]")

    # Print by type
    if pipeline.stats.by_type:
        console.print()
        console.print("[bold]By Block Type[/bold]")
        for block_type, count in sorted(pipeline.stats.by_type.items()):
            console.print(f"  {block_type}: {count}")

    # Print failed files
    failed = [r for r in results if not r.success]
    if failed:
        console.print()
        console.print("[bold red]Failed files:[/bold red]")
        for result in failed[:10]:  # Show first 10
            console.print(f"  [red]•[/red] {result.block_file.name}: {result.error}")
        if len(failed) > 10:
            console.print(f"  ... and {len(failed) - 10} more")

    console.print()
    console.print(f"[green]Documentation generated at: {output}[/green]")

    # Serve if requested
    if serve:
        import os
        import subprocess

        console.print()
        console.print(f"[bold]Starting documentation server on port {port}...[/bold]")
        console.print(f"Open http://localhost:{port} in your browser")
        console.print("Press Ctrl+C to stop")

        # Determine working directory (project root with mkdocs.yml)
        cwd = Path.cwd()

        # Find mkdocs executable
        mkdocs_cmd = None

        # 1. Try project's .venv
        venv_mkdocs = cwd / ".venv" / "bin" / "mkdocs"
        if venv_mkdocs.exists():
            mkdocs_cmd = [str(venv_mkdocs)]

        # 2. Try uv run mkdocs
        if mkdocs_cmd is None:
            uv_locations = [
                os.path.expanduser("~/.local/bin/uv"),
                os.path.expanduser("~/.cargo/bin/uv"),
                "/usr/local/bin/uv",
                "/usr/bin/uv",
            ]
            for uv_path in uv_locations:
                if os.path.exists(uv_path):
                    mkdocs_cmd = [uv_path, "run", "mkdocs"]
                    break

        # 3. Fall back to system mkdocs
        if mkdocs_cmd is None:
            mkdocs_cmd = ["mkdocs"]

        try:
            subprocess.run(
                mkdocs_cmd + ["serve", "--dev-addr", f"0.0.0.0:{port}"],
                cwd=cwd,
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]Server stopped.[/yellow]")
        except FileNotFoundError:
            console.print("[red]Error:[/red] mkdocs not found. Install with: uv add --dev mkdocs-material")


# =============================================================================
# Web Command (Unified PLC Analysis Server)
# =============================================================================


def _build_mkdocs_site() -> bool:
    """Build MkDocs site. Returns True on success."""
    import os
    import subprocess

    cwd = Path.cwd()

    if not (cwd / "mkdocs.yml").exists():
        console.print("[yellow]Warning:[/yellow] No mkdocs.yml found, skipping docs build.")
        return False

    # Find mkdocs executable
    mkdocs_cmd: list[str] | None = None

    venv_mkdocs = cwd / ".venv" / "bin" / "mkdocs"
    if venv_mkdocs.exists():
        mkdocs_cmd = [str(venv_mkdocs)]

    if mkdocs_cmd is None:
        uv_locations = [
            os.path.expanduser("~/.local/bin/uv"),
            os.path.expanduser("~/.cargo/bin/uv"),
            "/usr/local/bin/uv",
            "/usr/bin/uv",
        ]
        for uv_path in uv_locations:
            if os.path.exists(uv_path):
                mkdocs_cmd = [uv_path, "run", "mkdocs"]
                break

    if mkdocs_cmd is None:
        mkdocs_cmd = ["mkdocs"]

    console.print("Building documentation site...")
    try:
        result = subprocess.run(
            mkdocs_cmd + ["build"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            console.print("[green]Documentation built successfully.[/green]")
            return True
        else:
            console.print(f"[red]mkdocs build failed:[/red] {result.stderr.strip()}")
            return False
    except FileNotFoundError:
        console.print("[red]Error:[/red] mkdocs not found. Install with: uv add --dev mkdocs-material")
        return False


@code_group.command()
@click.option("--port", "-p", type=int, default=8080, help="Port to run server on")
@click.option(
    "--host",
    "-h",
    default="127.0.0.1",
    help="Host to bind to (pass 0.0.0.0 to expose the server on the network)",
)
@click.option(
    "--docs-dir",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to pre-built MkDocs site directory (default: auto-detect site/)",
)
@click.option("--build-docs", is_flag=True, help="Build MkDocs documentation before serving")
@click.option("--open-browser", is_flag=True, help="Open browser automatically (disabled by default)")
@click.option("--reload", is_flag=True, help="Enable auto-reload for development")
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
def web(
    port: int,
    host: str,
    docs_dir: Path | None,
    build_docs: bool,
    open_browser: bool,
    reload: bool,
    path: Path | None,
) -> None:
    """Start the PLC Analysis Server.

    Launches a unified web server with:
    - Landing page at /
    - Program documentation at /docs/ (MkDocs, when available)
    - I/O Tag Dependency Explorer at /explorer/
    - REST API at /api/

    If PATH is not specified, uses source path from plc.yaml.
    Documentation is auto-detected from site/ in the current directory.

    Examples:
        plc code web                    # Start on localhost:8080
        plc code web --build-docs       # Build docs first, then serve
        plc code web --port 3000        # Custom port
        plc code web /path/to/plc-program  # Specify source path
    """
    try:
        import uvicorn
    except ImportError:
        console.print("[red]Error:[/red] uvicorn not installed.")
        console.print("Install with: uv add 'uvicorn[standard]' fastapi")
        raise SystemExit(1) from None

    # Determine source path and project name
    project_name: str | None = None
    if path is None:
        try:
            from plc_code.core.config import load_config

            config = load_config()
            path = config.source_path
            project_name = config.name
        except FileNotFoundError:
            # Will be configured via web UI
            pass

    # Build docs if requested
    if build_docs:
        _build_mkdocs_site()

    # Determine docs site path
    if docs_dir is None:
        cwd = Path.cwd()
        site_dir = cwd / "site"
        if site_dir.exists() and (site_dir / "index.html").exists():
            docs_dir = site_dir

    # Set up the app
    from plc_code.web import create_app

    create_app(source_path=path, docs_site_path=docs_dir, project_name=project_name)

    if path:
        console.print(f"[green]Source path:[/green] {path}")

    console.print("[bold]Starting PLC Analysis Server[/bold]")
    console.print(f"Server: http://{host}:{port}")

    if docs_dir:
        console.print(f"  [green]Documentation:[/green] http://{host}:{port}/docs/")
    else:
        console.print("  [dim]Documentation: not available (run 'plc code docs && mkdocs build')[/dim]")
    console.print(f"  [green]I/O Explorer:[/green]  http://{host}:{port}/explorer/")

    # Show sim URL if plc-sim is installed
    try:
        import plc_sim  # noqa: F401

        console.print(f"  [green]Simulation:[/green]   http://{host}:{port}/sim/")
    except ImportError:
        pass

    # Show access URL for remote access
    if host == "0.0.0.0":
        import socket

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            console.print(f"\n[green]Network access:[/green] http://{local_ip}:{port}")
        except Exception:
            console.print("[dim]Access from network using this device's IP address[/dim]")

    # Open browser (only if explicitly requested)
    if open_browser:
        import threading
        import time
        import webbrowser

        def do_open_browser() -> None:
            time.sleep(1)  # Wait for server to start
            webbrowser.open(f"http://127.0.0.1:{port}")

        threading.Thread(target=do_open_browser, daemon=True).start()

    # Run server
    uvicorn.run(
        "plc_code.web:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


# =============================================================================
# Trace Command (Logic Dependency Analysis)
# =============================================================================


@code_group.command()
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["text", "json", "mermaid"]),
    default="text",
    help="Output format",
)
@click.option("--block", "-b", "block_name", default=None, help="Analyze specific block")
@click.option("--output", "-o", "output_var", default=None, help="Analyze specific output variable")
@click.option(
    "--simplified",
    is_flag=True,
    help="Generate simplified diagram (inputs to outputs only)",
)
@click.option("--no-expand", is_flag=True, help="Don't expand intermediate state variables")
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
def trace(
    output_format: str,
    block_name: str | None,
    output_var: str | None,
    simplified: bool,
    no_expand: bool,
    path: Path | None,
) -> None:
    """Analyze logic dependencies between outputs and inputs.

    Traces how output variables depend on input variables, state variables,
    and global data blocks. Generates dependency trees and logic diagrams.

    If PATH is not specified, uses source path from plc.yaml.

    Examples:
        plc code trace                      # Analyze all blocks
        plc code trace -b MyBlock           # Specific block
        plc code trace -o alarmState        # Specific output variable
        plc code trace -f mermaid -o deps.md  # Export as Mermaid diagram
    """
    from plc_code.analyzer.logic_dependency import (
        build_all_output_trees,
        extract_dependencies,
    )
    from plc_code.parser import parse_scl_file
    from plc_code.project.discovery import discover_blocks

    # Diagnostics must not share the stream the JSON payload is written to, or
    # `-f json` emits an unparseable document whenever anything is reported.
    diag_console = console_err if output_format == "json" else console

    # Determine source path
    if path is None:
        try:
            from plc_code.core.config import load_config

            config = load_config()
            path = config.source_path
        except FileNotFoundError:
            diag_console.print("[red]Error:[/red] No plc.yaml found and no path specified.")
            diag_console.print("Run 'plc init' or specify a path: plc code trace <path>")
            raise SystemExit(1) from None

    if not path.exists():
        diag_console.print(f"[red]Error:[/red] Source not found: {path}")
        raise SystemExit(1)

    try:
        # Discover blocks
        if path.is_file():
            block_files = [path]
        else:
            blocks_found = discover_blocks(path)
            block_files = [bf.source_path for bf in blocks_found]

        if not block_files:
            diag_console.print("[yellow]No .s7dcl files found to analyze.[/yellow]")
            raise SystemExit(1)

        # Filter by block name if specified
        if block_name:
            matching = [bf for bf in block_files if Path(bf).stem.lower() == block_name.lower()]
            if not matching:
                diag_console.print(f"[red]Error:[/red] Block '{block_name}' not found.")
                raise SystemExit(1)
            block_files = matching

        diag_console.print(f"Analyzing {len(block_files)} block(s)...", style="dim")

        # Analyze each block
        all_results: dict[str, dict] = {}

        for block_path in block_files:
            try:
                block = parse_scl_file(Path(block_path))

                # Extract dependencies
                deps = extract_dependencies(block)
                for problem in deps.parse_errors:
                    diag_console.print(f"[yellow]{block.name}:[/yellow] not traced, {problem}")

                # Build output trees
                output_trees = build_all_output_trees(deps)

                if output_trees:
                    all_results[block.name] = {
                        "source_file": str(block_path),
                        "trees": output_trees,
                        "deps": deps,
                    }

            except Exception as e:
                diag_console.print(f"[yellow]Warning:[/yellow] Failed to analyze {block_path}: {e}")

        if not all_results:
            diag_console.print("[yellow]No output dependencies found.[/yellow]")
            raise SystemExit(0)

        # Generate output based on format
        if output_format == "json":
            _output_json(all_results, output_var)
        elif output_format == "mermaid":
            _output_mermaid(all_results, output_var, simplified)
        else:
            _output_text(all_results, output_var)

    except SystemExit:
        raise
    except Exception as e:
        diag_console.print(f"[red]Error during analysis:[/red] {e}")
        import sys
        import traceback

        # Default is stdout, which would land inside the JSON payload.
        traceback.print_exc(file=sys.stderr)
        raise SystemExit(1) from e


def _output_text(results: dict, output_var: str | None) -> None:
    """Output analysis results as text."""
    from plc_code.analyzer.logic_dependency import get_dependency_summary

    for block_name, data in sorted(results.items()):
        console.print(f"\n[bold]{block_name}[/bold]")
        console.print(f"  Source: {data['source_file']}")

        trees = data["trees"]
        for output_name, tree in sorted(trees.items()):
            if output_var and output_name.lower() != output_var.lower():
                continue

            console.print(f"\n  [cyan]Output: {output_name}[/cyan]")
            summary = get_dependency_summary(tree)

            if summary["inputs"]:
                console.print(f"    Inputs: {', '.join(summary['inputs'])}")
            if summary["states"]:
                console.print(f"    States: {', '.join(summary['states'])}")
            if summary["constants"]:
                console.print(f"    Constants: {', '.join(summary['constants'])}")
            if summary["global_dbs"]:
                # Shorten global DB names
                short_dbs = [db.replace('"', "").split(".")[-1] for db in summary["global_dbs"]]
                console.print(f"    Global DBs: {', '.join(short_dbs)}")
            if summary["intermediate"]:
                console.print(f"    Intermediate vars: {', '.join(summary['intermediate'])}")


def _output_json(results: dict, output_var: str | None) -> None:
    """Output analysis results as JSON."""
    from plc_code.analyzer.logic_dependency import get_dependency_summary

    output_data = {}

    for block_name, data in results.items():
        block_data = {
            "source_file": data["source_file"],
            "outputs": {},
        }

        trees = data["trees"]
        for output_name, tree in trees.items():
            if output_var and output_name.lower() != output_var.lower():
                continue

            summary = get_dependency_summary(tree)
            block_data["outputs"][output_name] = {
                "inputs": summary["inputs"],
                "states": summary["states"],
                "constants": summary["constants"],
                "global_dbs": summary["global_dbs"],
                "intermediate_vars": summary["intermediate"],
                "source_location": {
                    "file": tree.output.source_location.file_path,
                    "line": tree.output.source_location.line_number,
                },
            }

        if block_data["outputs"]:
            output_data[block_name] = block_data

    print(json.dumps(output_data, indent=2))


def _output_mermaid(results: dict, output_var: str | None, simplified: bool) -> None:
    """Output analysis results as Mermaid diagrams."""
    from plc_code.analyzer.logic_dependency import (
        generate_block_summary_diagram,
        generate_dependency_diagram,
        generate_simplified_diagram,
    )

    diagrams: list[str] = []

    for block_name, data in sorted(results.items()):
        trees = data["trees"]

        if output_var:
            # Single output diagram
            for output_name, tree in trees.items():
                if output_name.lower() == output_var.lower():
                    diagram = (
                        generate_simplified_diagram(tree) if simplified else generate_dependency_diagram(tree)
                    )
                    diagrams.append(f"## {block_name}: {output_name}\n\n```mermaid\n{diagram}\n```")
        else:
            # All outputs for block
            if simplified:
                # Summary diagram
                diagram = generate_block_summary_diagram(block_name, trees)
                diagrams.append(f"## {block_name}\n\n```mermaid\n{diagram}\n```")
            else:
                # Individual diagrams for each output
                for output_name, tree in sorted(trees.items()):
                    diagram = generate_dependency_diagram(tree)
                    diagrams.append(f"## {block_name}: {output_name}\n\n```mermaid\n{diagram}\n```")

    print("\n\n".join(diagrams))


# =============================================================================
# Test Command
# =============================================================================


@code_group.command()
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
@click.option(
    "--coverage",
    is_flag=True,
    help="Measure SCL line coverage: which lines of each block the tests executed",
)
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
def test(verbose: bool, coverage: bool, path: Path | None) -> None:
    """Run unit tests for PLC blocks.

    If PATH is not specified, uses test directories from plc.yaml. With
    --coverage, every block compiled by the tests is instrumented and a per-block
    SCL line-coverage table is printed after the run -- the qualification
    argument a FAT wants: not "the block has a test" but "these lines ran".
    """
    # Determine test directories
    if path is not None:
        test_dirs = [path]
    else:
        try:
            from plc_code.core.config import load_config

            config = load_config()
            test_dirs = config.get_test_dirs()
        except FileNotFoundError:
            test_dirs = [Path("test-cases")]

    if not any(d.exists() for d in test_dirs):
        console.print("[yellow]No test directories found.[/yellow]")
        raise SystemExit(0)

    console.print(f"Running tests from: {', '.join(str(d) for d in test_dirs if d.exists())}")

    import json as json_module
    import os
    import subprocess
    import tempfile

    coverage_file: Path | None = None
    env = os.environ.copy()
    if coverage:
        descriptor, name = tempfile.mkstemp(suffix=".json", prefix="scl-coverage-")
        os.close(descriptor)
        coverage_file = Path(name)
        coverage_file.write_text("{}", encoding="utf-8")
        env["PLC_SCL_COVERAGE"] = str(coverage_file)

    test_paths = [str(d) for d in test_dirs if d.exists()]
    pytest_args = test_paths + (["-v"] if verbose else [])
    cwd = Path.cwd()

    command: list[str] | None = None
    venv_pytest = cwd / ".venv" / "bin" / "pytest"
    if venv_pytest.exists():
        command = [str(venv_pytest)]
    elif (cwd / "pyproject.toml").exists():
        for uv_path in (
            os.path.expanduser("~/.local/bin/uv"),
            os.path.expanduser("~/.cargo/bin/uv"),
            "/usr/local/bin/uv",
            "/usr/bin/uv",
        ):
            if os.path.exists(uv_path):
                command = [uv_path, "run", "pytest"]
                break
    if command is None:
        console.print("[red]Error:[/red] pytest not found.")
        console.print("Run 'uv sync' from the project root to set up your project.")
        raise SystemExit(1)

    result = subprocess.run(command + pytest_args, cwd=cwd, env=env)

    if coverage_file is not None:
        # Each process wrote its own `<file>.<pid>` shard (safe under xdist);
        # merge them here.
        data: dict[str, Any] = {}
        shards = [coverage_file, *coverage_file.parent.glob(coverage_file.name + ".*")]
        for shard in shards:
            try:
                part = json_module.loads(shard.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            finally:
                shard.unlink(missing_ok=True)
            for block, entry in part.items():
                merged = data.setdefault(block, {"executable": [], "touched": []})
                merged["executable"] = sorted(set(merged["executable"]) | set(entry.get("executable", [])))
                merged["touched"] = sorted(set(merged["touched"]) | set(entry.get("touched", [])))
        _print_scl_coverage(data)

    raise SystemExit(result.returncode)


def _line_ranges(lines: list[int]) -> str:
    """``[3,4,5,9]`` -> ``"3-5, 9"``, the way a reader scans missing lines."""
    ranges: list[str] = []
    start = previous = None
    for line in lines:
        if start is None:
            start = previous = line
        elif previous is not None and line == previous + 1:
            previous = line
        else:
            ranges.append(f"{start}-{previous}" if start != previous else f"{start}")
            start = previous = line
    if start is not None:
        ranges.append(f"{start}-{previous}" if start != previous else f"{start}")
    return ", ".join(ranges)


def _print_scl_coverage(data: dict[str, Any]) -> None:
    """The per-block SCL line-coverage table `plc code test --coverage` prints."""
    if not data:
        console.print("\n[yellow]No SCL coverage recorded[/yellow] — no block was compiled by the tests.")
        return
    console.print("\n[bold]SCL line coverage[/bold]")
    total_executable = total_touched = 0
    for block in sorted(data):
        executable = set(data[block].get("executable", []))
        touched = set(data[block].get("touched", [])) & executable
        if not executable:
            continue
        total_executable += len(executable)
        total_touched += len(touched)
        percent = 100.0 * len(touched) / len(executable)
        missing = sorted(executable - touched)
        style = "green" if percent == 100.0 else ("yellow" if percent >= 75.0 else "red")
        line = f"  [{style}]{percent:6.1f}%[/{style}]  {block}  ({len(touched)}/{len(executable)} lines)"
        if missing:
            line += f"  [dim]missing: {_line_ranges(missing)}[/dim]"
        console.print(line)
    if total_executable:
        overall = 100.0 * total_touched / total_executable
        console.print(f"  [bold]{overall:6.1f}%  overall ({total_touched}/{total_executable} lines)[/bold]")


# =============================================================================
# Legacy Entry Point (for backwards compatibility)
# =============================================================================


def main() -> int:
    """Legacy entry point for scl-docs CLI (deprecated).

    This function provides backwards compatibility with the old argparse-based CLI.
    New code should use the Click-based 'cli' entry point.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for errors).
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="scl-docs",
        description=(
            "[DEPRECATED] Use 'plc' command instead. "
            "Generate MkDocs documentation from TIA Portal V21 SCL exports"
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Generate command
    gen_parser = subparsers.add_parser("generate", help="Generate MkDocs documentation")
    gen_parser.add_argument("source", type=Path, help="Source directory")
    gen_parser.add_argument("--output", "-o", type=Path, default=Path("docs"))

    # Lint command
    lint_parser = subparsers.add_parser("lint", help="Run code quality analysis")
    lint_parser.add_argument("source", type=Path, help="Source directory or file")
    lint_parser.add_argument("--format", "-f", choices=["text", "json"], default="text")
    lint_parser.add_argument("--no-color", action="store_true")

    args = parser.parse_args()

    console.print("[yellow]Warning:[/yellow] scl-docs is deprecated. Use 'plc' command instead.")

    if args.command == "generate":
        console.print("Use: plc docs <path>")
        return 0
    elif args.command == "lint":
        # Redirect to new CLI
        sys.argv = ["plc", "lint", str(args.source)]
        if args.format == "json":
            sys.argv.extend(["--format", "json"])
        if args.no_color:
            sys.argv.append("--no-color")
        cli()
        return 0

    return 1


if __name__ == "__main__":
    cli()
