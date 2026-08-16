"""Tests for scenario-level `skip` / `skip_reason` (schema, runner, models)."""

import asyncio

from rich.console import Console

from plc_core.testing.models import Outcome, ScenarioResult, TestSuiteResult
from plc_core.testing.runner import ScenarioRunner
from plc_core.testing.schema import Scenario, parse_scenario

# ---------------------------------------------------------------------------
# schema: parsing skip / skip_reason from YAML
# ---------------------------------------------------------------------------


def test_parse_scenario_without_skip_defaults_to_false(tmp_path):
    path = tmp_path / "test_no_skip.yaml"
    path.write_text("""
scenario:
  name: "No skip"
  steps: []
""")
    scenario = parse_scenario(path)
    assert scenario.skip is False
    assert scenario.skip_reason == ""


def test_parse_scenario_with_skip_and_reason(tmp_path):
    path = tmp_path / "test_skip.yaml"
    path.write_text("""
scenario:
  name: "Skipped"
  skip: true
  skip_reason: "waiting on TIA recompile"
  steps: []
""")
    scenario = parse_scenario(path)
    assert scenario.skip is True
    assert scenario.skip_reason == "waiting on TIA recompile"


# ---------------------------------------------------------------------------
# runner: skip short-circuits before any client interaction
# ---------------------------------------------------------------------------


class _RaisingClient:
    """Any method call is a test failure — a skipped scenario must never touch the client."""

    def __getattr__(self, name):
        def _fail(*args, **kwargs):
            raise AssertionError(f"skipped scenario called client.{name}()")

        return _fail


class _RaisingResolver:
    def resolve(self, path):
        raise AssertionError(f"skipped scenario resolved tag {path!r}")


def test_run_scenario_skip_short_circuits_without_client_calls():
    runner = ScenarioRunner(
        client=_RaisingClient(),
        tag_resolver=_RaisingResolver(),
        console=Console(),
    )
    scenario = Scenario(
        name="Skipped scenario",
        skip=True,
        skip_reason="waiting on TIA recompile",
        preconditions=[],
        steps=[],
        cleanup=[],
    )
    result = asyncio.run(runner.run_scenario(scenario))

    assert result.outcome == Outcome.SKIPPED
    assert result.skip_reason == "waiting on TIA recompile"
    assert result.total_steps == 0
    assert result.step_results == []
    assert result.cleanup_results == []


def test_run_scenario_skip_with_no_reason_given():
    runner = ScenarioRunner(client=_RaisingClient(), tag_resolver=_RaisingResolver(), console=Console())
    scenario = Scenario(name="Skipped, no reason", skip=True)
    result = asyncio.run(runner.run_scenario(scenario))

    assert result.outcome == Outcome.SKIPPED
    assert result.skip_reason is None


# ---------------------------------------------------------------------------
# models: TestSuiteResult accounting excludes skipped from pass/fail counts
# ---------------------------------------------------------------------------


def _result(outcome: Outcome) -> ScenarioResult:
    return ScenarioResult(name="x", source_file=None, outcome=outcome)


def test_suite_result_skipped_is_not_counted_as_failed():
    suite = TestSuiteResult(
        scenario_results=[
            _result(Outcome.PASSED),
            _result(Outcome.PASSED),
            _result(Outcome.SKIPPED),
        ]
    )
    assert suite.scenarios_passed == 2
    assert suite.scenarios_skipped == 1
    assert suite.scenarios_failed == 0
    assert suite.overall_success is True


def test_suite_result_skipped_does_not_mask_a_real_failure():
    suite = TestSuiteResult(
        scenario_results=[
            _result(Outcome.PASSED),
            _result(Outcome.SKIPPED),
            _result(Outcome.FAILED),
        ]
    )
    assert suite.scenarios_passed == 1
    assert suite.scenarios_skipped == 1
    assert suite.scenarios_failed == 1
    assert suite.overall_success is False


def test_scenario_result_skipped_property():
    assert _result(Outcome.SKIPPED).skipped is True
    assert _result(Outcome.PASSED).skipped is False
    assert _result(Outcome.SKIPPED).passed is False
