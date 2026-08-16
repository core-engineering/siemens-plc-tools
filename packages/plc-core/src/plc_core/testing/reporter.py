"""Test result reporting: Rich console summary, JUnit XML, and Markdown report."""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement

from rich.console import Console
from rich.table import Table

from plc_core.testing.models import Outcome, ScenarioResult, StepResult, TestSuiteResult


def _extract_test_number(source_file: Path | None) -> str:
    """Extract a display test number from the scenario filename.

    Examples:
        EFAT_001_lamp_test.yaml  -> EFAT-001
        EFAT_012_02_oil_temp.yaml -> EFAT-012-02
        test_something.yaml      -> ""
    """
    if not source_file:
        return ""
    m = re.match(r"EFAT_(\d{3})(?:_(\d{2}))?", source_file.stem)
    if not m:
        return ""
    number = m.group(1)
    sub = m.group(2)
    return f"EFAT-{number}-{sub}" if sub else f"EFAT-{number}"


# ------------------------------------------------------------------
# Console reporting
# ------------------------------------------------------------------


def print_step_result(console: Console, index: int, result: StepResult) -> None:
    """Print a single step result line."""
    icon_map = {
        Outcome.PASSED: "[green]PASS[/green]",
        Outcome.WARNING: "[yellow]WARN[/yellow]",
        Outcome.FAILED: "[red]FAIL[/red]",
        Outcome.ERROR: "[red]ERR [/red]",
        Outcome.SKIPPED: "[yellow]SKIP[/yellow]",
    }
    icon = icon_map.get(result.outcome, "[dim]???[/dim]")
    desc = result.description or result.step_type
    console.print(f"  [{icon}]  {index + 1}. {desc:<50s} {result.duration_s:.2f}s")


def print_scenario_result(console: Console, result: ScenarioResult) -> None:
    """Print scenario summary line."""
    warn_suffix = ""
    if result.steps_warned:
        warn_suffix = f", [yellow]{result.steps_warned} warning(s)[/yellow]"
    if result.skipped:
        reason = result.skip_reason or "no reason given"
        console.print(f"  [yellow]SKIPPED[/yellow]  {reason}")
    elif result.passed:
        console.print(
            f"  [green]PASSED[/green]  "
            f"{result.steps_passed}/{result.total_steps} steps"
            f"{warn_suffix} "
            f"({result.duration_s:.2f}s)"
        )
    else:
        console.print(
            f"  [red]FAILED[/red]  "
            f"{result.steps_passed}/{result.total_steps} steps passed, "
            f"{result.steps_failed} failed"
            f"{warn_suffix} "
            f"({result.duration_s:.2f}s)"
        )


def print_suite_summary(console: Console, suite: TestSuiteResult) -> None:
    """Print a summary table for the entire test suite."""
    console.print()

    table = Table(title="Integration Test Results", show_lines=True)
    table.add_column("Test #", style="cyan")
    table.add_column("Scenario", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Steps", justify="center")
    table.add_column("Duration", justify="right")

    for sr in suite.scenario_results:
        test_num = _extract_test_number(sr.source_file)
        if sr.skipped:
            status = "[yellow]SKIP[/yellow]"
            steps = "-"
        else:
            status = "[green]PASS[/green]" if sr.passed else "[red]FAIL[/red]"
            steps = f"{sr.steps_passed}/{sr.total_steps}"
            if sr.steps_warned:
                steps += f" ([yellow]{sr.steps_warned}W[/yellow])"
        duration = f"{sr.duration_s:.2f}s"
        table.add_row(test_num, sr.name, status, steps, duration)

    console.print(table)

    # Overall summary
    total = suite.total_scenarios
    passed = suite.scenarios_passed
    failed = suite.scenarios_failed
    skipped = suite.scenarios_skipped
    skip_suffix = f", {skipped} skipped" if skipped else ""

    if suite.overall_success:
        if skipped:
            console.print(
                f"\n[bold green]{passed}/{total} scenario(s) passed[/bold green]{skip_suffix} "
                f"({suite.total_duration_s:.2f}s)"
            )
        else:
            console.print(
                f"\n[bold green]All {total} scenario(s) passed[/bold green] "
                f"({suite.total_duration_s:.2f}s)"
            )
    else:
        console.print(
            f"\n[bold red]{failed}/{total} scenario(s) failed[/bold red]{skip_suffix} "
            f"({suite.total_duration_s:.2f}s)"
        )


# ------------------------------------------------------------------
# JUnit XML export
# ------------------------------------------------------------------


def generate_junit_xml(suite: TestSuiteResult, output_path: Path) -> None:
    """Generate JUnit XML report for CI/CD integration.

    Parameters
    ----------
    suite : TestSuiteResult
        Test execution results.
    output_path : Path
        Path to write the XML file.
    """
    testsuites = Element("testsuites")
    testsuites.set("tests", str(sum(s.total_steps for s in suite.scenario_results)))
    testsuites.set(
        "failures",
        str(sum(s.steps_failed for s in suite.scenario_results)),
    )
    testsuites.set("time", f"{suite.total_duration_s:.3f}")

    for scenario in suite.scenario_results:
        testsuite = SubElement(testsuites, "testsuite")
        testsuite.set("name", scenario.name)
        testsuite.set("tests", str(scenario.total_steps or (1 if scenario.skipped else 0)))
        testsuite.set("failures", str(scenario.steps_failed))
        testsuite.set("time", f"{scenario.duration_s:.3f}")
        if scenario.source_file:
            testsuite.set("file", str(scenario.source_file))

        if scenario.skipped:
            # A scenario-level skip never runs any steps, so there is
            # nothing in step_results to report — synthesize one
            # testcase so CI dashboards show the whole file as skipped
            # rather than an empty, zero-test suite.
            testcase = SubElement(testsuite, "testcase")
            testcase.set("name", scenario.name)
            testcase.set("classname", scenario.name)
            testcase.set("time", f"{scenario.duration_s:.3f}")
            skipped_el = SubElement(testcase, "skipped")
            skipped_el.set("message", scenario.skip_reason or "no reason given")
            continue

        for step in scenario.step_results:
            testcase = SubElement(testsuite, "testcase")
            testcase.set(
                "name",
                step.description or f"Step {step.step_index + 1}: {step.step_type}",
            )
            testcase.set("classname", scenario.name)
            testcase.set("time", f"{step.duration_s:.3f}")

            if step.outcome == Outcome.FAILED:
                failure = SubElement(testcase, "failure")
                failure.set("message", step.error_message or "Assertion failed")
                failure.set("type", "AssertionError")
                # Build detail text
                detail_lines: list[str] = []
                if step.error_message:
                    detail_lines.append(step.error_message)
                if step.expected_values:
                    detail_lines.append(f"Expected: {step.expected_values}")
                if step.actual_values:
                    detail_lines.append(f"Actual: {step.actual_values}")
                failure.text = "\n".join(detail_lines)

            elif step.outcome == Outcome.ERROR:
                error = SubElement(testcase, "error")
                error.set("message", step.error_message or "Execution error")
                error.set("type", "RuntimeError")
                if step.error_message:
                    error.text = step.error_message

            elif step.outcome == Outcome.WARNING:
                system_out = SubElement(testcase, "system-out")
                system_out.text = f"WARNING: {step.error_message or 'Timing jitter detected'}"

            elif step.outcome == Outcome.SKIPPED:
                skipped = SubElement(testcase, "skipped")
                skipped.set("message", "Skipped due to previous failure")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree = ElementTree(testsuites)
    tree.write(str(output_path), encoding="unicode", xml_declaration=True)


# ------------------------------------------------------------------
# Markdown report
# ------------------------------------------------------------------


@dataclass
class ReportMetadata:
    """Metadata for the integration test report."""

    title: str = "Integration Test Report"
    subtitle: str = ""
    project_code: str = ""
    endpoint: str = ""
    server_name: str = ""
    tag_count: int = 0


def generate_markdown_report(
    suite: TestSuiteResult,
    output_path: Path,
    metadata: ReportMetadata | None = None,
) -> Path:
    """Generate a Markdown integration test report with Eisvogel front matter.

    Parameters
    ----------
    suite : TestSuiteResult
        Test execution results.
    output_path : Path
        Path to write the markdown file.
    metadata : ReportMetadata | None
        Optional report metadata. Defaults are used if not provided.

    Returns
    -------
    Path
        The path to the generated markdown file.
    """
    meta = metadata or ReportMetadata()
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    datetime_str = now.strftime("%Y-%m-%d %H:%M:%S")

    lines: list[str] = []

    # --- YAML front matter (Eisvogel) ---
    lines.append("---")
    lines.append(f'title: "{meta.title}"')
    lines.append(f'subtitle: "{meta.subtitle}"')
    lines.append(f"date: {date_str}")
    lines.append("toc: true")
    lines.append("titlepage: true")
    lines.append('titlepage-color: "FFFFFF"')
    lines.append('titlepage-text-color: "FFFFFF"')
    lines.append('titlepage-rule-color: "435488"')
    lines.append("titlepage-rule-height: 0")
    lines.append('titlepage-background: "Images/first-page.pdf"')
    lines.append('page-background: ""')
    lines.append('caption-justification: "centering"')
    lines.append("toc-own-page: false")
    lines.append("header-includes:")
    lines.append("  - \\usepackage{booktabs}")
    lines.append("  - \\renewcommand{\\arraystretch}{1.3}")
    lines.append("  - \\setlength{\\tabcolsep}{10pt}")
    lines.append("---")
    lines.append("")

    # --- Revision table ---
    lines.append("# Revisions")
    lines.append("")
    lines.append("| Revision | Date       | Description          | Prepared By | Checked By | Approved By |")
    lines.append("| -------- | ---------- | -------------------- | ----------- | ---------- | ----------- |")
    lines.append(  # noqa: E501  (markdown table row, column alignment must stay)
        f"| v1.0.0   | {now.strftime('%d/%m/%Y')} | Auto-generated       "
        "|             |            |             |"
    )
    lines.append("")
    lines.append(": Revision table")
    lines.append("")
    lines.append("\\clearpage")
    lines.append("")

    # --- Introduction ---
    lines.append("# Introduction")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append(
        "This report presents the results of the automated integration tests "
        "executed against the PLC simulation environment via OPC UA."
    )
    lines.append("")
    lines.append("## Test Environment")
    lines.append("")
    if meta.endpoint:
        lines.append(f"- **PLC Endpoint:** `{meta.endpoint}`")
    if meta.server_name:
        lines.append(f"- **Server:** {meta.server_name}")
    lines.append(f"- **Date:** {datetime_str}")
    if meta.tag_count:
        lines.append(f"- **Tag cache:** {meta.tag_count} tags")
    lines.append("")
    lines.append("\\clearpage")
    lines.append("")

    # --- Summary ---
    lines.append("# Summary")
    lines.append("")

    overall = "PASS" if suite.overall_success else "FAIL"
    lines.append(
        f"**Overall Result: {overall}** --- "
        f"{suite.scenarios_passed}/{suite.total_scenarios} scenario(s) passed "
        f"({suite.total_duration_s:.2f}s)"
    )
    lines.append("")

    lines.append("| Test # | Scenario | Status | Steps | Duration |")
    lines.append("| ------ | -------- | ------ | ----- | -------- |")

    for sr in suite.scenario_results:
        test_num = _extract_test_number(sr.source_file)
        if sr.skipped:
            status, steps = "SKIP", "-"
        else:
            status = "PASS" if sr.passed else "FAIL"
            steps = f"{sr.steps_passed}/{sr.total_steps}"
        duration = f"{sr.duration_s:.2f}s"
        lines.append(f"| {test_num} | {sr.name} | {status} | {steps} | {duration} |")

    lines.append("")
    lines.append(": Test summary")
    lines.append("")
    lines.append("\\clearpage")
    lines.append("")

    # --- Per-scenario details ---
    lines.append("# Test Results")
    lines.append("")

    for sr in suite.scenario_results:
        lines.append(f"## {sr.name}")
        lines.append("")

        if sr.source_file:
            lines.append(f"**Source:** `{sr.source_file.name}`")
            lines.append("")

        if sr.skipped:
            lines.append(f"**Result: SKIP** --- {sr.skip_reason or 'no reason given'}")
            lines.append("")
            continue

        status = "PASS" if sr.passed else "FAIL"
        lines.append(
            f"**Result: {status}** --- "
            f"{sr.steps_passed}/{sr.total_steps} steps "
            f"({sr.duration_s:.2f}s)"
        )
        lines.append("")

        # Step table
        lines.append("| # | Step | Description | Status | Duration |")
        lines.append("| - | ---- | ----------- | ------ | -------- |")

        for step in sr.step_results:
            step_num = step.step_index + 1
            step_type = step.step_type
            desc = step.description or "-"
            step_status = _outcome_label(step.outcome)
            duration = f"{step.duration_s:.2f}s"
            lines.append(f"| {step_num} | {step_type} | {desc} | {step_status} | {duration} |")

        lines.append("")
        lines.append(f": {sr.name} — step results")
        lines.append("")

        # Warning step details
        warned_steps = [s for s in sr.step_results if s.outcome == Outcome.WARNING]
        if warned_steps:
            lines.append("### Warnings")
            lines.append("")
            for step in warned_steps:
                lines.append(f"**Step {step.step_index + 1}: {step.description or step.step_type}**")
                lines.append("")
                if step.error_message:
                    lines.append(f"- **Warning:** {step.error_message}")
                lines.append("")

        # Failed step details
        failed_steps = [s for s in sr.step_results if s.failed]
        if failed_steps:
            lines.append("### Failures")
            lines.append("")
            for step in failed_steps:
                lines.append(f"**Step {step.step_index + 1}: {step.description or step.step_type}**")
                lines.append("")
                if step.error_message:
                    lines.append(f"- **Error:** {step.error_message}")
                if step.expected_values:
                    for path, val in step.expected_values.items():
                        actual = step.actual_values.get(path, "?")
                        lines.append(f"- `{path}`: expected `{val!r}`, got `{actual!r}`")
                lines.append("")

        if sr.error_message:
            lines.append(f"> **Error:** {sr.error_message}")
            lines.append("")

        lines.append("\\clearpage")
        lines.append("")

    # --- Conclusion ---
    lines.append("# Conclusion")
    lines.append("")
    if suite.overall_success:
        lines.append(
            f"All {suite.total_scenarios} test scenario(s) **passed** successfully. "
            f"Total execution time: {suite.total_duration_s:.2f}s."
        )
    else:
        lines.append(
            f"{suite.scenarios_failed}/{suite.total_scenarios} test scenario(s) **failed**. "
            f"Total execution time: {suite.total_duration_s:.2f}s. "
            "See individual scenario sections for failure details."
        )
    lines.append("")

    # Write file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def _outcome_label(outcome: Outcome) -> str:
    """Plain-text label for a step outcome."""
    return {
        Outcome.PASSED: "PASS",
        Outcome.WARNING: "WARN",
        Outcome.FAILED: "FAIL",
        Outcome.ERROR: "ERROR",
        Outcome.SKIPPED: "SKIP",
    }.get(outcome, "?")
