"""Simulation config parsing and the scenario executors, on fake clients only."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from plc_core.testing.models import Outcome

from plc_sim.core.config import SimConfig, SimTestConfig
from plc_sim.testing.executors import execute_assert_flash, execute_assert_stable
from plc_sim.testing.steps import AssertFlashStep, AssertStableStep


class TestSimTestConfig:
    def test_defaults(self) -> None:
        config = SimTestConfig.from_dict({})
        assert config.test_dir == "integration-tests"
        assert config.cache_dir == ".sim"
        assert config.scenario_timeout_s == 60.0
        assert config.results_cache_filename == "test_results.json"

    def test_overrides_and_glob_list(self) -> None:
        config = SimTestConfig.from_dict(
            {"test_dir": "efat", "baseline_source_globs": ["blocks/**/*.s7dcl"], "cache_ttl_hours": 1}
        )
        assert (config.test_dir, config.cache_ttl_hours) == ("efat", 1)
        assert config.baseline_source_globs == ["blocks/**/*.s7dcl"]


class TestSimConfig:
    def test_endpoint_round_trips_through_the_opcua_section(self) -> None:
        config = SimConfig.from_dict({"endpoint": "opc.tcp://192.0.2.10:4840"})
        assert config.endpoint == "opc.tcp://192.0.2.10:4840"
        config.endpoint = "opc.tcp://192.0.2.11:4840"
        assert config.endpoint == "opc.tcp://192.0.2.11:4840"


# -- executors on fakes ---------------------------------------------------------------


@dataclass
class _Value:
    value: Any


class _FakeClient:
    """Hands back a scripted sequence of values, then repeats the last one."""

    def __init__(self, values: list[Any]) -> None:
        self._values = list(values)

    async def read_value(self, node_id: str) -> _Value:
        return _Value(self._values.pop(0) if len(self._values) > 1 else self._values[0])


@dataclass
class _FakeTag:
    node_id: str = "ns=3;s=x"


class _FakeTags:
    def resolve(self, path: str) -> _FakeTag:
        return _FakeTag()


@dataclass
class _FakeRunner:
    client: _FakeClient
    tags: _FakeTags


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class TestAssertStable:
    def test_passes_while_the_value_holds(self) -> None:
        step = AssertStableStep(path="a.b", value=True, duration_s=0.05, poll_interval_s=0.01)
        runner = _FakeRunner(_FakeClient([True]), _FakeTags())
        result = _run(execute_assert_stable(runner, 0, step, 0.0))
        assert result.outcome is Outcome.PASSED

    def test_fails_the_moment_the_value_moves(self) -> None:
        step = AssertStableStep(path="a.b", value=True, duration_s=1.0, poll_interval_s=0.0)
        runner = _FakeRunner(_FakeClient([True, True, False]), _FakeTags())
        result = _run(execute_assert_stable(runner, 0, step, 0.0))
        assert result.outcome is Outcome.FAILED
        assert result.error_message is not None and "changed to False" in result.error_message


class TestAssertFlash:
    def test_an_unknown_pattern_is_an_error_before_any_read(self) -> None:
        step = AssertFlashStep(path="a.b", pattern="FL9", duration_s=0.01, poll_interval_s=0.01)
        result = _run(execute_assert_flash(_FakeRunner(_FakeClient([True]), _FakeTags()), 0, step, 0.0))
        assert result.outcome is Outcome.ERROR
        assert result.error_message is not None and "FL9" in result.error_message

    def test_a_dead_signal_fails_with_the_ratio(self) -> None:
        step = AssertFlashStep(path="a.b", pattern="FL1", duration_s=0.05, poll_interval_s=0.005)
        result = _run(execute_assert_flash(_FakeRunner(_FakeClient([False]), _FakeTags()), 0, step, 0.0))
        assert result.outcome is Outcome.FAILED
        assert result.error_message is not None and "dead" in result.error_message

    def test_a_constant_true_signal_is_a_jitter_warning_not_a_pass(self) -> None:
        step = AssertFlashStep(path="a.b", pattern="FL1", duration_s=0.05, poll_interval_s=0.005)
        result = _run(execute_assert_flash(_FakeRunner(_FakeClient([True]), _FakeTags()), 0, step, 0.0))
        assert result.outcome is Outcome.WARNING
        assert result.error_message is not None and "transition" in result.error_message
