"""Byte/bit layout of non-optimized (standard access) data blocks."""

from plc_code.layout.api import OptimizedBlockError, compute_layout
from plc_code.layout.registry import TypeRegistry, UnknownTypeError, normalize_type_name
from plc_code.layout.rules import Layout, Member, layout_fields
from plc_code.layout.sizes import ElementarySize, elementary_size
from plc_code.layout.typespec import TypeSpec, parse_type_spec

__all__ = [
    "ElementarySize",
    "Layout",
    "Member",
    "OptimizedBlockError",
    "TypeSpec",
    "TypeRegistry",
    "UnknownTypeError",
    "compute_layout",
    "elementary_size",
    "layout_fields",
    "normalize_type_name",
    "parse_type_spec",
]
