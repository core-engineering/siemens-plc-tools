"""SCL type system mapping to Python types.

This module provides mappings from TIA Portal SCL data types to their
Python equivalents, including default value generation and type conversion.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class SCLType(Enum):
    """Enumeration of supported SCL data types."""

    # Boolean
    BOOL = "Bool"

    # Integer types (signed)
    SINT = "SInt"  # 8-bit signed
    INT = "Int"  # 16-bit signed
    DINT = "DInt"  # 32-bit signed
    LINT = "LInt"  # 64-bit signed

    # Integer types (unsigned)
    USINT = "USInt"  # 8-bit unsigned
    UINT = "UInt"  # 16-bit unsigned
    UDINT = "UDInt"  # 32-bit unsigned
    ULINT = "ULInt"  # 64-bit unsigned

    # Floating point
    REAL = "Real"  # 32-bit float
    LREAL = "LReal"  # 64-bit float

    # Bit string types
    BYTE = "Byte"  # 8-bit
    WORD = "Word"  # 16-bit
    DWORD = "DWord"  # 32-bit
    LWORD = "LWord"  # 64-bit

    # String types
    STRING = "String"
    CHAR = "Char"

    # Time types
    TIME = "Time"
    DATE = "Date"
    TIME_OF_DAY = "Time_of_day"
    DATE_AND_TIME = "Date_and_time"

    # Timer types
    TON_TIME = "TON_TIME"
    TOF_TIME = "TOF_TIME"
    TP_TIME = "TP_TIME"

    # Special
    VOID = "Void"
    ARRAY = "Array"
    UDT = "UDT"  # User-defined type


@dataclass
class TypeInfo:
    """Information about an SCL type and its Python mapping.

    Attributes
    ----------
    scl_type : SCLType
        The SCL type category.
    python_type : type
        The corresponding Python type.
    default_factory : Callable[[], Any]
        Factory function to create default values.
    type_hint : str
        Python type hint string for code generation.
    """

    scl_type: SCLType
    python_type: type
    default_factory: Callable[[], Any]
    type_hint: str


@dataclass
class ArrayTypeInfo:
    """Information about an SCL array type.

    Attributes
    ----------
    element_type : str
        The element type string.
    lower_bound : int
        Lower array index (first dimension).
    upper_bound : int
        Upper array index (first dimension, inclusive).
    dimensions : list[tuple[int, int]]
        List of (lo, hi) tuples, one per dimension. For a 1D array this is
        a single-element list; for 2D it has two entries, etc.
    size : int
        Total number of elements (product of all dimension sizes).
    symbolic_bounds : bool
        True when at least one bound is a named constant (e.g. ``_.AXIS_NUM_INDEX``)
        rather than an integer literal.  In that case the runtime default is a
        plain dict ``{}`` rather than a sized list, because the actual subscript
        access pattern (string vs integer) is unknown at transpile time and string-
        keyed dict access is the most common usage.
    """

    element_type: str
    lower_bound: int
    upper_bound: int
    dimensions: list[tuple[int, int]] = None  # type: ignore[assignment]
    symbolic_bounds: bool = False

    def __post_init__(self) -> None:
        """Initialise dimensions from lower/upper bound when not supplied."""
        if self.dimensions is None:
            self.dimensions = [(self.lower_bound, self.upper_bound)]

    @property
    def size(self) -> int:
        """Calculate total array size (product of all dimension sizes)."""
        total = 1
        for lo, hi in self.dimensions:
            total *= hi - lo + 1
        return total


# Type mapping table
TYPE_MAP: dict[str, TypeInfo] = {
    # Boolean
    "Bool": TypeInfo(SCLType.BOOL, bool, lambda: False, "bool"),
    # Signed integers
    "SInt": TypeInfo(SCLType.SINT, int, lambda: 0, "int"),
    "Int": TypeInfo(SCLType.INT, int, lambda: 0, "int"),
    "DInt": TypeInfo(SCLType.DINT, int, lambda: 0, "int"),
    "LInt": TypeInfo(SCLType.LINT, int, lambda: 0, "int"),
    # Unsigned integers
    "USInt": TypeInfo(SCLType.USINT, int, lambda: 0, "int"),
    "UInt": TypeInfo(SCLType.UINT, int, lambda: 0, "int"),
    "UDInt": TypeInfo(SCLType.UDINT, int, lambda: 0, "int"),
    "ULInt": TypeInfo(SCLType.ULINT, int, lambda: 0, "int"),
    # Floating point
    "Real": TypeInfo(SCLType.REAL, float, lambda: 0.0, "float"),
    "LReal": TypeInfo(SCLType.LREAL, float, lambda: 0.0, "float"),
    # Bit strings
    "Byte": TypeInfo(SCLType.BYTE, int, lambda: 0, "int"),
    "Word": TypeInfo(SCLType.WORD, int, lambda: 0, "int"),
    "DWord": TypeInfo(SCLType.DWORD, int, lambda: 0, "int"),
    "LWord": TypeInfo(SCLType.LWORD, int, lambda: 0, "int"),
    # Strings
    "String": TypeInfo(SCLType.STRING, str, lambda: "", "str"),
    "Char": TypeInfo(SCLType.CHAR, str, lambda: "", "str"),
    # Time types (stored as float seconds)
    "Time": TypeInfo(SCLType.TIME, float, lambda: 0.0, "float"),
    "Date": TypeInfo(SCLType.DATE, int, lambda: 0, "int"),
    "Time_of_day": TypeInfo(SCLType.TIME_OF_DAY, float, lambda: 0.0, "float"),
    "Date_and_time": TypeInfo(SCLType.DATE_AND_TIME, float, lambda: 0.0, "float"),
    # Void
    "Void": TypeInfo(SCLType.VOID, type(None), lambda: None, "None"),
}

# Regex patterns for type parsing
# Matches Array[lo1..hi1] of T  (1D)  OR  Array[lo1..hi1, lo2..hi2, ...] of T  (nD)
# The dimension list is captured as one group; individual (lo..hi) pairs are parsed separately.
ARRAY_PATTERN = re.compile(
    r"Array\s*\[([^\]]+)\]\s+of\s+(.+)",
    re.IGNORECASE,
)
# Pattern for each individual dimension specification: lo..hi
_DIM_PATTERN = re.compile(r"(-?\d+)\s*\.\.\s*(-?\d+)")
# Pattern for an open/dynamic dimension specification: * (Siemens VAR_IN_OUT open arrays)
_OPEN_DIM_PATTERN = re.compile(r"\*")
LIBRARY_TYPE_PATTERN = re.compile(r"^_\.(.+)$")
# Individual time component patterns (for combined formats)
TIME_COMPONENT_PATTERNS = [
    (re.compile(r"(\d+)ms", re.IGNORECASE), 0.001),  # milliseconds - check first
    (re.compile(r"(\d+)s", re.IGNORECASE), 1.0),  # seconds
    (re.compile(r"(\d+)m", re.IGNORECASE), 60.0),  # minutes
    (re.compile(r"(\d+)h", re.IGNORECASE), 3600.0),  # hours
    (re.compile(r"(\d+)d", re.IGNORECASE), 86400.0),  # days
]


class TypeMapper:
    """Maps SCL types to Python types and handles type operations.

    This class provides methods to parse SCL type strings, create default
    values, and convert literals to Python values.
    """

    def __init__(self, udt_registry: dict[str, Any] | None = None) -> None:
        """Initialize the type mapper.

        Parameters
        ----------
        udt_registry : dict[str, Any] | None
            Registry of user-defined types (UDTs) and their default factories.
        """
        self.udt_registry = udt_registry or {}

    def parse_type(self, type_str: str) -> TypeInfo | ArrayTypeInfo:
        """Parse an SCL type string and return type information.

        Parameters
        ----------
        type_str : str
            The SCL type string (e.g., "Bool", "Array[1..10] of Real").

        Returns
        -------
        TypeInfo | ArrayTypeInfo
            Type information for the given type string.

        Raises
        ------
        ValueError
            If the type string cannot be parsed.
        """
        type_str = type_str.strip()

        # Check for array type (1D or multi-dimensional)
        array_match = ARRAY_PATTERN.match(type_str)
        if array_match:
            dims_str = array_match.group(1)
            element_type = array_match.group(2).strip()
            # Parse each dimension: "lo..hi" separated by commas
            dimensions: list[tuple[int, int]] = [
                (int(m.group(1)), int(m.group(2))) for m in _DIM_PATTERN.finditer(dims_str)
            ]
            if not dimensions:
                # Check for open/dynamic array dimensions (Array[*] or Array[*, *] etc.)
                # These are used in VAR_IN_OUT for Siemens open arrays.
                # Count the number of "*" placeholders to determine dimensionality.
                open_dim_count = len(_OPEN_DIM_PATTERN.findall(dims_str))
                if open_dim_count > 0:
                    # Use (0, 0) as a sentinel; actual bounds come from the passed array
                    dimensions = [(0, 0)] * open_dim_count
                    lower, upper = dimensions[0]
                    return ArrayTypeInfo(
                        element_type=element_type,
                        lower_bound=lower,
                        upper_bound=upper,
                        dimensions=dimensions,
                    )
                # Check for symbolic array bounds (e.g. 0.._.AXIS_NUM_INDEX).
                # The ARRAY_PATTERN matched so this IS an array type, but the
                # bounds contain named constants rather than integer literals.
                # Count dimensions by counting ".." occurrences in dims_str and
                # use (0, 0) as placeholder (actual bounds are symbolic).
                symbolic_dim_count = dims_str.count("..")
                if symbolic_dim_count > 0:
                    dimensions = [(0, 0)] * symbolic_dim_count
                    lower, upper = dimensions[0]
                    return ArrayTypeInfo(
                        element_type=element_type,
                        lower_bound=lower,
                        upper_bound=upper,
                        dimensions=dimensions,
                        symbolic_bounds=True,
                    )
                # Truly malformed — fall through to unknown-type handling below
            else:
                lower, upper = dimensions[0]
                return ArrayTypeInfo(
                    element_type=element_type,
                    lower_bound=lower,
                    upper_bound=upper,
                    dimensions=dimensions,
                )

        # Check for library type (_.TypeName)
        lib_match = LIBRARY_TYPE_PATTERN.match(type_str)
        if lib_match:
            type_name = lib_match.group(1)
            if type_name in self.udt_registry:
                factory = self.udt_registry[type_name]
                return TypeInfo(SCLType.UDT, type, factory, type_name)
            # Return a placeholder for unknown UDTs
            return TypeInfo(SCLType.UDT, dict, dict, type_name)

        # Check for timer types
        if type_str == "TON_TIME":
            from plc_code.executor.timers import TON_TIME

            return TypeInfo(SCLType.TON_TIME, TON_TIME, TON_TIME, "TON_TIME")
        if type_str == "TOF_TIME":
            from plc_code.executor.timers import TOF_TIME

            return TypeInfo(SCLType.TOF_TIME, TOF_TIME, TOF_TIME, "TOF_TIME")
        if type_str == "TP_TIME":
            from plc_code.executor.timers import TP_TIME

            return TypeInfo(SCLType.TP_TIME, TP_TIME, TP_TIME, "TP_TIME")

        # Check standard type map
        if type_str in TYPE_MAP:
            return TYPE_MAP[type_str]

        # Unknown type - treat as UDT
        if type_str in self.udt_registry:
            factory = self.udt_registry[type_str]
            return TypeInfo(SCLType.UDT, type, factory, type_str)

        # Return dict placeholder for completely unknown types
        return TypeInfo(SCLType.UDT, dict, dict, type_str)

    def create_default(self, type_str: str) -> Any:
        """Create a default value for an SCL type.

        Parameters
        ----------
        type_str : str
            The SCL type string.

        Returns
        -------
        Any
            A default value appropriate for the type.
        """
        type_info = self.parse_type(type_str)

        if isinstance(type_info, ArrayTypeInfo):
            if len(type_info.dimensions) == 1:
                lo, hi = type_info.dimensions[0]
                element_default = self.create_default(type_info.element_type)
                # Allocate hi+1 elements when lo>0 so 1-based SCL index access
                # (e.g. arr[1]..arr[hi]) works as direct Python list indexing.
                alloc_size = hi + 1 if lo > 0 else (hi - lo + 1)
                return [element_default for _ in range(alloc_size)]
            # Multi-dimensional: build nested lists recursively.
            # For 2D: outer list has dim[0] rows; each row is a flat list of dim[1] elements.
            # For ND: recurse by wrapping remaining dimensions.
            outer_lo, outer_hi = type_info.dimensions[0]
            outer_alloc = outer_hi + 1 if outer_lo > 0 else (outer_hi - outer_lo + 1)
            inner_dims = type_info.dimensions[1:]
            inner_type_str = (
                f"Array[{', '.join(f'{lo}..{hi}' for lo, hi in inner_dims)}] of {type_info.element_type}"
            )
            return [self.create_default(inner_type_str) for _ in range(outer_alloc)]

        return type_info.default_factory()

    def convert_literal(self, value: str, type_str: str) -> Any:
        """Convert an SCL literal value to a Python value.

        Parameters
        ----------
        value : str
            The literal value string from SCL code.
        type_str : str
            The target SCL type string.

        Returns
        -------
        Any
            The converted Python value.
        """
        value = value.strip()

        # Handle time literals (T#150ms, T#1s, etc.)
        if value.upper().startswith("T#"):
            return self._parse_time_literal(value)

        # Handle boolean literals
        if type_str == "Bool":
            return value.lower() in ("true", "1")

        # Handle numeric literals
        type_info = self.parse_type(type_str)
        if isinstance(type_info, TypeInfo):
            if type_info.python_type is int:
                # Handle hex literals
                if value.lower().startswith("16#"):
                    return int(value[3:], 16)
                # Handle binary literals
                if value.lower().startswith("2#"):
                    return int(value[2:], 2)
                return int(float(value))
            if type_info.python_type is float:
                return float(value)
            if type_info.python_type is str:
                # Strip quotes if present
                if value.startswith(("'", '"')) and value.endswith(("'", '"')):
                    return value[1:-1]
                return value
            if type_info.python_type is bool:
                return value.lower() in ("true", "1")

        return value

    def _parse_time_literal(self, value: str) -> float:
        """Parse a time literal to seconds.

        Parameters
        ----------
        value : str
            Time literal string (e.g., "T#150ms", "T#1s", "T#1h30m").

        Returns
        -------
        float
            Time value in seconds.
        """
        value = value.strip()

        # Check if it starts with T#
        if not value.upper().startswith("T#"):
            return 0.0

        time_part = value[2:]

        # Parse all time components and sum them
        # This handles both simple (T#150ms) and combined (T#1h30m) formats
        total_seconds = 0.0
        remaining = time_part

        for pattern, multiplier in TIME_COMPONENT_PATTERNS:
            match = pattern.search(remaining)
            if match:
                total_seconds += float(match.group(1)) * multiplier
                # Remove matched portion to avoid double-matching
                remaining = remaining[: match.start()] + remaining[match.end() :]

        return total_seconds

    def get_python_type_hint(self, type_str: str) -> str:
        """Get the Python type hint string for an SCL type.

        Parameters
        ----------
        type_str : str
            The SCL type string.

        Returns
        -------
        str
            Python type hint string for code generation.
        """
        type_info = self.parse_type(type_str)

        if isinstance(type_info, ArrayTypeInfo):
            # UDT / _.Type elements become _AutoStruct (or dict) at runtime and
            # their bare name is undefined in the generated module namespace, so a
            # hint like ``list[someUdt]`` would raise NameError. Emit ``list[Any]``
            # instead. ``Any`` is available because scalar UDTs already emit it.
            element_info = self.parse_type(type_info.element_type)
            if isinstance(element_info, TypeInfo) and element_info.scl_type == SCLType.UDT:
                return "list[Any]"
            if len(type_info.dimensions) == 1:
                element_hint = self.get_python_type_hint(type_info.element_type)
                return f"list[{element_hint}]"
            # Multi-dimensional: wrap inner hint with list[…]
            inner_dims = type_info.dimensions[1:]
            inner_type_str = (
                f"Array[{', '.join(f'{lo}..{hi}' for lo, hi in inner_dims)}] of {type_info.element_type}"
            )
            inner_hint = self.get_python_type_hint(inner_type_str)
            return f"list[{inner_hint}]"

        return type_info.type_hint


# Convenience instance with no UDT registry
default_type_mapper = TypeMapper()


def parse_time_literal(value: str) -> float:
    """Parse a time literal to seconds.

    Parameters
    ----------
    value : str
        Time literal string (e.g., "T#150ms").

    Returns
    -------
    float
        Time value in seconds.
    """
    return default_type_mapper._parse_time_literal(value)
