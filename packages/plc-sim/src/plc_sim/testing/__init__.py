"""Integration testing framework for PLC simulation.

Defines YAML-based test scenarios, executes them against a live PLC
via OPC UA, and reports results.
"""

from plc_sim.testing.models import (
    Outcome,
    ScenarioResult,
    StepResult,
    TestSuiteResult,
)
from plc_sim.testing.reporter import (
    ReportMetadata,
    generate_junit_xml,
    generate_markdown_report,
    print_suite_summary,
)
from plc_sim.testing.runner import ScenarioRunner
from plc_sim.testing.schema import (
    AssertFlashStep,
    AssertStableStep,
    Scenario,
    SuiteSetup,
    discover_scenario_files,
    parse_duration,
    parse_scenario,
    parse_setup,
)
from plc_sim.testing.steps import (
    parse_assert_flash,
    parse_assert_stable,
)
from plc_sim.testing.tag_resolver import TagInfo, TagResolver

__all__ = [
    "Outcome",
    "StepResult",
    "ScenarioResult",
    "TestSuiteResult",
    "AssertFlashStep",
    "AssertStableStep",
    "Scenario",
    "SuiteSetup",
    "parse_scenario",
    "parse_setup",
    "parse_duration",
    "parse_assert_flash",
    "parse_assert_stable",
    "discover_scenario_files",
    "TagInfo",
    "TagResolver",
    "ScenarioRunner",
    "print_suite_summary",
    "generate_junit_xml",
    "generate_markdown_report",
    "ReportMetadata",
]
