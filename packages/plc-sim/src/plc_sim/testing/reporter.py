"""Backward-compatible re-exports from plc-core."""

from plc_core.testing.reporter import (  # noqa: F401
    ReportMetadata,
    generate_junit_xml,
    generate_markdown_report,
    print_scenario_result,
    print_step_result,
    print_suite_summary,
)

__all__ = [
    "ReportMetadata",
    "generate_junit_xml",
    "generate_markdown_report",
    "print_scenario_result",
    "print_step_result",
    "print_suite_summary",
]
