"""Tests for ModbusClient using mocked pymodbus.

We mock ``pymodbus.client.AsyncModbusTcpClient`` rather than spinning up
a real server — the Modbus wire protocol is exercised by pymodbus itself,
our wrapper concerns are: dispatch to the right method, slave/timeout
plumbing, error wrapping, and address-spec routing.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from plc_modbus.client import (
    ModbusClient,
    ModbusConnectionError,
    ModbusReadError,
)
from plc_modbus.config import ModbusConfig


def _make_response(
    *, registers: list[int] | None = None, bits: list[bool] | None = None, error: bool = False
) -> MagicMock:
    """Build a fake pymodbus response object."""
    resp = MagicMock()
    resp.isError.return_value = error
    if registers is not None:
        resp.registers = registers
    if bits is not None:
        resp.bits = bits
    return resp


class FakePymodbusClient:
    """Stand-in for AsyncModbusTcpClient with controllable responses.

    Tests inject this via ``patch.object`` on
    ``plc_modbus.client.ModbusClient.connect``-time.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.connected = False
        self.host = kwargs.get("host")
        self.port = kwargs.get("port")
        self.timeout = kwargs.get("timeout")

        # Pre-canned responses (populated by tests)
        self.holding: dict[int, list[int]] = {}
        self.input: dict[int, list[int]] = {}
        self.coils: dict[int, list[bool]] = {}
        self.discrete: dict[int, list[bool]] = {}
        self.fail_on: set[str] = set()

        # Spy state
        self.last_call: tuple[str, dict[str, Any]] | None = None

    async def connect(self) -> bool:
        if "connect" in self.fail_on:
            return False
        self.connected = True
        return True

    def close(self) -> None:
        self.connected = False

    async def read_holding_registers(self, address: int, count: int, device_id: int) -> MagicMock:
        self.last_call = (
            "read_holding_registers",
            {"address": address, "count": count, "device_id": device_id},
        )
        if "read_holding_registers" in self.fail_on:
            return _make_response(registers=[], error=True)
        return _make_response(registers=self.holding.get(address, [0] * count))

    async def read_input_registers(self, address: int, count: int, device_id: int) -> MagicMock:
        self.last_call = (
            "read_input_registers",
            {"address": address, "count": count, "device_id": device_id},
        )
        return _make_response(registers=self.input.get(address, [0] * count))

    async def read_coils(self, address: int, count: int, device_id: int) -> MagicMock:
        self.last_call = ("read_coils", {"address": address, "count": count, "device_id": device_id})
        return _make_response(bits=self.coils.get(address, [False] * count))

    async def read_discrete_inputs(self, address: int, count: int, device_id: int) -> MagicMock:
        self.last_call = (
            "read_discrete_inputs",
            {"address": address, "count": count, "device_id": device_id},
        )
        return _make_response(bits=self.discrete.get(address, [False] * count))


@pytest.fixture
def fake_client_class() -> Any:
    """Patch AsyncModbusTcpClient with FakePymodbusClient."""
    with patch("pymodbus.client.AsyncModbusTcpClient", FakePymodbusClient):
        yield FakePymodbusClient


class TestConnectDisconnect:
    async def test_context_manager(self, fake_client_class: Any) -> None:
        cfg = ModbusConfig(host="x")
        async with ModbusClient(cfg) as mb:
            assert mb.connected is True
        assert mb.connected is False

    async def test_failed_connect_raises(self) -> None:
        with patch("pymodbus.client.AsyncModbusTcpClient") as mock_cls:
            instance = FakePymodbusClient(host="x")
            instance.fail_on = {"connect"}
            mock_cls.return_value = instance
            with pytest.raises(ModbusConnectionError, match="Failed to connect"):
                async with ModbusClient(ModbusConfig(host="x")):
                    pass

    async def test_disconnect_idempotent(self, fake_client_class: Any) -> None:
        mb = ModbusClient(ModbusConfig(host="x"))
        await mb.connect()
        await mb.disconnect()
        await mb.disconnect()  # second call is fine
        assert mb.connected is False

    async def test_passes_host_port_timeout(self, fake_client_class: Any) -> None:
        cfg = ModbusConfig(host="10.0.0.1", port=1502, unit_id=7, timeout_s=2.5)
        async with ModbusClient(cfg) as mb:
            assert mb._client.host == "10.0.0.1"
            assert mb._client.port == 1502
            assert mb._client.timeout == 2.5


class TestReadHoldingRegisters:
    async def test_returns_register_list(self, fake_client_class: Any) -> None:
        async with ModbusClient(ModbusConfig(host="x", unit_id=3)) as mb:
            mb._client.holding[10] = [42, 99, 7]
            assert await mb.read_holding_registers(10, 3) == [42, 99, 7]
            assert mb._client.last_call == (
                "read_holding_registers",
                {"address": 10, "count": 3, "device_id": 3},
            )

    async def test_error_response_raises(self, fake_client_class: Any) -> None:
        async with ModbusClient(ModbusConfig(host="x")) as mb:
            mb._client.fail_on = {"read_holding_registers"}
            with pytest.raises(ModbusReadError, match="returned error"):
                await mb.read_holding_registers(0, 1)

    async def test_not_connected_raises(self) -> None:
        mb = ModbusClient(ModbusConfig(host="x"))
        with pytest.raises(ModbusConnectionError, match="not connected"):
            await mb.read_holding_registers(0, 1)


class TestReadCoilsAndDiscretes:
    async def test_coils(self, fake_client_class: Any) -> None:
        async with ModbusClient(ModbusConfig(host="x")) as mb:
            mb._client.coils[5] = [True, False, True]
            assert await mb.read_coils(5, 3) == [True, False, True]

    async def test_discrete(self, fake_client_class: Any) -> None:
        async with ModbusClient(ModbusConfig(host="x")) as mb:
            mb._client.discrete[5] = [False, True]
            assert await mb.read_discrete_inputs(5, 2) == [False, True]

    async def test_coils_truncated_to_count(self, fake_client_class: Any) -> None:
        # pymodbus may return more bits than requested (round to byte).
        async with ModbusClient(ModbusConfig(host="x")) as mb:
            mb._client.coils[0] = [True, False, True, False, True, False, True, False]
            assert await mb.read_coils(0, 3) == [True, False, True]


class TestReadRegisterAt:
    """The string-based dispatch — registers, bits, coils, discretes."""

    async def test_holding_uint16(self, fake_client_class: Any) -> None:
        async with ModbusClient(ModbusConfig(host="x")) as mb:
            mb._client.holding[42] = [12345]
            assert await mb.read_register_at("HOLDING:42") == 12345

    async def test_holding_int16_negative(self, fake_client_class: Any) -> None:
        async with ModbusClient(ModbusConfig(host="x")) as mb:
            mb._client.holding[42] = [0xFFFF]
            assert await mb.read_register_at("HOLDING:42", dtype="int16") == -1

    async def test_input_register(self, fake_client_class: Any) -> None:
        async with ModbusClient(ModbusConfig(host="x")) as mb:
            mb._client.input[5] = [777]
            assert await mb.read_register_at("INPUT:5") == 777

    async def test_holding_bit_set(self, fake_client_class: Any) -> None:
        # 0b0000_0000_0100_0000 = bit 6 set
        async with ModbusClient(ModbusConfig(host="x")) as mb:
            mb._client.holding[0] = [0b0100_0000]
            assert await mb.read_register_at("HOLDING:0/6") is True
            assert await mb.read_register_at("HOLDING:0/7") is False

    async def test_holding_bit_high_word(self, fake_client_class: Any) -> None:
        # MSB
        async with ModbusClient(ModbusConfig(host="x")) as mb:
            mb._client.holding[1] = [0x8000]
            assert await mb.read_register_at("HOLDING:1/15") is True
            assert await mb.read_register_at("HOLDING:1/14") is False

    async def test_coil(self, fake_client_class: Any) -> None:
        async with ModbusClient(ModbusConfig(host="x")) as mb:
            mb._client.coils[3] = [True]
            assert await mb.read_register_at("COIL:3") is True

    async def test_discrete(self, fake_client_class: Any) -> None:
        async with ModbusClient(ModbusConfig(host="x")) as mb:
            mb._client.discrete[10] = [False]
            assert await mb.read_register_at("DISCRETE:10") is False
