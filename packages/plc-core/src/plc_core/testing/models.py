"""Result models for integration test execution."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class Outcome(enum.Enum):
    """Result of a step or scenario execution."""

    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class StepResult:
    """Result of a single test step execution."""

    step_index: int
    step_type: str
    description: str
    outcome: Outcome
    duration_s: float = 0.0
    error_message: str | None = None
    expected_values: dict[str, Any] = field(default_factory=dict)
    actual_values: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.outcome == Outcome.PASSED

    @property
    def failed(self) -> bool:
        return self.outcome in (Outcome.FAILED, Outcome.ERROR)


@dataclass
class ScenarioResult:
    """Result of a complete scenario execution."""

    name: str
    source_file: Path | None
    step_results: list[StepResult] = field(default_factory=list)
    cleanup_results: list[StepResult] = field(default_factory=list)
    outcome: Outcome = Outcome.PASSED
    duration_s: float = 0.0
    error_message: str | None = None
    skip_reason: str | None = None

    @property
    def passed(self) -> bool:
        return self.outcome == Outcome.PASSED

    @property
    def skipped(self) -> bool:
        return self.outcome == Outcome.SKIPPED

    @property
    def total_steps(self) -> int:
        return len(self.step_results)

    @property
    def steps_passed(self) -> int:
        return sum(1 for s in self.step_results if s.passed)

    @property
    def steps_warned(self) -> int:
        return sum(1 for s in self.step_results if s.outcome == Outcome.WARNING)

    @property
    def steps_failed(self) -> int:
        return sum(1 for s in self.step_results if s.failed)


@dataclass
class TestSuiteResult:
    """Result of running multiple scenarios."""

    __test__ = False  # a result/config model, not a pytest test class

    scenario_results: list[ScenarioResult] = field(default_factory=list)
    total_duration_s: float = 0.0

    @property
    def total_scenarios(self) -> int:
        return len(self.scenario_results)

    @property
    def scenarios_passed(self) -> int:
        return sum(1 for s in self.scenario_results if s.passed)

    @property
    def scenarios_skipped(self) -> int:
        return sum(1 for s in self.scenario_results if s.skipped)

    @property
    def scenarios_failed(self) -> int:
        return self.total_scenarios - self.scenarios_passed - self.scenarios_skipped

    @property
    def overall_success(self) -> bool:
        return all(s.passed or s.skipped for s in self.scenario_results)
