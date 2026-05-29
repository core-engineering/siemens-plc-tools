"""Extract function block and function calls from SCL code.

This module provides functionality to detect and extract call references
from parsed SCL blocks, building the foundation for call graph analysis.
"""

import re
from dataclasses import dataclass, field

from plc_code.analyzer.models import CallReference, CallType
from plc_code.parser.models import Block, VariableDeclaration

# System functions that should be excluded from call graphs
# These are built-in TIA Portal functions, not user-defined
SYSTEM_FUNCTIONS: set[str] = {
    # LADDER elements
    "Contact",
    "Coil",
    "ACK_GL",
    "F_ACK_GL",
    "RCoil",
    "SCoil",
    "PBox",
    "NBox",
    "JumpCoil",
    "Label",
    "Move",
    "MOVE_BLK_VARIANT",
    # SCL keywords that might be falsely detected
    "IF",
    "IFNOT",
    "THEN",
    "ELSE",
    "ELSIF",
    "WHILE",
    "FOR",
    "REPEAT",
    "CASE",
    "RETURN",
    # Type conversions
    "INT_TO_REAL",
    "REAL_TO_INT",
    "INT_TO_USINT",
    "USINT_TO_INT",
    "BYTE_TO_SINT",
    "SINT_TO_BYTE",
    "INT_TO_DINT",
    "DINT_TO_INT",
    "WORD_TO_INT",
    "INT_TO_WORD",
    "DWORD_TO_REAL",
    "REAL_TO_DWORD",
    "BOOL_TO_INT",
    "INT_TO_BOOL",
    "DTL_TO_LDT",
    "LDT_TO_DTL",
    "TIME_TO_LTIME",
    "LTIME_TO_TIME",
    # Math functions
    "ABS",
    "SQRT",
    "SQR",
    "LN",
    "LOG",
    "EXP",
    "SIN",
    "COS",
    "TAN",
    "ASIN",
    "ACOS",
    "ATAN",
    "ATAN2",
    "TRUNC",
    "ROUND",
    "CEIL",
    "FLOOR",
    "MIN",
    "MAX",
    "LIMIT",
    "SEL",
    "MUX",
    # Bit operations
    "ROL",
    "ROR",
    "SHL",
    "SHR",
    "SWAP",
    # String functions
    "LEN",
    "LEFT",
    "RIGHT",
    "MID",
    "CONCAT",
    "INSERT",
    "DELETE",
    "REPLACE",
    "FIND",
    # System functions
    "RD_SYS_T",
    "WR_SYS_T",
    "LED",
    "DeviceStates",
    "GET_ERROR",
    "GetInstanceName",
    # Timer/Counter types (IEC)
    "TON",
    "TOF",
    "TP",
    "CTU",
    "CTD",
    "CTUD",
    "TON_TIME",
    "TOF_TIME",
    "TP_TIME",
    # Boolean functions
    "NOT",
    "AND",
    "OR",
    "XOR",
    # Move operations
    "MOVE",
    "MOVE_BLK",
    "UMOVE_BLK",
    "FILL_BLK",
    "UFILL_BLK",
    # Comparison (usually operators, but sometimes functions)
    "EQ",
    "NE",
    "LT",
    "LE",
    "GT",
    "GE",
}

# Pattern for instance variable calls: #varName() or #varName[index]()
# Captures the base variable name (without # prefix)
# Note: Tokenized content may have spaces after # (e.g., "# varName")
INSTANCE_CALL_PATTERN = re.compile(
    r"#\s*(\w+)\s*(?:\[[^\]]+\])?\s*\(",
    re.MULTILINE,
)

# Pattern for function calls: FunctionName() - starts with uppercase
# Must not be preceded by # (which would be instance call)
FUNCTION_CALL_PATTERN = re.compile(
    r"(?<!#)(?<!\w)([A-Z]\w*)\s*\(",
    re.MULTILINE,
)

# Pattern for quoted function calls in LADDER: "FunctionName"(...)
# Used in LADDER blocks exported from TIA Portal
QUOTED_FUNCTION_CALL_PATTERN = re.compile(
    r'"([A-Z]\w*)"\s*\(',
    re.MULTILINE,
)

# Pattern for lowercase calls in LADDER: instanceName(...) without # prefix
# These are typically instance variable calls exported from LADDER
LOWERCASE_CALL_PATTERN = re.compile(
    r"(?<!\w)([a-z]\w*)\s*\(",
    re.MULTILINE,
)


@dataclass
class InstanceTypeMap:
    """Mapping from instance variable names to their types.

    Attributes
    ----------
    instances : dict[str, str]
        Maps instance name to resolved type name.
    """

    instances: dict[str, str] = field(default_factory=dict)

    def get_type(self, instance_name: str) -> str | None:
        """Get the type for an instance variable.

        Parameters
        ----------
        instance_name : str
            The instance variable name (without #).

        Returns
        -------
        str | None
            The resolved type name, or None if not found.
        """
        return self.instances.get(instance_name)


def build_instance_type_map(block: Block) -> InstanceTypeMap:
    """Build a mapping from instance variable names to their types.

    This extracts all VAR (static) variables and maps their names to
    resolved type names (stripping the _.prefix for library types).

    Parameters
    ----------
    block : Block
        The parsed block to analyze.

    Returns
    -------
    InstanceTypeMap
        Mapping from instance names to type names.
    """
    type_map = InstanceTypeMap()

    for section in block.variable_sections:
        # Only look at VAR (static) section - instances are declared here
        if section.section_type != "VAR":
            continue

        for var in section.variables:
            resolved_type = _resolve_type_name(var.data_type)
            if resolved_type:
                type_map.instances[var.name] = resolved_type

    return type_map


def _resolve_type_name(data_type: str) -> str | None:
    """Resolve a data type to its base type name.

    Handles:
    - Library types: _.TypeName -> TypeName
    - Array types: Array[1..9] of _.TypeName -> TypeName
    - System types: TON_TIME, Bool, etc. -> None (excluded)

    Parameters
    ----------
    data_type : str
        The raw data type string.

    Returns
    -------
    str | None
        The resolved type name, or None if it's a system type.
    """
    # Check for array of library type
    array_match = re.match(r"Array\s*\[[^\]]+\]\s+of\s+_\.(\w+)", data_type, re.IGNORECASE)
    if array_match:
        return array_match.group(1)

    # Check for simple library type
    if data_type.startswith("_."):
        return data_type[2:]

    # System types and primitives - exclude from graph
    if data_type.upper() in SYSTEM_FUNCTIONS or data_type in {
        "Bool",
        "Int",
        "DInt",
        "Real",
        "LReal",
        "Word",
        "DWord",
        "Byte",
        "SInt",
        "USInt",
        "UInt",
        "UDInt",
        "String",
        "WString",
        "Time",
        "LTime",
        "Date",
        "DTL",
        "LDT",
        "TON_TIME",
        "TOF_TIME",
        "TP_TIME",
        "CTU_INT",
        "CTD_INT",
        "CTUD_INT",
    }:
        return None

    # Unknown type - could be a user function block
    return data_type


def _get_code_content(block: Block) -> list[tuple[str, int]]:
    """Extract all code content from a block with approximate line numbers.

    Parameters
    ----------
    block : Block
        The parsed block.

    Returns
    -------
    list[tuple[str, int]]
        List of (content, base_line_number) tuples.
    """
    contents: list[tuple[str, int]] = []

    for network in block.networks:
        # Get content from regions
        for region in network.regions:
            if region.content:
                # Use a base line estimate (regions don't track exact lines)
                contents.append((region.content, 0))

            # Handle nested regions
            for nested in region.nested_regions:
                if nested.content:
                    contents.append((nested.content, 0))

        # Get raw network content if present
        if network.content:
            contents.append((network.content, 0))

        # Get LADDER elements (for LAD blocks)
        if network.ladder_elements:
            # Join ladder elements as content for call extraction
            ladder_content = "\n".join(network.ladder_elements)
            contents.append((ladder_content, 0))

    return contents


def extract_calls(block: Block) -> list[CallReference]:
    """Extract all function block and function calls from a block.

    This function:
    1. Builds a map of instance variables to their types
    2. Scans all code regions for call patterns
    3. Resolves instance calls to their actual block types
    4. Filters out system function calls

    Parameters
    ----------
    block : Block
        The parsed block to analyze.

    Returns
    -------
    list[CallReference]
        List of call references found in the block.
    """
    calls: list[CallReference] = []
    seen_calls: set[tuple[str, str]] = set()  # (caller, callee) pairs

    # Build instance type map
    type_map = build_instance_type_map(block)

    # Get all code content
    code_contents = _get_code_content(block)

    for content, base_line in code_contents:
        # Find instance calls (#varName())
        for match in INSTANCE_CALL_PATTERN.finditer(content):
            instance_name = match.group(1)
            callee_type = type_map.get_type(instance_name)

            if callee_type:
                # Deduplicate calls to same target
                call_key = (block.name, callee_type)
                if call_key not in seen_calls:
                    seen_calls.add(call_key)
                    calls.append(
                        CallReference(
                            caller=block.name,
                            callee=callee_type,
                            instance_name=instance_name,
                            call_type=CallType.INSTANCE,
                            line_number=base_line + content[: match.start()].count("\n"),
                        )
                    )

        # Find direct function calls (FunctionName())
        for match in FUNCTION_CALL_PATTERN.finditer(content):
            func_name = match.group(1)

            # Skip system functions
            if func_name.upper() in SYSTEM_FUNCTIONS or func_name in SYSTEM_FUNCTIONS:
                continue

            # Check if this is actually an instance variable call (common in LADDER)
            # Instance variables called without # prefix resolve to their type
            instance_type = type_map.get_type(func_name)
            if instance_type:
                call_key = (block.name, instance_type)
                if call_key not in seen_calls:
                    seen_calls.add(call_key)
                    calls.append(
                        CallReference(
                            caller=block.name,
                            callee=instance_type,
                            instance_name=func_name,
                            call_type=CallType.INSTANCE,
                            line_number=base_line + content[: match.start()].count("\n"),
                        )
                    )
                continue

            # Deduplicate
            call_key = (block.name, func_name)
            if call_key not in seen_calls:
                seen_calls.add(call_key)
                calls.append(
                    CallReference(
                        caller=block.name,
                        callee=func_name,
                        instance_name=func_name,
                        call_type=CallType.FUNCTION,
                        line_number=base_line + content[: match.start()].count("\n"),
                    )
                )

        # Find quoted function calls in LADDER blocks ("FunctionName"())
        for match in QUOTED_FUNCTION_CALL_PATTERN.finditer(content):
            func_name = match.group(1)

            # Skip system functions
            if func_name.upper() in SYSTEM_FUNCTIONS or func_name in SYSTEM_FUNCTIONS:
                continue

            # Deduplicate
            call_key = (block.name, func_name)
            if call_key not in seen_calls:
                seen_calls.add(call_key)
                calls.append(
                    CallReference(
                        caller=block.name,
                        callee=func_name,
                        instance_name=func_name,
                        call_type=CallType.FUNCTION,
                        line_number=base_line + content[: match.start()].count("\n"),
                    )
                )

        # Find lowercase calls in LADDER blocks (instanceName())
        # These are instance variable calls without # prefix
        for match in LOWERCASE_CALL_PATTERN.finditer(content):
            var_name = match.group(1)

            # Skip common keywords and short names
            if len(var_name) < 3 or var_name in {"in", "out", "pt", "et", "input", "output"}:
                continue

            # Check if this matches an instance variable
            instance_type = type_map.get_type(var_name)
            if instance_type:
                call_key = (block.name, instance_type)
                if call_key not in seen_calls:
                    seen_calls.add(call_key)
                    calls.append(
                        CallReference(
                            caller=block.name,
                            callee=instance_type,
                            instance_name=var_name,
                            call_type=CallType.INSTANCE,
                            line_number=base_line + content[: match.start()].count("\n"),
                        )
                    )

    return calls


def extract_instance_declarations(block: Block) -> list[VariableDeclaration]:
    """Extract all instance variable declarations (FB instances) from a block.

    Parameters
    ----------
    block : Block
        The parsed block.

    Returns
    -------
    list[VariableDeclaration]
        List of instance variable declarations.
    """
    instances: list[VariableDeclaration] = []

    for section in block.variable_sections:
        if section.section_type != "VAR":
            continue

        for var in section.variables:
            resolved_type = _resolve_type_name(var.data_type)
            if resolved_type:
                instances.append(var)

    return instances
