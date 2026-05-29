# plc-net

Industrial network monitoring for PLC environments — part of the
[siemens-plc-tools](../../README.md) monorepo.

Live packet capture with protocol classification (OPC UA, S7comm, Modbus, NTP,
Syslog, SSH, …) and a binary OPC UA dissector, with Rich live dashboards.

## Install

```bash
uv pip install -e packages/plc-net      # from the monorepo
```

## Usage

```bash
plc net monitor      # live multi-protocol traffic dashboard
plc net opcua        # OPC UA service dissection dashboard
```

> **Requires `root`/`sudo`** for raw-socket packet capture (scapy).

## Dependencies
scapy, rich, click.
