"""PLC SCL: Code analysis and documentation for TIA Portal V21 SCL exports.

This package provides tools to parse TIA Portal V21 text exports (.s7dcl files),
run quality analysis, and generate professional documentation.

Example
-------
>>> from plc_code import parse_scl_file
>>> block = parse_scl_file(Path("./MyBlock.s7dcl"))
"""

__version__ = "0.4.0"
__all__ = [
    "__version__",
]
