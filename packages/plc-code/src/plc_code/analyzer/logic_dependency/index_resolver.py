"""Index resolver for PLC tag names.

This module extracts index values (like arm numbers) from tag names
and resolves variable references in field paths.
"""

import re
from dataclasses import dataclass


@dataclass
class TagIndexInfo:
    """Information about indices extracted from a tag name."""

    arm_index: int | None = None
    unit_index: int | None = None
    # Add more index types as needed

    def get_replacements(self) -> dict[str, str]:
        """Get variable replacement mappings.

        Returns
        -------
        dict[str, str]
            Mapping from variable names to their values.
        """
        replacements = {}
        if self.arm_index is not None:
            # Common variable names for arm index
            replacements["armIndex"] = str(self.arm_index)
            replacements["armNumber"] = str(self.arm_index)
            replacements["ARM_INDEX"] = str(self.arm_index)
        if self.unit_index is not None:
            replacements["unitIndex"] = str(self.unit_index)
            replacements["UNIT_INDEX"] = str(self.unit_index)
        return replacements


# Patterns to extract indices from tag names
ARM_INDEX_PATTERN = re.compile(r"ARM(\d+)", re.IGNORECASE)
UNIT_INDEX_PATTERN = re.compile(r"UNIT(\d+)", re.IGNORECASE)


def extract_indices_from_tag(tag_name: str) -> TagIndexInfo:
    """Extract index information from a tag name.

    Parameters
    ----------
    tag_name : str
        The tag name (e.g., "DI_ARM3_PERC_AXIS").

    Returns
    -------
    TagIndexInfo
        Extracted index information.
    """
    info = TagIndexInfo()

    # Extract arm index
    arm_match = ARM_INDEX_PATTERN.search(tag_name)
    if arm_match:
        info.arm_index = int(arm_match.group(1))

    # Extract unit index
    unit_match = UNIT_INDEX_PATTERN.search(tag_name)
    if unit_match:
        info.unit_index = int(unit_match.group(1))

    return info


def resolve_field_indices(field_path: str, indices: TagIndexInfo) -> str:
    """Resolve variable indices in a field path.

    Parameters
    ----------
    field_path : str
        The field path with variable indices (e.g., "ProcessData".arms[#armIndex].input.x).
    indices : TagIndexInfo
        Index information to use for resolution.

    Returns
    -------
    str
        Field path with resolved indices.
    """
    result = field_path
    replacements = indices.get_replacements()

    for var_name, value in replacements.items():
        # Match patterns like [# armIndex], [#armIndex], [ # armIndex ]
        pattern = re.compile(r"\[\s*#\s*" + re.escape(var_name) + r"\s*\]", re.IGNORECASE)
        result = pattern.sub(f"[{value}]", result)

    return result


def normalize_and_resolve(field_path: str, tag_name: str | None = None) -> str:
    """Normalize a field path and optionally resolve indices.

    Parameters
    ----------
    field_path : str
        The field path to process.
    tag_name : str | None
        Optional tag name to extract indices from.

    Returns
    -------
    str
        Normalized field path with resolved indices.
    """
    # First normalize spaces
    result = re.sub(r"\s*\.\s*", ".", field_path)
    result = re.sub(r"\s*\[\s*", "[", result)
    result = re.sub(r"\s*\]\s*", "]", result)
    # Remove spurious # prefix on field names (parser artifact)
    # e.g., .#percCollarSwitch or .# percCollarSwitch -> .percCollarSwitch
    result = re.sub(r"\.#\s*([a-zA-Z])", r".\1", result)

    # Resolve indices if tag name provided
    if tag_name:
        indices = extract_indices_from_tag(tag_name)
        result = resolve_field_indices(result, indices)

    return result


def fields_match_with_resolution(field1: str, field2: str, tag_name: str | None = None) -> bool:
    """Check if two field paths match, considering index resolution.

    Parameters
    ----------
    field1 : str
        First field path.
    field2 : str
        Second field path.
    tag_name : str | None
        Tag name to use for index resolution.

    Returns
    -------
    bool
        True if the fields match.
    """
    # Normalize both
    norm1 = normalize_and_resolve(field1, tag_name)
    norm2 = normalize_and_resolve(field2, tag_name)

    # Direct match
    if norm1 == norm2:
        return True

    # Match with wildcard indices (replace all indices with *)
    def wildcard_indices(s: str) -> str:
        return re.sub(r"\[[^\]]+\]", "[*]", s)

    return wildcard_indices(norm1) == wildcard_indices(norm2)
