# plc-sup

Supervision pipeline testing for PLC systems — part of the
[siemens-plc-tools](../../README.md) monorepo.

End-to-end integration testing of the OPC UA → Redis → TimescaleDB → REST API
supervision pipeline. Scenario logic (streams, SQL queries, endpoints) lives in
user-provided YAML scenarios.

## Install

```bash
uv pip install -e packages/plc-sup
```

## Usage

```bash
plc sup test         # run supervision integration scenarios from plc.yaml
```

> **Requires live infrastructure** referenced in `plc.yaml`: an OPC UA server,
> Redis, a TimescaleDB/PostgreSQL instance, and (optionally) SSH access to the
> deployment host. Configure `infra.expected_containers` and connection URLs in
> the `sup:` section of `plc.yaml`.

## Dependencies
plc-core[opcua], redis, psycopg, httpx, msgpack.
