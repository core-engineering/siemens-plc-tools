"""Tests for ModbusConfig.from_dict."""

from __future__ import annotations

import pytest

from plc_modbus.config import ModbusConfig


class TestModbusConfigFromDict:
    def test_minimal(self) -> None:
        cfg = ModbusConfig.from_dict({"host": "192.168.1.50"})
        assert cfg.host == "192.168.1.50"
        assert cfg.port == 502
        assert cfg.unit_id == 1
        assert cfg.timeout_s == 5.0

    def test_full(self) -> None:
        cfg = ModbusConfig.from_dict({"host": "10.0.0.1", "port": 1502, "unit_id": 7, "timeout_s": 2.5})
        assert cfg == ModbusConfig(host="10.0.0.1", port=1502, unit_id=7, timeout_s=2.5)

    def test_missing_host_raises(self) -> None:
        with pytest.raises(ValueError, match="ModbusConfig requires a 'host'"):
            ModbusConfig.from_dict({"port": 502})

    def test_string_port_coerced(self) -> None:
        # YAML may give str even for numeric fields; we coerce.
        cfg = ModbusConfig.from_dict({"host": "x", "port": "502"})
        assert cfg.port == 502

    def test_immutable(self) -> None:
        cfg = ModbusConfig(host="x")
        with pytest.raises((AttributeError, TypeError)):
            cfg.host = "y"  # type: ignore[misc]
