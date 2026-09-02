"""Byte/bit layout of non-optimized (standard access) data blocks."""

from plc_code.layout.registry import TypeRegistry, UnknownTypeError, normalize_type_name
from plc_code.layout.rules import Layout, Member, layout_fields
from plc_code.layout.sizes import ElementarySize, elementary_size
from plc_code.layout.typespec import TypeSpec, parse_type_spec

__all__ = [
    "ElementarySize",
    "Layout",
    "Member",
    "TypeSpec",
    "TypeRegistry",
    "UnknownTypeError",
    "elementary_size",
    "layout_fields",
    "normalize_type_name",
    "parse_type_spec",
]
