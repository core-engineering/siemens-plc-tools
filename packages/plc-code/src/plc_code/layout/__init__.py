"""Byte/bit layout of non-optimized (standard access) data blocks."""

from plc_code.layout.sizes import ElementarySize, elementary_size
from plc_code.layout.typespec import TypeSpec, parse_type_spec

__all__ = ["ElementarySize", "TypeSpec", "elementary_size", "parse_type_spec"]
