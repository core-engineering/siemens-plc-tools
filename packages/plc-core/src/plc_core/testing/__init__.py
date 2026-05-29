"""Testing framework for PLC integration tests via OPC UA."""

from plc_core.testing.models import Outcome, ScenarioResult, StepResult, TestSuiteResult
from plc_core.testing.reporter import (
    ReportMetadata,
    generate_junit_xml,
    generate_markdown_report,
    print_scenario_result,
    print_step_result,
    print_suite_summary,
)
from plc_core.testing.runner import ScenarioRunner
from plc_core.testing.schema import (
    AssertStep,
    Precondition,
    ReadStep,
    RestoreStep,
    Scenario,
    SnapshotStep,
    Step,
    SuiteSetup,
    WaitStep,
    WaitUntilStep,
    WriteStep,
    discover_scenario_files,
    parse_duration,
    parse_scenario,
    parse_setup,
    register_step_parser,
)
from plc_core.testing.tag_resolver import TagInfo, TagResolver

__all__ = [
    # models
    "Outcome",
    "StepResult",
    "ScenarioResult",
    "TestSuiteResult",
    # schema - step types
    "WriteStep",
    "WaitStep",
    "AssertStep",
    "WaitUntilStep",
    "ReadStep",
    "SnapshotStep",
    "RestoreStep",
    "Step",
    # schema - structures
    "SuiteSetup",
    "Precondition",
    "Scenario",
    # schema - functions
    "parse_duration",
    "parse_scenario",
    "parse_setup",
    "discover_scenario_files",
    "register_step_parser",
    # runner
    "ScenarioRunner",
    # reporter
    "ReportMetadata",
    "print_step_result",
    "print_scenario_result",
    "print_suite_summary",
    "generate_junit_xml",
    "generate_markdown_report",
    # tag_resolver
    "TagInfo",
    "TagResolver",
]
