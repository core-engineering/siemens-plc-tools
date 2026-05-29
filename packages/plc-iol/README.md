# PLC IOL

I/O list management, TAGS/IOL comparison, and validation for PLC projects.

## Features

- **Import**: Load I/O data from S7-1500 XML exports or Excel files
- **Export**: Generate S7-1500 compatible XML tags or IOL Excel files
- **Compare**: Detect differences between TAGS and IOL sources
- **Validate**: Check naming conventions, address conflicts, and consistency

## Installation

```bash
pip install plc-iol
```

Or as part of plc-tools:

```bash
pip install plc-tools[iol]
```

## Usage

### CLI Commands

```bash
# Initialize a project
plc iol init --name "My Project" --code "PRJ"

# Show project status
plc iol status

# Import from S7-1500 XML
plc iol import tags --path ./tags

# Import from IOL Excel
plc iol import excel --path ./iol.xlsx

# Export to S7-1500 XML
plc iol export tags -o ./output

# Export to IOL Excel
plc iol export excel -o ./output.xlsx

# List I/O points
plc iol list --category DI --group ARM1

# Compare sources
plc iol compare --source tags --target iol

# Validate database
plc iol validate --check-consistency
```

### Python API

```python
from plc_iol import IOPoint, IODatabase, IOCategory, DataType
from plc_iol.importers import XMLImporter, ExcelImporter
from plc_iol.exporters import XMLExporter, ExcelExporter

# Create a database
db = IODatabase()

# Add an I/O point
point = IOPoint(
    mnemonic="DI_PUMP_START",
    signal_name="Pump Start Button",
    io_category=IOCategory.DI,
    plc_address="%I1.0",
)
db.add(point)

# Import from XML
importer = XMLImporter()
db = importer.import_file(Path("tags.xml"))

# Export to Excel
exporter = ExcelExporter()
exporter.export(db, Path("iol.xlsx"))
```

## License

MIT
