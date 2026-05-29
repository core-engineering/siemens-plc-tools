# PLC Code

SCL code analysis, documentation generation, and quality tools for TIA Portal V21.

## Features

- **Parser**: Tokenize and parse SCL source files (.s7dcl)
- **Extractor**: Extract header metadata, interface documentation, and UDT fields
- **Generator**: Generate Markdown documentation with cross-references
- **Analyzer**: Call graphs, type graphs, state machines, and quality analysis
- **Executor**: Transpile SCL to Python for unit testing
- **Testing**: Unit test framework for PLC blocks

## Installation

```bash
pip install plc-code
```

Or as part of plc-tools:

```bash
pip install plc-tools[scl]
```

## Usage

### CLI Commands

```bash
# Initialize a project
plc scl init --name "My Project" --code "PRJ"

# Show project status
plc scl status

# Run quality analysis
plc scl lint
plc scl lint path/to/file.s7dcl
plc scl lint --format json

# Generate documentation
plc scl docs
plc scl docs --serve

# Export PDF report
plc scl export pdf -o report.pdf

# Run tests
plc scl test
plc scl test -v
```

### Python API

```python
from plc_code.parser import parse_scl_file
from plc_code.extractor import extract_header, extract_interface
from plc_code.generator import generate_markdown

# Parse a block
block = parse_scl_file(Path("MyBlock.s7dcl"))

# Extract documentation
header = extract_header(block)
interface = extract_interface(block)

# Generate markdown
markdown = generate_markdown(block)
```

## License

MIT
