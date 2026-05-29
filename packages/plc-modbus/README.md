# plc-modbus

Modbus TCP client for PLC integration testing.

This package provides an async `ModbusClient` and pairs with `plc-core`'s test
runner to add 3 new YAML step types: `modbus_read`, `modbus_assert`,
`modbus_wait_until`.

The primary use case is validating an interface DB → serializer → Modbus server
chain on a PLC: stimulate process inputs through the existing OPC UA test runner,
then read holding registers via Modbus TCP to verify the operational signal
mapping.

## Install

```bash
uv pip install -e packages/plc-modbus
```

## Usage in a test scenario

Add the `modbus` block to `plc.yaml`:

```yaml
sim:
  endpoint: opc.tcp://192.168.1.50:4840
  modbus:
    host: 192.168.1.50
    port: 502
    unit_id: 1
    timeout_s: 5
```

Then in a YAML scenario:

```yaml
- step: write
  values:
    SensorData.pump.input.temperature: 25000

- step: wait_until
  path: SensorData.pump.status.highTemperatureAlarmState
  value: 1

- step: modbus_assert
  description: "PUMP_HIGH_TEMPERATURE register reflects the alarm"
  values:
    "HOLDING:0/6": true   # bit 6 of holding register 0
```

## Register format

The `register` field uses one of:

| Format | Meaning |
|---|---|
| `HOLDING:N` | Holding register N (read whole 16-bit Word) |
| `INPUT:N` | Input register N |
| `HOLDING:N/B` | Bit B of holding register N (B = 0..15) |
| `COIL:N` | Coil N (Boolean) |
| `DISCRETE:N` | Discrete input N (Boolean) |

The optional `dtype` selects the decoding (`uint16` default, also `int16`,
`bool`, `word`).

## API

```python
from plc_modbus import ModbusClient, ModbusConfig

async with ModbusClient(ModbusConfig(host="192.168.1.50")) as mb:
    regs = await mb.read_holding_registers(address=0, count=10)
    bit = await mb.read_bit("HOLDING:0/6")
```
