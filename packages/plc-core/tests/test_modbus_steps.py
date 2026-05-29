"""Tests for the Modbus step parsers and runner executors.

The runner executors are exercised against a small mock that mimics the
``ModbusClient`` surface (only ``read_register_at`` is needed). This keeps
plc-core decoupled from plc-modbus.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from plc_core.testing.models import Outcome
from plc_core.testing.runner import ScenarioRunner
from plc_core.testing.schema import (
    _STEP_PARSERS,
    ModbusAssertStep,
    ModbusReadStep,
    ModbusWaitUntilStep,
    _parse_step,
)

# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


class TestModbusReadParser:
    def test_minimal(self) -> None:
        step = _parse_step({"step": "modbus_read", "register": "HOLDING:0"})
        assert isinstance(step, ModbusReadStep)
        assert step.register == "HOLDING:0"
        assert step.count == 1
        assert step.dtype == "uint16"

    def test_full(self) -> None:
        step = _parse_step(
            {
                "step": "modbus_read",
                "description": "Read 5 holding registers",
                "register": "HOLDING:10",
                "count": 5,
                "dtype": "int16",
            }
        )
        assert isinstance(step, ModbusReadStep)
        assert step.description == "Read 5 holding registers"
        assert step.count == 5
        assert step.dtype == "int16"

    def test_missing_register_raises(self) -> None:
        with pytest.raises(ValueError, match="modbus_read step requires a 'register'"):
            _parse_step({"step": "modbus_read"})


class TestModbusAssertParser:
    def test_basic(self) -> None:
        step = _parse_step(
            {
                "step": "modbus_assert",
                "values": {"HOLDING:0": 12345, "HOLDING:0/6": True},
            }
        )
        assert isinstance(step, ModbusAssertStep)
        assert step.values == {"HOLDING:0": 12345, "HOLDING:0/6": True}
        assert step.tolerance is None

    def test_tolerance(self) -> None:
        step = _parse_step({"step": "modbus_assert", "values": {"HOLDING:0": 100}, "tolerance": 0.5})
        assert isinstance(step, ModbusAssertStep)
        assert step.tolerance == 0.5

    def test_empty_values_rejected(self) -> None:
        with pytest.raises(ValueError, match="modbus_assert step requires a non-empty"):
            _parse_step({"step": "modbus_assert", "values": {}})

    def test_missing_values_rejected(self) -> None:
        with pytest.raises(ValueError, match="modbus_assert step requires a non-empty"):
            _parse_step({"step": "modbus_assert"})


class TestModbusWaitUntilParser:
    def test_minimal(self) -> None:
        step = _parse_step({"step": "modbus_wait_until", "register": "HOLDING:5", "value": 42})
        assert isinstance(step, ModbusWaitUntilStep)
        assert step.register == "HOLDING:5"
        assert step.value == 42
        assert step.timeout_s == 10.0
        assert step.poll_interval_s == 0.5

    def test_durations(self) -> None:
        step = _parse_step(
            {
                "step": "modbus_wait_until",
                "register": "HOLDING:5",
                "value": True,
                "timeout": "30s",
                "poll_interval": "100ms",
            }
        )
        assert isinstance(step, ModbusWaitUntilStep)
        assert step.timeout_s == 30.0
        assert step.poll_interval_s == 0.1

    def test_missing_register_raises(self) -> None:
        with pytest.raises(ValueError, match="modbus_wait_until step requires a 'register'"):
            _parse_step({"step": "modbus_wait_until", "value": 1})

    def test_missing_value_raises(self) -> None:
        with pytest.raises(ValueError, match="modbus_wait_until step requires a 'value'"):
            _parse_step({"step": "modbus_wait_until", "register": "HOLDING:0"})


# ---------------------------------------------------------------------------
# Runner executors
# ---------------------------------------------------------------------------


def _make_runner(modbus_client: Any = None) -> ScenarioRunner:
    """Build a minimal ScenarioRunner for executor testing."""
    return ScenarioRunner(
        client=MagicMock(),
        tag_resolver=MagicMock(),
        console=MagicMock(),
        modbus_client=modbus_client,
    )


@pytest.mark.asyncio
class TestModbusReadExecutor:
    async def test_passes_and_returns_value(self) -> None:
        mb = MagicMock()
        mb.read_register_at = AsyncMock(return_value=12345)
        runner = _make_runner(mb)

        step = ModbusReadStep(register="HOLDING:42", dtype="uint16")
        result = await runner._execute_modbus_read(0, step, t0=0.0)

        assert result.outcome == Outcome.PASSED
        assert result.actual_values == {"HOLDING:42": 12345}
        mb.read_register_at.assert_awaited_once_with("HOLDING:42", dtype="uint16")

    async def test_no_client_returns_error(self) -> None:
        runner = _make_runner(None)
        step = ModbusReadStep(register="HOLDING:0")
        result = await runner._execute_modbus_read(0, step, t0=0.0)
        assert result.outcome == Outcome.ERROR
        assert "Modbus client is not configured" in (result.error_message or "")

    async def test_client_exception_becomes_error(self) -> None:
        mb = MagicMock()
        mb.read_register_at = AsyncMock(side_effect=RuntimeError("boom"))
        runner = _make_runner(mb)
        step = ModbusReadStep(register="HOLDING:0")
        result = await runner._execute_modbus_read(0, step, t0=0.0)
        assert result.outcome == Outcome.ERROR
        assert "RuntimeError: boom" in (result.error_message or "")


@pytest.mark.asyncio
class TestModbusAssertExecutor:
    async def test_all_match_passes(self) -> None:
        mb = MagicMock()
        mb.read_register_at = AsyncMock(side_effect=[12345, True])
        runner = _make_runner(mb)

        step = ModbusAssertStep(values={"HOLDING:0": 12345, "HOLDING:0/6": True})
        result = await runner._execute_modbus_assert(0, step, t0=0.0)

        assert result.outcome == Outcome.PASSED
        assert result.expected_values == {"HOLDING:0": 12345, "HOLDING:0/6": True}
        assert result.actual_values == {"HOLDING:0": 12345, "HOLDING:0/6": True}

    async def test_mismatch_fails_with_message(self) -> None:
        mb = MagicMock()
        mb.read_register_at = AsyncMock(return_value=999)
        runner = _make_runner(mb)

        step = ModbusAssertStep(values={"HOLDING:0": 12345})
        result = await runner._execute_modbus_assert(0, step, t0=0.0)

        assert result.outcome == Outcome.FAILED
        assert "expected 12345" in (result.error_message or "")
        assert "got 999" in (result.error_message or "")

    async def test_bool_dtype_chosen_for_bool_expected(self) -> None:
        mb = MagicMock()
        mb.read_register_at = AsyncMock(return_value=True)
        runner = _make_runner(mb)

        step = ModbusAssertStep(values={"HOLDING:0/6": True})
        await runner._execute_modbus_assert(0, step, t0=0.0)
        mb.read_register_at.assert_awaited_with("HOLDING:0/6", dtype="bool")

    async def test_uint16_dtype_for_int_expected(self) -> None:
        mb = MagicMock()
        mb.read_register_at = AsyncMock(return_value=12345)
        runner = _make_runner(mb)

        step = ModbusAssertStep(values={"HOLDING:0": 12345})
        await runner._execute_modbus_assert(0, step, t0=0.0)
        mb.read_register_at.assert_awaited_with("HOLDING:0", dtype="uint16")

    async def test_no_client_returns_error(self) -> None:
        runner = _make_runner(None)
        step = ModbusAssertStep(values={"HOLDING:0": 1})
        result = await runner._execute_modbus_assert(0, step, t0=0.0)
        assert result.outcome == Outcome.ERROR


@pytest.mark.asyncio
class TestModbusWaitUntilExecutor:
    async def test_immediate_match(self) -> None:
        mb = MagicMock()
        mb.read_register_at = AsyncMock(return_value=42)
        runner = _make_runner(mb)

        step = ModbusWaitUntilStep(register="HOLDING:5", value=42, timeout_s=1.0, poll_interval_s=0.05)
        result = await runner._execute_modbus_wait_until(0, step, t0=0.0)

        assert result.outcome == Outcome.PASSED
        assert result.actual_values == {"HOLDING:5": 42}

    async def test_match_after_polls(self) -> None:
        mb = MagicMock()
        # First two reads return wrong value, third matches.
        mb.read_register_at = AsyncMock(side_effect=[0, 0, 42])
        runner = _make_runner(mb)

        step = ModbusWaitUntilStep(register="HOLDING:5", value=42, timeout_s=2.0, poll_interval_s=0.01)
        result = await runner._execute_modbus_wait_until(0, step, t0=0.0)

        assert result.outcome == Outcome.PASSED
        assert mb.read_register_at.await_count == 3

    async def test_timeout_fails(self) -> None:
        mb = MagicMock()
        mb.read_register_at = AsyncMock(return_value=0)
        runner = _make_runner(mb)

        step = ModbusWaitUntilStep(register="HOLDING:5", value=42, timeout_s=0.05, poll_interval_s=0.01)
        result = await runner._execute_modbus_wait_until(0, step, t0=0.0)

        assert result.outcome == Outcome.FAILED
        assert "Timeout after" in (result.error_message or "")

    async def test_bool_dtype_forced_for_bool_target(self) -> None:
        mb = MagicMock()
        mb.read_register_at = AsyncMock(return_value=True)
        runner = _make_runner(mb)

        step = ModbusWaitUntilStep(register="HOLDING:0/6", value=True, dtype="uint16")
        await runner._execute_modbus_wait_until(0, step, t0=0.0)
        mb.read_register_at.assert_awaited_with("HOLDING:0/6", dtype="bool")

    async def test_no_client_returns_error(self) -> None:
        runner = _make_runner(None)
        step = ModbusWaitUntilStep(register="HOLDING:0", value=1)
        result = await runner._execute_modbus_wait_until(0, step, t0=0.0)
        assert result.outcome == Outcome.ERROR


# ---------------------------------------------------------------------------
# Registry sanity
# ---------------------------------------------------------------------------


class TestParserRegistry:
    def test_all_three_registered(self) -> None:
        for step_type in ("modbus_read", "modbus_assert", "modbus_wait_until"):
            assert step_type in _STEP_PARSERS
