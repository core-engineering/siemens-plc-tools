# plc-sim

OPC UA simulation interface for live PLC interaction and integration testing.

## Features

- Connect to PLC OPC UA servers (S7-1500, S7-1518RH)
- Browse node tree (variables, data blocks)
- Read/write variable values
- Live monitoring with subscriptions
- Web interface for interactive testing
- CLI tools for scripted interaction

## Usage

```bash
# CLI
plc sim connect
plc sim browse
plc sim read "ns=3;s=ProcessData.DO_Valve1"
plc sim write "ns=3;s=ProcessData.DI_Sensor1" true
plc sim monitor "ns=3;s=ProcessData.DO_Valve1"

# Web interface
plc sim web
```

## Configuration

Add a `sim:` section to your `plc.yaml`:

```yaml
sim:
  endpoint: opc.tcp://192.168.1.50:4840
  interface: Simulation
  namespaces:
    - ProcessData
    - SafetyData
```

## Modbus testing (optional)

Add a `sim.modbus:` block to enable the `modbus_read`, `modbus_assert` and
`modbus_wait_until` step types in YAML scenarios. They let you validate
the PLC's Modbus interface (DB serializer + holding-register layout)
directly over TCP, without going through OPC UA.

```yaml
sim:
  endpoint: opc.tcp://192.168.1.50:4840
  modbus:
    host: 192.168.1.50
    port: 502         # default 502
    unit_id: 1        # default 1
    timeout_s: 5      # default 5
```

Example scenario step:

```yaml
- step: write
  values:
    ProcessData.pump.input.oilTemperature: 25000

- step: wait_until
  path: ProcessData.pump.status.oilHighTemperatureAlarmState
  value: 1

- step: modbus_assert
  description: "HPU_HIGH_OIL_TEMPERATURE register reflects the alarm"
  values:
    "HOLDING:0/6": true   # bit 6 of holding register 0
```

Register format: `HOLDING:N`, `INPUT:N`, `COIL:N`, `DISCRETE:N`, plus
`HOLDING:N/B` / `INPUT:N/B` for bit access. See `plc-modbus/README.md` for
the full reference.
