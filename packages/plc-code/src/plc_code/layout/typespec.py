"""Parse the data-type strings the SCL parser emits into a structured spec."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_ARRAY_RE = re.compile(r"^Array\[(?P<dims>[^\]]+)\]\s*of\s+(?P<elem>.+)$", re.IGNORECASE)
_DIM_RE = re.compile(r"^\s*(-?\d+)\s*\.\.\s*(-?\d+)\s*$")
_STRING_RE = re.compile(r"^(?P<base>W?String)(?:\[(?P<len>\d+)\])?$", re.IGNORECASE)

DEFAULT_STRING_LENGTH = 254


@dataclass(frozen=True)
class TypeSpec:
    """A declared type: base name, array dimensions, string length, inline-struct flag.

    Attributes
    ----------
    base : str
        The base type name (e.g., "Int", "String", "typeMotor").
    dims : tuple[tuple[int, int], ...]
        Array dimensions as tuples of (lower_bound, upper_bound), or empty if not an array.
    string_length : int | None
        For String/WString types, the length (or None for non-string types).
    is_struct : bool
        Whether the type is declared as "Struct".
    """

    base: str
    dims: tuple[tuple[int, int], ...] = ()
    string_length: int | None = None
    is_struct: bool = False

    @property
    def element_count(self) -> int:
        """Total number of array elements (or 1 if not an array).

        Returns
        -------
        int
            The product of (upper_bound - lower_bound + 1) for each dimension,
            or 1 if not an array.
        """
        return math.prod(hi - lo + 1 for lo, hi in self.dims) if self.dims else 1

    @property
    def is_array(self) -> bool:
        """Whether this type is an array.

        Returns
        -------
        bool
            True if dims is non-empty, False otherwise.
        """
        return bool(self.dims)


def parse_type_spec(text: str) -> TypeSpec:
    """Parse data-type strings: scalar, UDT, String, Array, Struct.

    Handles formats like "Int", "_.typeX", '"typeX"', "String[16]", "Array[0..7] of DInt",
    "Struct", and "Array[1..2, 0..3] of String[4]".

    Parameters
    ----------
    text : str
        The type specification text to parse.

    Returns
    -------
    TypeSpec
        A TypeSpec with base name, array dimensions, string length, and struct flag.
    """
    text = text.strip()
    match = _ARRAY_RE.match(text)
    if match:
        dims = tuple(_parse_dim(d) for d in match.group("dims").split(","))
        inner = parse_type_spec(match.group("elem"))
        return TypeSpec(
            base=inner.base, dims=dims, string_length=inner.string_length, is_struct=inner.is_struct
        )
    if text.lower() == "struct":
        return TypeSpec(base="Struct", is_struct=True)
    string = _STRING_RE.match(text)
    if string:
        base = "WString" if string.group("base").lower().startswith("w") else "String"
        length = int(string.group("len")) if string.group("len") else DEFAULT_STRING_LENGTH
        return TypeSpec(base=base, string_length=length)
    if text.startswith("_."):
        text = text[2:]
    return TypeSpec(base=text.strip('"'))


def _parse_dim(text: str) -> tuple[int, int]:
    """Parse a single array dimension (e.g., "0..7" or "1..2").

    Parameters
    ----------
    text : str
        The dimension text (lower..upper).

    Returns
    -------
    tuple[int, int]
        A tuple of (lower_bound, upper_bound).

    Raises
    ------
    ValueError
        If the text does not match the expected format.
    """
    match = _DIM_RE.match(text)
    if match is None:
        raise ValueError(f"cannot parse array dimension {text!r}")
    return int(match.group(1)), int(match.group(2))
