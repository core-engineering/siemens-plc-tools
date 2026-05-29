"""Backward-compatible re-exports from plc-core."""

from plc_core.testing.models import (  # noqa: F401
    Outcome,
    ScenarioResult,
    StepResult,
    TestSuiteResult,
)

__all__ = ["Outcome", "ScenarioResult", "StepResult", "TestSuiteResult"]
