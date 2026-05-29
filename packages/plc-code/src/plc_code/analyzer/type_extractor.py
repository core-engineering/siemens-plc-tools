"""Extract type dependencies from SCL User Data Types.

This module provides functionality to detect and extract type references
from parsed UDT blocks, building the foundation for type dependency graphs.
"""

import re
from dataclasses import dataclass, field

from plc_code.parser.models import Block

# Built-in types that should be excluded from dependency graphs
BUILTIN_TYPES: set[str] = {
    # Boolean
    "Bool",
    "BOOL",
    # Integer types
    "Int",
    "INT",
    "DInt",
    "DINT",
    "UInt",
    "UINT",
    "UDInt",
    "UDINT",
    "SInt",
    "SINT",
    "USInt",
    "USINT",
    "LInt",
    "LINT",
    "ULInt",
    "ULINT",
    "Byte",
    "BYTE",
    "Word",
    "WORD",
    "DWord",
    "DWORD",
    "LWord",
    "LWORD",
    # Real types
    "Real",
    "REAL",
    "LReal",
    "LREAL",
    # String types
    "String",
    "STRING",
    "WString",
    "WSTRING",
    "Char",
    "CHAR",
    "WChar",
    "WCHAR",
    # Time types
    "Time",
    "TIME",
    "LTime",
    "LTIME",
    "Date",
    "DATE",
    "TOD",
    "Time_Of_Day",
    "TIME_OF_DAY",
    "DT",
    "Date_And_Time",
    "DATE_AND_TIME",
    "DTL",
    "LDT",
    # Timer/Counter types
    "TON",
    "TON_TIME",
    "TOF",
    "TOF_TIME",
    "TP",
    "TP_TIME",
    "CTU",
    "CTD",
    "CTUD",
    "IEC_TIMER",
    "IEC_COUNTER",
    # Other
    "Void",
    "VOID",
    "Any",
    "ANY",
    "Pointer",
    "POINTER",
    "Variant",
    "VARIANT",
}


@dataclass
class TypeReference:
    """A reference from one type to another.

    Attributes
    ----------
    source_type : str
        The type that contains the reference.
    target_type : str
        The type being referenced.
    field_name : str
        Name of the field that holds the reference.
    is_array : bool
        Whether this is an array of the target type.
    """

    source_type: str
    target_type: str
    field_name: str
    is_array: bool = False


@dataclass
class TypeDependencies:
    """Dependencies extracted from a UDT.

    Attributes
    ----------
    type_name : str
        Name of the UDT.
    references : list[TypeReference]
        List of type references found in this UDT.
    """

    type_name: str
    references: list[TypeReference] = field(default_factory=list)


# Pattern to match library type references like "_.typeUnitInput"
LIBRARY_TYPE_PATTERN = re.compile(r"_\.(\w+)")

# Pattern to match Array declarations like "Array[1..9] of _.typeUnitParameter"
ARRAY_TYPE_PATTERN = re.compile(r"Array\s*\[[^\]]+\]\s*of\s+_\.(\w+)", re.IGNORECASE)


def extract_type_dependencies(block: Block) -> TypeDependencies:
    """Extract type dependencies from a UDT block.

    Parameters
    ----------
    block : Block
        A parsed TYPE block.

    Returns
    -------
    TypeDependencies
        The extracted type dependencies.
    """
    result = TypeDependencies(type_name=block.name)

    if block.block_type != "TYPE":
        return result

    if not block.user_data_type:
        return result

    # Extract dependencies from UDT fields
    for udt_field in block.user_data_type.fields:
        field_name = udt_field.name
        data_type = udt_field.data_type

        # Check for array of library types
        array_match = ARRAY_TYPE_PATTERN.search(data_type)
        if array_match:
            target_type = array_match.group(1)
            if target_type not in BUILTIN_TYPES:
                result.references.append(
                    TypeReference(
                        source_type=block.name,
                        target_type=target_type,
                        field_name=field_name,
                        is_array=True,
                    )
                )
            continue

        # Check for direct library type reference
        lib_match = LIBRARY_TYPE_PATTERN.search(data_type)
        if lib_match:
            target_type = lib_match.group(1)
            if target_type not in BUILTIN_TYPES:
                result.references.append(
                    TypeReference(
                        source_type=block.name,
                        target_type=target_type,
                        field_name=field_name,
                        is_array=False,
                    )
                )

    return result


def extract_all_type_dependencies(blocks: list[Block]) -> list[TypeDependencies]:
    """Extract type dependencies from multiple blocks.

    Parameters
    ----------
    blocks : list[Block]
        List of parsed blocks (will filter for TYPE blocks).

    Returns
    -------
    list[TypeDependencies]
        List of type dependencies for each UDT.
    """
    results = []
    for block in blocks:
        if block.block_type == "TYPE":
            deps = extract_type_dependencies(block)
            results.append(deps)
    return results
