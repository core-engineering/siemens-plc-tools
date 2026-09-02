"""Byte/bit layout of non-optimized (standard access) data blocks."""

from plc_code.layout.registry import TypeRegistry, UnknownTypeError, normalize_type_name
from plc_code.layout.sizes import ElementarySize, elementary_size
from plc_code.layout.typespec import TypeSpec, parse_type_spec

__all__ = [
    "ElementarySize",
    "TypeSpec",
    "TypeRegistry",
    "UnknownTypeError",
    "elementary_size",
    "normalize_type_name",
    "parse_type_spec",
]
