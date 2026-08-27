# siemens-plc-tools

[![CI](https://github.com/core-engineering/siemens-plc-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/core-engineering/siemens-plc-tools/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
![Version](https://img.shields.io/badge/version-0.4.0-informational)

A toolkit for Siemens TIA Portal V21 (S7-1500) automation projects: parse and
analyze SCL, generate documentation, transpile SCL to Python for unit testing,
manage I/O lists, monitor industrial networks, and run OPC UA / Modbus /
supervision integration tests.

## Packages

| Package | Purpose |
|---------|---------|
| **plc-core** | Shared config, S7/IOL models, CLI framework, reporting, OPC UA client, scenario test framework |
| **plc-code** | SCL parser, doc generation (MkDocs/Draw.io/PDF), quality analysis, SCL→Python transpiler + pytest harness |
| **plc-iol** | I/O list import/export (XML/Excel), comparison and validation |
| **plc-modbus** | Async Modbus TCP client with YAML step types for integration tests |
| **plc-net** | Industrial network monitoring (scapy) + OPC UA dissector |
| **plc-sim** | OPC UA simulation interface, CLI, web UI, integration-test runner |
| **plc-sup** | Supervision pipeline integration tests (OPC UA → Redis → TimescaleDB → API) |
| **plc-hw** | TIA Portal hardware-parameter dump via Openness, semantic diff, baseline check |

## Install

```bash
# whole workspace (development)
uv sync --all-extras --all-packages

# or a single capability
uv pip install -e packages/plc-code
```

The root package also exposes capability extras (`core`, `code`, `iol`,
`sim`, `sup`, `net`, `hw`, `trace`, `all`) for selective installs, e.g.
`uv sync --extra code`.

## Quickstart

See [`examples/demo-project/`](examples/demo-project/) for a runnable example:

```bash
cd examples/demo-project
plc code lint
plc code docs
plc code test --coverage         # block tests + SCL line coverage
plc code diff old-export/ new-export/   # semantic diff, formatting-blind
plc code xref --tags "PLC tags" "Program blocks"   # unused / undeclared I/O
```

### `plc hw` — hardware configuration

An AutomationML export versions devices, order numbers, topology, I/O addresses
and F-addresses. It carries no module parameters, no CPU settings, no PROFINET
timing and no safety signatures. `plc hw` reads those through TIA Openness.

```bash
plc hw dump --out deliverables/hardware-parameters   # Windows + TIA
plc hw diff OLD NEW                                  # anywhere
plc hw check                                         # baseline gate for a FAT
```

The package never writes to TIA.

## Documentation
Built with MkDocs (`uv run mkdocs serve`).

## Contributing
See [CONTRIBUTING.md](CONTRIBUTING.md). Licensed under the [MIT License](LICENSE).
