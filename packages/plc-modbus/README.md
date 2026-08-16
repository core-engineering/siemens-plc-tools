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

- step: modbus_read
  description: "Scan the interface block to map its layout"
  register: "HOLDING:0"
  count: 20               # HOLDING:0 .. HOLDING:19, one request
  dtype: uint16
```

`modbus_read` only logs; it never fails. With `count > 1` the report carries one
entry per register, keyed by that register's own spec (`HOLDING:0`, `HOLDING:1`,
...), which is what makes it useful for mapping an unknown layout.

`count` must be at least 1, and must be 1 for a `AREA:N/B` bit spec — a range of
bit selections has no meaning. Both are rejected with an explicit error rather
than silently adjusted.

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
    # Raw, address-based reads
    regs = await mb.read_holding_registers(address=0, count=10)   # -> list[int]

    # Spec-based reads
    bit = await mb.read_register_at("HOLDING:0/6")                # -> bool
    temp = await mb.read_register_at("HOLDING:4", dtype="int16")  # -> int

    # A consecutive range, keyed by each register's own spec
    block = await mb.read_register_block("HOLDING:0", 20)
    # {"HOLDING:0": 4, "HOLDING:1": 0, ...}
```
