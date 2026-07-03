"""IndexRange array reads against an in-process asyncua server."""

from __future__ import annotations

import pytest
import pytest_asyncio
from asyncua import Server, ua

from plc_core.opcua.client import OpcUaClient
from plc_core.opcua.config import OpcUaConfig

ENDPOINT = "opc.tcp://127.0.0.1:48440/trace-test/"


def _patch_index_range_support(server: Server) -> None:
    """Make the in-process test server honor ``ReadValueId.IndexRange``.

    The bundled asyncua in-memory ``Server`` ignores ``IndexRange`` on Read
    requests entirely (see ``asyncua.server.address_space.AttributeService.
    read``, which only forwards ``NodeId``/``AttributeId``) — a known gap in
    the test-only server implementation. Real OPC UA servers, including the
    target S7-1500, honor it. Patch the read path here so these tests
    exercise the client's IndexRange request end-to-end; production code is
    untouched.
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
    """Return a *new* DataValue sliced to ``index_range``.

    ``read_attribute_value`` returns the live stored object, not a copy —
    mutating it in place would permanently shrink the node's value. An
    out-of-range request (either bound past the end of the array) mimics a
    spec-compliant server's ``BadIndexRangeNoData`` response, letting tests
    exercise the client's bad-StatusCode branch end-to-end.
    """
    if data_value.Value is None or not isinstance(data_value.Value.Value, list):
        return data_value
    values = data_value.Value.Value
    if ":" in index_range:
        lo_s, hi_s = index_range.split(":")
        lo, hi = int(lo_s), int(hi_s)
        if lo >= len(values) or hi >= len(values):
            return ua.DataValue(StatusCode=ua.StatusCode(ua.StatusCodes.BadIndexRangeNoData))
        sliced = values[lo : hi + 1]
    else:
        idx = int(index_range)
        if idx >= len(values):
            return ua.DataValue(StatusCode=ua.StatusCode(ua.StatusCodes.BadIndexRangeNoData))
        sliced = values[idx]
    new_variant = ua.Variant(sliced, data_value.Value.VariantType)
    return ua.DataValue(
        Value=new_variant,
        StatusCode=data_value.StatusCode,
        SourceTimestamp=data_value.SourceTimestamp,
        ServerTimestamp=data_value.ServerTimestamp,
    )


@pytest_asyncio.fixture()
async def server_with_array():
    server = Server()
    await server.init()
    server.set_endpoint(ENDPOINT)
    _patch_index_range_support(server)
    idx = await server.register_namespace("urn:trace-test")
    obj = await server.nodes.objects.add_object(idx, "TraceData")
    arr = await obj.add_variable(idx, "posX", [float(i) for i in range(100)])
    async with server:
        yield arr.nodeid.to_string()


@pytest.mark.asyncio
async def test_read_array_range_slices(server_with_array):
    node_id = server_with_array
    client = OpcUaClient(OpcUaConfig(endpoint=ENDPOINT))
    await client.connect()
    try:
        chunk = await client.read_array_range(node_id, 10, 19)
        assert chunk == [float(i) for i in range(10, 20)]
        single = await client.read_array_range(node_id, 5, 5)
        assert single == [5.0]
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_read_array_range_full_span(server_with_array):
    node_id = server_with_array
    client = OpcUaClient(OpcUaConfig(endpoint=ENDPOINT))
    await client.connect()
    try:
        full = await client.read_array_range(node_id, 0, 99)
        assert full == [float(i) for i in range(100)]
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_read_array_range_bad_status_raises(server_with_array):
    node_id = server_with_array
    client = OpcUaClient(OpcUaConfig(endpoint=ENDPOINT))
    await client.connect()
    try:
        with pytest.raises(RuntimeError, match="Array range read failed"):
            await client.read_array_range(node_id, 100, 105)
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_read_array_range_not_connected_raises():
    client = OpcUaClient(OpcUaConfig(endpoint=ENDPOINT))
    with pytest.raises(RuntimeError, match="Not connected"):
        await client.read_array_range("ns=2;i=1", 0, 1)
