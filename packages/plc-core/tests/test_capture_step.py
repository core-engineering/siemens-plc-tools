"""Tests for the generic OPC UA `capture` step (schema + parser + executor)."""

import asyncio
import json
from dataclasses import dataclass

import pytest
from rich.console import Console

from plc_core.opcua.models import OpcUaValue
from plc_core.testing.runner import ScenarioRunner
from plc_core.testing.schema import _STEP_PARSERS, CaptureStep, _parse_step


def test_parse_capture_with_duration():
    raw = {
        "step": "capture",
        "description": "goto stream",
        "paths": ["newPosition[0]", "busy"],
        "duration": "2s",
        "output": "captures/goto.json",
        "sampling_interval_ms": 20,
    }
    step = _parse_step(raw)
    assert isinstance(step, CaptureStep)
    assert step.step_type == "capture"
    assert step.paths == ["newPosition[0]", "busy"]
    assert step.duration_s == 2.0
    assert step.until_path == ""
    assert step.output == "captures/goto.json"
    assert step.sampling_interval_ms == 20


def test_parse_capture_with_until():
    raw = {
        "step": "capture",
        "paths": ["newPosition[0]"],
        "until": {"path": "done", "value": True},
        "output": "captures/goto.json",
    }
    step = _parse_step(raw)
    assert step.until_path == "done"
    assert step.until_value is True
    assert step.duration_s == 0.0
    assert step.sampling_interval_ms == 50  # default


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_parse_capture_missing_paths_raises() -> None:
    with pytest.raises(ValueError, match="non-empty 'paths' list"):
        _parse_step({"step": "capture", "output": "captures/out.json"})


def test_parse_capture_empty_paths_raises() -> None:
    with pytest.raises(ValueError, match="non-empty 'paths' list"):
        _parse_step({"step": "capture", "paths": [], "output": "captures/out.json"})


def test_parse_capture_missing_output_raises() -> None:
    with pytest.raises(ValueError, match="'output' file path"):
        _parse_step({"step": "capture", "paths": ["newPosition[0]"]})


def test_parse_capture_no_stop_condition_raises() -> None:
    with pytest.raises(ValueError, match="positive 'duration' or an 'until' condition"):
        _parse_step(
            {
                "step": "capture",
                "paths": ["newPosition[0]"],
                "duration": "0s",
                "output": "captures/out.json",
            }
        )


# ---------------------------------------------------------------------------
# Registry sanity
# ---------------------------------------------------------------------------


class TestParserRegistry:
    def test_capture_registered(self) -> None:
        assert "capture" in _STEP_PARSERS


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


@dataclass
class _Tag:
    node_id: str


class _FakeResolver:
    """Maps friendly paths to fake node-ids 1:1."""

    def resolve(self, path):
        return _Tag(node_id=f"ns=3;s={path}")


class _FakeClient:
    """Pushes a scripted burst of OpcUaValue into the subscription queue."""

    def __init__(self, scripted):
        self._scripted = scripted  # list[(path, value)]

    async def subscribe(self, node_ids, queue, interval_ms=None):
        for path, value in self._scripted:
            await queue.put(
                OpcUaValue(
                    node_id=f"ns=3;s={path}",
                    value=value,
                    source_timestamp="",
                    server_timestamp="",
                    status_code=0,
                    quality="Good",
                )
            )
        return "sub-1"

    async def unsubscribe(self, sub_id):
        return None

    async def read_value(self, node_id):  # used by `until` polling fallback
        return OpcUaValue(
            node_id=node_id,
            value=True,
            source_timestamp="",
            server_timestamp="",
            status_code=0,
            quality="Good",
        )


def test_capture_writes_samples(tmp_path):
    out = tmp_path / "cap.json"
    step = CaptureStep(
        paths=["newPosition[0]", "busy"], duration_s=0.2, output=str(out), sampling_interval_ms=10
    )
    runner = ScenarioRunner(
        client=_FakeClient([("newPosition[0]", 1.0), ("busy", True), ("newPosition[0]", 2.0)]),
        tag_resolver=_FakeResolver(),
        console=Console(),
    )
    result = asyncio.run(runner._execute_capture(0, step, 0.0))
    assert result.outcome.name == "PASSED"
    data = json.loads(out.read_text())
    assert data["meta"]["paths"] == ["newPosition[0]", "busy"]
    assert len(data["samples"]) == 3
    assert data["samples"][0]["path"] == "newPosition[0]"
    assert data["samples"][0]["value"] == 1.0
    assert "t" in data["samples"][0]


def test_capture_until_in_stream_match(tmp_path):
    """In-stream `until` match stops the capture at (and includes) the matching sample."""
    out = tmp_path / "cap.json"
    step = CaptureStep(
        paths=["newPosition[0]", "done"],
        duration_s=0.0,
        until_path="done",
        until_value=True,
        output=str(out),
    )
    runner = ScenarioRunner(
        client=_FakeClient(
            [
                ("newPosition[0]", 1.0),
                ("newPosition[0]", 2.0),
                ("done", True),
                ("newPosition[0]", 3.0),  # must NOT be recorded
            ]
        ),
        tag_resolver=_FakeResolver(),
        console=Console(),
    )
    result = asyncio.run(runner._execute_capture(0, step, 0.0))
    assert result.outcome.name == "PASSED"
    data = json.loads(out.read_text())
    # Capture stops at the `done`=True sample; the trailing 3.0 is not recorded.
    assert len(data["samples"]) == 3
    assert data["samples"][-1]["path"] == "done"
    assert data["samples"][-1]["value"] is True


class _PollOnlyFakeClient:
    """Pushes NOTHING into the queue; the `until` stop is reached via the poll fallback."""

    async def subscribe(self, node_ids, queue, interval_ms=None):
        return "sub-poll"

    async def unsubscribe(self, sub_id):
        return None

    async def read_value(self, node_id):
        return OpcUaValue(
            node_id=node_id,
            value=True,
            source_timestamp="",
            server_timestamp="",
            status_code=0,
            quality="Good",
        )


def test_capture_until_poll_fallback(tmp_path):
    """With no stream traffic, the poll fallback reads the `until` value and stops."""
    out = tmp_path / "cap.json"
    step = CaptureStep(
        paths=["newPosition[0]"],
        duration_s=0.0,
        until_path="done",
        until_value=True,
        output=str(out),
    )
    runner = ScenarioRunner(
        client=_PollOnlyFakeClient(),
        tag_resolver=_FakeResolver(),
        console=Console(),
    )
    result = asyncio.run(runner._execute_capture(0, step, 0.0))
    assert result.outcome.name == "PASSED"
    data = json.loads(out.read_text())
    assert data["samples"] == []
