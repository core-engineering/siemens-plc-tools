"""Re-exports from plc-core + sim-specific step registration."""

from plc_core.testing.schema import (  # noqa: F401
    AssertStep,
    Precondition,
    ReadStep,
    RestoreStep,
    Scenario,
    SnapshotStep,
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

# Re-export sim-specific steps
from plc_sim.testing.steps import (  # noqa: F401
    AssertFlashStep,
    AssertStableStep,
    parse_assert_flash,
    parse_assert_stable,
)

# Register sim-specific step parsers
register_step_parser("assert_flash", parse_assert_flash)
register_step_parser("assert_stable", parse_assert_stable)

Step = (
    WriteStep
    | WaitStep
    | AssertStep
    | WaitUntilStep
    | AssertStableStep
    | AssertFlashStep
    | ReadStep
    | SnapshotStep
    | RestoreStep
)

__all__ = [
    "AssertFlashStep",
    "AssertStableStep",
    "AssertStep",
    "Precondition",
    "ReadStep",
    "RestoreStep",
    "Scenario",
    "SnapshotStep",
    "Step",
    "SuiteSetup",
    "WaitStep",
    "WaitUntilStep",
    "WriteStep",
    "discover_scenario_files",
    "parse_duration",
    "parse_scenario",
    "parse_setup",
    "register_step_parser",
]
