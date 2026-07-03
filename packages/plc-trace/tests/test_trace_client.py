"""TraceClient protocol tests against an in-process asyncua server.

The server hosts the contract layout produced by the Task 2 scaffold
generator (``control.*`` / ``status.*`` / ``sampleCycles`` / one array per
UDT field) for a depth-8 trace with fields ``posX: Real`` and ``flag: Bool``.
"""

from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio
from asyncua import Node, Server, ua
from plc_core.opcua.client import OpcUaClient
from plc_core.opcua.config import OpcUaConfig
from plc_trace.client import TraceClient
from plc_trace.config import TraceConfig

ENDPOINT = "opc.tcp://127.0.0.1:48441/trace-client-test/"
DEPTH = 8
FIELDS = ["posX", "flag"]


async def _add(parent: Node, idx: int, name: str, value: object, vtype: ua.VariantType) -> Node:
    node = await parent.add_variable(idx, name, value, varianttype=vtype)
    await node.set_writable()
    return node


async def _set(node: Node, value: object, vtype: ua.VariantType) -> None:
    """Write a scalar/array value with an explicit VariantType.

    asyncua's plain ``Node.write_value(value)`` guesses the wire type from
    the Python type (e.g. ``int`` -> Int64, ``float`` -> Double), which
    mismatches the narrower contract types (Int32/UInt32/Float) created by
    :func:`_add` and is rejected by the server as ``BadTypeMismatch``.
    """
    await node.write_value(value, varianttype=vtype)


def _patch_index_range_support(server: Server) -> None:
    """Make the in-process test server honor ``ReadValueId.IndexRange``.

    See the identical helper in
    ``packages/plc-core/tests/test_read_array_range.py`` for the rationale:
    the bundled asyncua in-memory ``Server`` ignores IndexRange on reads.
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
    idx = await server.register_namespace("urn:trace-client-test")

    db = await server.nodes.objects.add_object(idx, "TraceData")
    control = await db.add_object(idx, "control")
    status = await db.add_object(idx, "status")

    nodes: dict[str, Node] = {
        "control.start": await _add(control, idx, "start", False, ua.VariantType.Boolean),
        "control.mode": await _add(control, idx, "mode", 0, ua.VariantType.Int16),
        "control.decimation": await _add(control, idx, "decimation", 1, ua.VariantType.UInt32),
        "status.recording": await _add(status, idx, "recording", False, ua.VariantType.Boolean),
        "status.wrapped": await _add(status, idx, "wrapped", False, ua.VariantType.Boolean),
        "status.writeIdx": await _add(status, idx, "writeIdx", 0, ua.VariantType.Int32),
        "status.sampleCount": await _add(status, idx, "sampleCount", 0, ua.VariantType.Int32),
        "status.cycleCounter": await _add(status, idx, "cycleCounter", 0, ua.VariantType.UInt32),
        "status.cycleTimeMs": await _add(status, idx, "cycleTimeMs", 0.0, ua.VariantType.Float),
        "status.depth": await _add(status, idx, "depth", DEPTH, ua.VariantType.Int32),
        "status.startMem": await _add(status, idx, "startMem", False, ua.VariantType.Boolean),
        "status.decCounter": await _add(status, idx, "decCounter", 0, ua.VariantType.UInt32),
        "sampleCycles": await _add(db, idx, "sampleCycles", [0] * DEPTH, ua.VariantType.UInt32),
        "posX": await _add(db, idx, "posX", [0.0] * DEPTH, ua.VariantType.Float),
        "flag": await _add(db, idx, "flag", [False] * DEPTH, ua.VariantType.Boolean),
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


def _make_client(client, resolve_map, fetch_chunk: int = 500) -> TraceClient:
    config = TraceConfig(db_path="TraceData", fetch_chunk=fetch_chunk)
    return TraceClient(client, resolve_map.__getitem__, config, fields=FIELDS)


@pytest.mark.asyncio
async def test_start_writes_control_and_waits(trace_server):
    client, nodes, resolve_map = trace_server
    tc = _make_client(client, resolve_map)

    async def _set_recording_after_delay() -> None:
        await asyncio.sleep(0.15)
        await _set(nodes["status.recording"], True, ua.VariantType.Boolean)

    delayed = asyncio.create_task(_set_recording_after_delay())
    await tc.start(mode="oneshot", decimation=3)
    await delayed

    assert await nodes["control.mode"].read_value() == 1
    assert await nodes["control.decimation"].read_value() == 3
    assert (await nodes["control.start"].read_value()) is True


@pytest.mark.asyncio
async def test_start_times_out_with_clear_message(trace_server):
    client, _nodes, resolve_map = trace_server
    tc = _make_client(client, resolve_map)

    with pytest.raises(TimeoutError, match="status.recording"):
        await tc.start(timeout_s=0.2)


@pytest.mark.asyncio
async def test_stop_clears_start_and_returns_status(trace_server):
    client, nodes, resolve_map = trace_server
    tc = _make_client(client, resolve_map)

    await _set(nodes["control.start"], True, ua.VariantType.Boolean)
    await _set(nodes["status.recording"], True, ua.VariantType.Boolean)

    async def _clear_recording_after_delay() -> None:
        await asyncio.sleep(0.15)
        await _set(nodes["status.recording"], False, ua.VariantType.Boolean)

    delayed = asyncio.create_task(_clear_recording_after_delay())
    st = await tc.stop()
    await delayed

    assert (await nodes["control.start"].read_value()) is False
    assert st.depth == 8
    assert st.recording is False


@pytest.mark.asyncio
async def test_fetch_linear(trace_server):
    client, nodes, resolve_map = trace_server
    tc = _make_client(client, resolve_map, fetch_chunk=2)

    await _set(nodes["status.writeIdx"], 5, ua.VariantType.Int32)
    await _set(nodes["status.wrapped"], False, ua.VariantType.Boolean)
    await _set(nodes["status.sampleCount"], 5, ua.VariantType.Int32)
    await _set(nodes["status.cycleTimeMs"], 5.0, ua.VariantType.Float)
    await nodes["sampleCycles"].write_value([1, 2, 3, 4, 5, 0, 0, 0], varianttype=ua.VariantType.UInt32)
    await nodes["posX"].write_value(
        [0.1, 0.2, 0.3, 0.4, 0.5, 0.0, 0.0, 0.0], varianttype=ua.VariantType.Float
    )

    rec = await tc.fetch()

    assert rec.columns["posX"] == pytest.approx([0.1, 0.2, 0.3, 0.4, 0.5])
    assert rec.sample_cycles == [1, 2, 3, 4, 5]
    assert rec.t_rel_s == pytest.approx([0.005, 0.010, 0.015, 0.020, 0.025])
    assert rec.meta["wrapped"] is False


@pytest.mark.asyncio
async def test_fetch_wrapped_reorders(trace_server):
    client, nodes, resolve_map = trace_server
    tc = _make_client(client, resolve_map, fetch_chunk=3)

    await _set(nodes["status.writeIdx"], 3, ua.VariantType.Int32)
    await _set(nodes["status.wrapped"], True, ua.VariantType.Boolean)
    await _set(nodes["status.sampleCount"], 11, ua.VariantType.Int32)
    await _set(nodes["status.cycleTimeMs"], 5.0, ua.VariantType.Float)
    await nodes["sampleCycles"].write_value([9, 10, 11, 4, 5, 6, 7, 8], varianttype=ua.VariantType.UInt32)
    await nodes["posX"].write_value(
        [0.9, 1.0, 1.1, 0.4, 0.5, 0.6, 0.7, 0.8], varianttype=ua.VariantType.Float
    )

    rec = await tc.fetch()

    assert rec.sample_cycles == [4, 5, 6, 7, 8, 9, 10, 11]
    assert rec.columns["posX"] == pytest.approx([0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1])
    assert rec.meta["wrapped"] is True


@pytest.mark.asyncio
async def test_save_csv_and_meta(trace_server, tmp_path):
    client, nodes, resolve_map = trace_server
    tc = _make_client(client, resolve_map)

    await _set(nodes["status.writeIdx"], 3, ua.VariantType.Int32)
    await _set(nodes["status.wrapped"], False, ua.VariantType.Boolean)
    await _set(nodes["status.sampleCount"], 3, ua.VariantType.Int32)
    await _set(nodes["status.cycleTimeMs"], 10.0, ua.VariantType.Float)
    await nodes["sampleCycles"].write_value([1, 2, 3, 0, 0, 0, 0, 0], varianttype=ua.VariantType.UInt32)
    await nodes["posX"].write_value([0.1, 0.2, 0.3, 0, 0, 0, 0, 0], varianttype=ua.VariantType.Float)
    await nodes["flag"].write_value(
        [True, False, True, False, False, False, False, False],
        varianttype=ua.VariantType.Boolean,
    )

    rec = await tc.fetch()
    out_path = tmp_path / "trace.csv"
    rec.save(out_path)

    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "t_rel_s,sample_cycles,posX,flag"
    assert len(lines) == 1 + 3

    meta_path = tmp_path / "trace.csv.meta.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["depth"] == 8
    assert meta["cycle_time_ms"] == 10.0
    assert "started_at_iso" in meta
