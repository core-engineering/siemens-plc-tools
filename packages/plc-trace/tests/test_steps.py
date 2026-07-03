"""Tests for trace_start/trace_stop/trace_fetch scenario steps.

Executor tests reuse the Task 4 in-process asyncua server fixture (same
contract layout and ``_patch_index_range_support`` monkeypatch as
``test_trace_client.py``) so ``TraceClient`` methods exercise real OPC UA
reads/writes rather than mocks.
"""

from __future__ import annotations

import asyncio
import time
import types
from pathlib import Path

import pytest
import pytest_asyncio
from asyncua import Node, Server, ua
from plc_core.opcua.client import OpcUaClient
from plc_core.opcua.config import OpcUaConfig
from plc_core.testing.models import Outcome
from plc_trace.client import TraceClient
from plc_trace.config import TraceConfig
from plc_trace.steps import (
    TraceStartStep,
    TraceStopStep,
    execute_trace_fetch,
    execute_trace_start,
    execute_trace_stop,
    parse_trace_fetch,
    parse_trace_start,
    parse_trace_stop,
    register_trace_steps,
)

ENDPOINT = "opc.tcp://127.0.0.1:48442/trace-steps-test/"
DEPTH = 8
FIELDS = ["posX", "flag"]


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


def test_parse_trace_start_defaults() -> None:
    step = parse_trace_start({"step": "trace_start"})
    assert step == TraceStartStep(mode="ring", decimation=1)


def test_parse_trace_start_explicit() -> None:
    step = parse_trace_start({"step": "trace_start", "mode": "oneshot", "decimation": 5})
    assert step.mode == "oneshot"
    assert step.decimation == 5


def test_parse_trace_stop_defaults() -> None:
    step = parse_trace_stop({"step": "trace_stop"})
    assert isinstance(step, TraceStopStep)


def test_parse_trace_fetch_defaults() -> None:
    step = parse_trace_fetch({"step": "trace_fetch"})
    assert step.output == ""


def test_parse_trace_fetch_explicit() -> None:
    step = parse_trace_fetch({"step": "trace_fetch", "output": "x.csv"})
    assert step.output == "x.csv"


# ---------------------------------------------------------------------------
# In-process server fixture (same contract layout as test_trace_client.py)
# ---------------------------------------------------------------------------


async def _add(parent: Node, idx: int, name: str, value: object, vtype: ua.VariantType) -> Node:
    node = await parent.add_variable(idx, name, value, varianttype=vtype)
    await node.set_writable()
    return node


def _patch_index_range_support(server: Server) -> None:
    """Make the in-process test server honor ``ReadValueId.IndexRange``.

    See the identical helper in ``test_trace_client.py`` for the rationale.
    """
    original_read = server.iserver.attribute_service.read

    def _read_with_index_range(params: ua.ReadParameters) -> list[ua.DataValue]:
        results = original_read(params)
        sliced_results = []
        for read_value, data_value in zip(params.NodesToRead, results, strict=True):
            if read_value.AttributeId == ua.AttributeIds.Value and read_value.IndexRange:
                data_value = _sliced_data_value(data_value, read_value.IndexRange)
            sliced_results.append(data_value)
        return sliced_results

    server.iserver.attribute_service.read = _read_with_index_range  # type: ignore[method-assign]


def _sliced_data_value(data_value: ua.DataValue, index_range: str) -> ua.DataValue:
    if data_value.Value is None or not isinstance(data_value.Value.Value, list):
        return data_value
    values = data_value.Value.Value
    if ":" in index_range:
        lo_s, hi_s = index_range.split(":")
        sliced = values[int(lo_s) : int(hi_s) + 1]
    else:
        sliced = values[int(index_range)]
    new_variant = ua.Variant(sliced, data_value.Value.VariantType)
    return ua.DataValue(
        Value=new_variant,
        StatusCode=data_value.StatusCode,
        SourceTimestamp=data_value.SourceTimestamp,
        ServerTimestamp=data_value.ServerTimestamp,
    )


async def _build_server() -> tuple[Server, dict[str, Node]]:
    server = Server()
    await server.init()
    server.set_endpoint(ENDPOINT)
    _patch_index_range_support(server)
    idx = await server.register_namespace("urn:trace-steps-test")

    db = await server.nodes.objects.add_object(idx, "TraceData")
    control = await db.add_object(idx, "control")
    status = await db.add_object(idx, "status")

    nodes: dict[str, Node] = {
        "control.start": await _add(control, idx, "start", False, ua.VariantType.Boolean),
        "control.mode": await _add(control, idx, "mode", 0, ua.VariantType.Int16),
        "control.decimation": await _add(control, idx, "decimation", 1, ua.VariantType.UInt32),
        "status.recording": await _add(status, idx, "recording", False, ua.VariantType.Boolean),
        "status.wrapped": await _add(status, idx, "wrapped", False, ua.VariantType.Boolean),
        "status.writeIdx": await _add(status, idx, "writeIdx", 3, ua.VariantType.Int32),
        "status.sampleCount": await _add(status, idx, "sampleCount", 3, ua.VariantType.Int32),
        "status.cycleCounter": await _add(status, idx, "cycleCounter", 0, ua.VariantType.UInt32),
        "status.cycleTimeMs": await _add(status, idx, "cycleTimeMs", 10.0, ua.VariantType.Float),
        "status.depth": await _add(status, idx, "depth", DEPTH, ua.VariantType.Int32),
        "status.startMem": await _add(status, idx, "startMem", False, ua.VariantType.Boolean),
        "status.decCounter": await _add(status, idx, "decCounter", 0, ua.VariantType.UInt32),
        "sampleCycles": await _add(db, idx, "sampleCycles", [1, 2, 3, 0, 0, 0, 0, 0], ua.VariantType.UInt32),
        "posX": await _add(db, idx, "posX", [0.1, 0.2, 0.3, 0, 0, 0, 0, 0], ua.VariantType.Float),
        "flag": await _add(
            db, idx, "flag", [True, False, True, False, False, False, False, False], ua.VariantType.Boolean
        ),
    }
    return server, nodes


@pytest_asyncio.fixture()
async def trace_server():
    server, nodes = await _build_server()
    resolve_map = {f"TraceData.{path}": node.nodeid.to_string() for path, node in nodes.items()}
    async with server:
        client = OpcUaClient(OpcUaConfig(endpoint=ENDPOINT))
        await client.connect()
        try:
            yield client, nodes, resolve_map
        finally:
            await client.disconnect()


def _make_stub_tags(resolve_map: dict[str, str]) -> types.SimpleNamespace:
    """A minimal TagResolver stand-in: ``tags.resolve(path).node_id``."""

    def _resolve(path: str) -> types.SimpleNamespace:
        if path not in resolve_map:
            raise KeyError(f"Tag not found: {path!r}")
        return types.SimpleNamespace(node_id=resolve_map[path])

    return types.SimpleNamespace(resolve=_resolve)


def _make_client(
    client: OpcUaClient, resolve_map: dict[str, str], fields: list[str] | None = FIELDS
) -> TraceClient:
    stub_tags = _make_stub_tags(resolve_map)
    config = TraceConfig(db_path="TraceData")
    return TraceClient(client, lambda p: stub_tags.resolve(p).node_id, config, fields=fields)


# ---------------------------------------------------------------------------
# Executor tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_trace_start_passes_and_writes_control(trace_server):
    client, nodes, resolve_map = trace_server
    tc = _make_client(client, resolve_map)
    step = parse_trace_start({"step": "trace_start", "mode": "oneshot", "decimation": 2})

    async def _set_recording_after_delay() -> None:
        await asyncio.sleep(0.1)
        await nodes["status.recording"].write_value(True, varianttype=ua.VariantType.Boolean)

    delayed = asyncio.create_task(_set_recording_after_delay())
    result = await execute_trace_start(tc, 0, step, time.monotonic())
    await delayed

    assert result.outcome is Outcome.PASSED
    assert (await nodes["control.start"].read_value()) is True
    assert (await nodes["control.mode"].read_value()) == 1
    assert (await nodes["control.decimation"].read_value()) == 2


@pytest.mark.asyncio
async def test_execute_trace_stop_passes_and_clears_control(trace_server):
    client, nodes, resolve_map = trace_server
    tc = _make_client(client, resolve_map)
    step = parse_trace_stop({"step": "trace_stop"})

    async def _clear_recording_after_delay() -> None:
        await asyncio.sleep(0.1)
        await nodes["status.recording"].write_value(False, varianttype=ua.VariantType.Boolean)

    await nodes["control.start"].write_value(True, varianttype=ua.VariantType.Boolean)
    await nodes["status.recording"].write_value(True, varianttype=ua.VariantType.Boolean)
    delayed = asyncio.create_task(_clear_recording_after_delay())
    result = await execute_trace_stop(tc, 0, step, time.monotonic())
    await delayed

    assert result.outcome is Outcome.PASSED
    assert (await nodes["control.start"].read_value()) is False


@pytest.mark.asyncio
async def test_execute_trace_fetch_writes_csv(trace_server, tmp_path):
    client, _nodes, resolve_map = trace_server
    tc = _make_client(client, resolve_map)
    step = parse_trace_fetch({"step": "trace_fetch"})

    result = await execute_trace_fetch(
        tc, 0, step, time.monotonic(), output_dir=tmp_path, scenario_name_provider=lambda: "my_scenario"
    )

    assert result.outcome is Outcome.PASSED
    out_path = tmp_path / "my_scenario.csv"
    assert out_path.exists()
    assert result.actual_values["output"] == str(out_path)
    assert result.actual_values["samples"] == 3


@pytest.mark.asyncio
async def test_execute_trace_fetch_explicit_output_relative_to_output_dir(trace_server, tmp_path):
    client, _nodes, resolve_map = trace_server
    tc = _make_client(client, resolve_map)
    step = parse_trace_fetch({"step": "trace_fetch", "output": "custom.csv"})

    result = await execute_trace_fetch(
        tc, 0, step, time.monotonic(), output_dir=tmp_path, scenario_name_provider=lambda: "unused"
    )

    assert result.outcome is Outcome.PASSED
    assert (tmp_path / "custom.csv").exists()


@pytest.mark.asyncio
async def test_execute_trace_fetch_falls_back_to_timestamp_when_name_unavailable(trace_server, tmp_path):
    client, _nodes, resolve_map = trace_server
    tc = _make_client(client, resolve_map)
    step = parse_trace_fetch({"step": "trace_fetch"})

    def _raise() -> str:
        raise RuntimeError("scenario name not reachable")

    result = await execute_trace_fetch(
        tc, 0, step, time.monotonic(), output_dir=tmp_path, scenario_name_provider=_raise
    )

    assert result.outcome is Outcome.PASSED
    saved = list(tmp_path.glob("trace_*.csv"))
    assert len(saved) == 1


# ---------------------------------------------------------------------------
# Failure path: unresolvable db_path -> Outcome.ERROR (no exception escapes)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_trace_start_error_on_unresolvable_path(trace_server):
    client, _nodes, _resolve_map = trace_server
    # Empty resolve map: every tag lookup raises KeyError.
    tc = _make_client(client, resolve_map={})
    step = parse_trace_start({"step": "trace_start"})

    result = await execute_trace_start(tc, 0, step, time.monotonic())

    assert result.outcome is Outcome.ERROR
    assert result.error_message
    assert "TraceData" in result.error_message


@pytest.mark.asyncio
async def test_execute_trace_fetch_error_on_unresolvable_path(trace_server, tmp_path):
    client, _nodes, _resolve_map = trace_server
    tc = _make_client(client, resolve_map={})
    step = parse_trace_fetch({"step": "trace_fetch"})

    result = await execute_trace_fetch(
        tc, 0, step, time.monotonic(), output_dir=tmp_path, scenario_name_provider=lambda: "s"
    )

    assert result.outcome is Outcome.ERROR
    assert result.error_message
    assert not list(tmp_path.glob("*.csv"))


@pytest.mark.asyncio
async def test_execute_trace_stop_error_on_unresolvable_path(trace_server):
    client, _nodes, _resolve_map = trace_server
    tc = _make_client(client, resolve_map={})
    step = parse_trace_stop({"step": "trace_stop"})

    result = await execute_trace_stop(tc, 0, step, time.monotonic())

    assert result.outcome is Outcome.ERROR
    assert result.error_message


# ---------------------------------------------------------------------------
# register_trace_steps wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_trace_steps_registers_all_three(trace_server):
    client, _nodes, resolve_map = trace_server
    stub_tags = _make_stub_tags(resolve_map)
    registered: dict[str, object] = {}

    runner = types.SimpleNamespace(
        client=client,
        tags=stub_tags,
        register_step=lambda step_type, executor: registered.__setitem__(step_type, executor),
    )

    config = TraceConfig(db_path="TraceData")
    register_trace_steps(
        runner, config, output_dir=Path("/tmp/does-not-matter"), scenario_name_provider=lambda: "s"
    )

    assert set(registered) == {"trace_start", "trace_stop", "trace_fetch"}
