# PLC Core

Core library for PLC Tools - shared utilities, models, and configuration.

## Features

- **Configuration Framework**: YAML-based configuration loading and management
- **Shared Models**: PLCAddress, DataType, IOCategory enumerations
- **CLI Utilities**: Plugin discovery and Rich console output helpers
- **Reporting Framework**: Severity, Finding, Report models and Markdown/PDF export

## Installation

```bash
pip install plc-core
```

Or as part of plc-tools:

```bash
pip install plc-tools[core]
```

## Usage

```python
from plc_core.config import find_config_file, load_yaml
from plc_core.models import PLCAddress, DataType, IOCategory
from plc_core.reporting import Severity, Finding, Report

# Load configuration
config_path = find_config_file()
if config_path:
    data = load_yaml(config_path)

# Parse PLC addresses
addr = PLCAddress.from_s7_format("%I1.0")
print(addr.to_iol_format())  # E 1.0

# Create findings
finding = Finding(
    title="Variable naming",
    severity=Severity.WARNING,
    message="Variable name does not follow convention",
    location="MyBlock:15",
)
```

## License

MIT
