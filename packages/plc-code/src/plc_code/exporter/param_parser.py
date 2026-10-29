"""TIA Portal InstanceDB XML parser for parameter extraction.

Parses Siemens TIA Portal V21 InstanceDB XML exports (e.g. ProcessParameter.xml,
SafetyParameter.xml) into flat lists of parameter entries with fully
qualified paths, data types, and values.

The XML structure uses nested Member elements with Sections/Subelements
to represent UDT hierarchies and multi-dimensional arrays. This parser
recursively traverses the structure and flattens it into individual
parameter entries.

When a Member references a UDT but has no inline value/sections (self-closing
tag), the parser can resolve the type definition from .s7dcl source files
and expand the structure using type-default values.
"""

from __future__ import annotations

import itertools
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from plc_code.layout.registry import TypeRegistry, normalize_type_name
from plc_code.parser.models import StructField

logger = logging.getLogger(__name__)

# TIA Portal XML namespace for interface definitions
NS = "http://www.siemens.com/automation/Openness/SW/Interface/v5"


# ``Array[dims] of Element``; each dim is ``lo..hi``.
_ARRAY_TYPE_RE = re.compile(r"^Array\s*\[(.*)\]\s*of\s+(.+)$", re.IGNORECASE)
_ARRAY_BOUNDS_RE = re.compile(r"^\s*(-?\d+)\s*\.\.\s*(-?\d+)\s*$")


@dataclass
class ParameterEntry:
    """A single parameter extracted from an InstanceDB XML export.

    Attributes
    ----------
    qualified_path : str
        Fully qualified path, e.g. "ProcessParameter.arms[1].motion.angular.nominalSpeeds[0]"
    datatype : str
        S7 data type (Real, Time, Bool, String, DInt, HW_IO, etc.)
    value : str
        Start value as string (e.g. "0.018", "T#5s", "TRUE", "'rcma'")
    comment : str
        Description/comment if available.
    """

    qualified_path: str
    datatype: str
    value: str
    comment: str = ""


def parse_parameter_xml(
    xml_path: Path,
    db_name: str | None = None,
    types_dir: Path | None = None,
) -> list[ParameterEntry]:
    """Parse a TIA Portal InstanceDB XML export into parameter entries.

    Parameters
    ----------
    xml_path : Path
        Path to the XML file exported from TIA Portal.
    db_name : str | None
        DB name prefix for qualified paths. If None, extracted from XML.
    types_dir : Path | None
        Directory containing .s7dcl UDT type definitions. When provided,
        self-closing UDT members (no inline values) are expanded using
        the type definitions and their default values.

    Returns
    -------
    list[ParameterEntry]
        Flat list of all leaf parameter entries with values.

    Raises
    ------
    FileNotFoundError
        If the XML file does not exist.
    ET.ParseError
        If the XML is malformed.
    ValueError
        If the XML does not contain an InstanceDB block.
    """
    xml_path = Path(xml_path)
    if not xml_path.exists():
        raise FileNotFoundError(f"XML file not found: {xml_path}")

    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Find the InstanceDB block
    instance_db = root.find("SW.Blocks.InstanceDB")
    if instance_db is None:
        raise ValueError(f"No SW.Blocks.InstanceDB found in {xml_path}")

    attr_list = instance_db.find("AttributeList")
    if attr_list is None:
        raise ValueError(f"No AttributeList found in InstanceDB in {xml_path}")

    # Extract DB name if not provided
    if db_name is None:
        name_elem = attr_list.find("Name")
        if name_elem is not None and name_elem.text:
            db_name = name_elem.text
        else:
            db_name = xml_path.stem

    # Find the Interface > Sections > Section[Name="Static"]
    interface = attr_list.find("Interface")
    if interface is None:
        raise ValueError(f"No Interface found in {xml_path}")

    sections = interface.find(f"{{{NS}}}Sections")
    if sections is None:
        raise ValueError(f"No Sections found in Interface in {xml_path}")

    static_section = None
    for section in sections.findall(f"{{{NS}}}Section"):
        if section.get("Name") == "Static":
            static_section = section
            break

    if static_section is None:
        raise ValueError(f"No Static section found in {xml_path}")

    # Build type registry if types_dir provided
    type_registry = TypeRegistry()
    if types_dir is not None:
        type_registry = build_type_registry(types_dir)

    # Parse all members recursively
    entries: list[ParameterEntry] = []
    for member in static_section.findall(f"{{{NS}}}Member"):
        _walk_member(member, db_name, [], [], entries, type_registry)

    # Sort so array-of-struct instances are grouped together.
    # The XML flattens arrays of structs field-by-field (all type[0..3], then
    # all mountingPosition[0..3], ...). We want instance-by-instance grouping
    # (all fields of [0], then all fields of [1], ...).
    entries = _sort_by_array_instance(entries)

    return entries


def _walk_member(
    member: ET.Element,
    db_name: str,
    path_parts: list[str],
    array_names: list[str],
    entries: list[ParameterEntry],
    type_registry: TypeRegistry | None = None,
) -> None:
    """Recursively walk a Member element and collect leaf parameter entries.

    Parameters
    ----------
    member : ET.Element
        The <Member> XML element to process.
    db_name : str
        DB name prefix for qualified paths.
    path_parts : list[str]
        Member names accumulated from root to current position.
    array_names : list[str]
        Names of members in path_parts that are arrays (for index insertion).
    entries : list[ParameterEntry]
        Accumulator for discovered parameter entries.
    type_registry : TypeRegistry | None
        Optional type registry for resolving self-closing UDT members.
    """
    name = member.get("Name", "")
    raw_datatype = member.get("Datatype", "")

    # Clean datatype: remove UDT quotes and extract base type for arrays
    is_array = raw_datatype.startswith("Array")
    base_type = _extract_base_type(raw_datatype)

    current_path = path_parts + [name]
    current_arrays = array_names + ([name] if is_array else [])

    # Check what children this member has
    subelements = member.findall(f"{{{NS}}}Subelement")
    # Also check without namespace (some elements don't use the namespace)
    if not subelements:
        subelements = member.findall("Subelement")

    start_value_elem = member.find(f"{{{NS}}}StartValue")
    if start_value_elem is None:
        start_value_elem = member.find("StartValue")

    sections_elem = member.find(f"{{{NS}}}Sections")
    if sections_elem is None:
        sections_elem = member.find("Sections")

    if subelements:
        # Leaf with values indexed by parent/self arrays
        for sub in subelements:
            path_str = sub.get("Path", "")
            sv = sub.find(f"{{{NS}}}StartValue")
            if sv is None:
                sv = sub.find("StartValue")
            value = sv.text if sv is not None and sv.text else ""

            indices = path_str.split(",")
            qualified = _build_qualified_path(db_name, current_path, current_arrays, indices)
            entries.append(
                ParameterEntry(
                    qualified_path=qualified,
                    datatype=base_type,
                    value=value,
                )
            )

    elif start_value_elem is not None:
        # Simple leaf value (not inside any array)
        value = start_value_elem.text if start_value_elem.text else ""
        qualified = db_name + "." + ".".join(current_path)
        entries.append(
            ParameterEntry(
                qualified_path=qualified,
                datatype=base_type,
                value=value,
            )
        )

    elif sections_elem is not None:
        # UDT container — recurse into child members
        for section in sections_elem:
            for child in section:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag == "Member":
                    _walk_member(child, db_name, current_path, current_arrays, entries, type_registry)

    elif type_registry and base_type in type_registry:
        # Self-closing UDT member with no inline values — expand from type definition
        _expand_type(db_name, current_path, current_arrays, base_type, type_registry, entries)

    # else: member with no value, no subelements, no sections — skip


def _expand_type(
    db_name: str,
    path_parts: list[str],
    array_names: list[str],
    type_name: str,
    type_registry: TypeRegistry,
    entries: list[ParameterEntry],
) -> None:
    """Expand a UDT type from the registry into leaf parameter entries.

    Every member of the type is reached: nested UDTs and inline ``Struct``
    members are recursed into, and arrays are expanded element by element
    (``gains[0]``, ``zones[1].x``, ``grid[0,1]``), as the XML export names
    them. Leaf entries carry the default value written in the type, or ``""``.

    Parameters
    ----------
    db_name : str
        DB name prefix for qualified paths.
    path_parts : list[str]
        Member names accumulated from root to current position.
    array_names : list[str]
        Names of members in path_parts that are arrays (unused here: expanded
        names already carry their indices).
    type_name : str
        UDT type name to expand.
    type_registry : TypeRegistry
        Registry of the UDTs parsed from the ``.s7dcl`` sources.
    entries : list[ParameterEntry]
        Accumulator for discovered parameter entries.
    """
    if type_name not in type_registry:
        return
    fields = type_registry.get(type_name).fields
    _expand_fields(db_name, path_parts, fields, "", type_registry, entries)


def _expand_fields(
    db_name: str,
    path_parts: list[str],
    fields: list[StructField],
    parent: str,
    type_registry: TypeRegistry,
    entries: list[ParameterEntry],
) -> None:
    """Expand the fields of ``fields`` declared directly under ``parent`` (``""`` = top level)."""
    for field in fields:
        if field.parent != parent:
            continue
        struct_path = f"{parent}.{field.name}" if parent else field.name
        _expand_member(
            db_name,
            path_parts,
            field.name,
            field.data_type,
            field.default_value or "",
            fields,
            struct_path,
            type_registry,
            entries,
        )


def _expand_member(
    db_name: str,
    path_parts: list[str],
    name: str,
    data_type: str,
    default_value: str,
    fields: list[StructField],
    struct_path: str,
    type_registry: TypeRegistry,
    entries: list[ParameterEntry],
) -> None:
    """Expand one member: inline Struct, array, UDT, or leaf entry.

    ``struct_path`` is the member's path inside its UDT; the fields of an inline
    ``Struct`` (or of an ``Array[..] of Struct``) are declared under it.
    """
    if data_type.strip().lower() == "struct":
        _expand_fields(db_name, path_parts + [name], fields, struct_path, type_registry, entries)
        return
    shape = _array_shape(data_type)
    if shape is not None:
        dimensions, element_type = shape
        for index in itertools.product(*dimensions):
            element = f"{name}[{','.join(str(i) for i in index)}]"
            _expand_member(
                db_name, path_parts, element, element_type, "", fields, struct_path, type_registry, entries
            )
        return
    if data_type in type_registry:
        _expand_type(db_name, path_parts + [name], [], data_type, type_registry, entries)
        return
    # Leaf, or an array whose bounds are not literal (kept whole rather than dropped).
    entries.append(
        ParameterEntry(
            qualified_path=db_name + "." + ".".join(path_parts + [name]),
            datatype=normalize_type_name(data_type),
            value=default_value,
        )
    )


def _array_shape(data_type: str) -> tuple[list[range], str] | None:
    """Index ranges and element type of an ``Array[lo..hi, ...] of T``; ``None`` otherwise.

    ``None`` too for bounds that are not integer literals (``Array[*]``, named
    constants), which cannot be enumerated from the source alone.
    """
    match = _ARRAY_TYPE_RE.match(data_type.strip())
    if not match:
        return None
    dimensions: list[range] = []
    for dimension in match.group(1).split(","):
        bounds = _ARRAY_BOUNDS_RE.match(dimension)
        if not bounds:
            return None
        dimensions.append(range(int(bounds.group(1)), int(bounds.group(2)) + 1))
    return dimensions, match.group(2).strip()


def build_type_registry(types_dir: Path) -> TypeRegistry:
    """Build a type registry from all .s7dcl files in a directory tree.

    Parses every ``TYPE`` block with the SCL parser. Files that do not parse
    are logged and skipped (see ``TypeRegistry.problems``).

    Parameters
    ----------
    types_dir : Path
        Root directory to scan for .s7dcl type definition files.

    Returns
    -------
    TypeRegistry
        Registry of the UDTs found (empty when ``types_dir`` is not a directory).
    """
    types_dir = Path(types_dir)
    if not types_dir.is_dir():
        return TypeRegistry()
    registry = TypeRegistry.from_directories(types_dir)
    for problem in registry.problems:
        logger.warning("type source skipped: %s", problem)
    return registry


def _sort_by_array_instance(entries: list[ParameterEntry]) -> list[ParameterEntry]:
    """Sort entries so array-of-struct instances are grouped together.

    The XML parser produces entries field-by-field across array elements:
      cpms[0].type, cpms[1].type, cpms[2].type, cpms[0].offset, cpms[1].offset, ...

    This function reorders them instance-by-instance:
      cpms[0].type, cpms[0].offset, ..., cpms[1].type, cpms[1].offset, ...

    The sort key groups entries by their "array scope" (the path up to and
    including the last array index), preserving original field order within
    each scope instance.

    Parameters
    ----------
    entries : list[ParameterEntry]
        Entries in XML parse order.

    Returns
    -------
    list[ParameterEntry]
        Entries sorted by array instance grouping.
    """
    if not entries:
        return entries

    # For each entry, compute a sort key:
    # 1. Find the last ']' in the path — everything up to and including it
    #    is the "array scope" (e.g. "ProcessParameter.arms[1].cpms[0]")
    # 2. The sort key is (scope, original_index) so entries with the same
    #    scope are grouped together in their original relative order.
    #
    # We need scopes to themselves sort by array index within parent scope.
    # Example: arms[1].cpms[0] < arms[1].cpms[1] < arms[1].cpms[2]
    # This works naturally because we extract numeric indices for comparison.

    def _sort_key(idx_entry: tuple[int, ParameterEntry]) -> tuple[list[int], int]:
        idx, entry = idx_entry
        path = entry.qualified_path
        # Extract "non-terminal" array indices — those followed by '.'
        # (i.e. struct array indices, not leaf scalar array indices).
        # This groups all fields of a struct instance together regardless
        # of whether those fields are themselves arrays.
        non_terminal: list[int] = []
        for m in re.finditer(r"\[(\d+)\]", path):
            if m.end() < len(path) and path[m.end()] == ".":
                non_terminal.append(int(m.group(1)))
        return (non_terminal, idx)

    indexed = list(enumerate(entries))
    indexed.sort(key=_sort_key)
    return [entry for _, entry in indexed]


def _build_qualified_path(
    db_name: str,
    path_parts: list[str],
    array_names: list[str],
    indices: list[str],
) -> str:
    """Build a fully qualified parameter path with array indices.

    Parameters
    ----------
    db_name : str
        DB name prefix (e.g. "ProcessParameter").
    path_parts : list[str]
        Member names from root to leaf.
    array_names : list[str]
        Which members in path_parts are arrays.
    indices : list[str]
        Array index values from the Subelement Path attribute.

    Returns
    -------
    str
        Fully qualified path like "ProcessParameter.arms[1].motion.angular.nominalSpeeds[0]"
    """
    result = db_name
    idx_iter = iter(indices)
    for part in path_parts:
        result += "." + part
        if part in array_names:
            try:
                idx = next(idx_iter)
                result += f"[{idx}]"
            except StopIteration:
                pass
    return result


def _extract_base_type(raw_datatype: str) -> str:
    """Extract the base data type from a possibly array/UDT datatype string.

    Parameters
    ----------
    raw_datatype : str
        Raw datatype from XML (e.g. 'Array[0..3] of Real', '"typeUnitGeometry"', 'Bool')

    Returns
    -------
    str
        Base type name (e.g. 'Real', 'typeUnitGeometry', 'Bool')
    """
    # Remove HTML entity quotes used for UDT names
    cleaned = raw_datatype.replace("&quot;", "").replace('"', "")

    # Extract base type from array declarations
    array_match = re.match(r"Array\[.*?\]\s+of\s+(.*)", cleaned)
    if array_match:
        return array_match.group(1).strip().replace('"', "").replace("&quot;", "")

    return cleaned


def get_arm_types(entries: list[ParameterEntry], db_name: str = "ProcessParameter") -> dict[int, str]:
    """Extract arm type values from parsed parameter entries.

    Parameters
    ----------
    entries : list[ParameterEntry]
        Parsed parameter entries.
    db_name : str
        DB name prefix to search.

    Returns
    -------
    dict[int, str]
        Mapping of arm index to type value (e.g. {1: "'rcma'", 2: "'rcma'", 5: "'none'"}).
    """
    arm_types: dict[int, str] = {}
    pattern = re.compile(rf"^{re.escape(db_name)}\.arms\[(\d+)\]\.type$")
    for entry in entries:
        m = pattern.match(entry.qualified_path)
        if m:
            arm_types[int(m.group(1))] = entry.value
    return arm_types


def get_arm_names(entries: list[ParameterEntry], db_name: str = "ProcessParameter") -> dict[int, str]:
    """Extract arm name/designation values from parsed parameter entries.

    Parameters
    ----------
    entries : list[ParameterEntry]
        Parsed parameter entries.
    db_name : str
        DB name prefix to search.

    Returns
    -------
    dict[int, str]
        Mapping of arm index to name (e.g. {1: "'021-LA001A'", 2: "'021-LA001B'"}).
    """
    arm_names: dict[int, str] = {}
    pattern = re.compile(rf"^{re.escape(db_name)}\.arms\[(\d+)\]\.name$")
    for entry in entries:
        m = pattern.match(entry.qualified_path)
        if m:
            arm_names[int(m.group(1))] = entry.value
    return arm_names


def classify_entry(entry: ParameterEntry, db_name: str) -> tuple[str, int | None]:
    """Classify a parameter entry into a section and optional arm index.

    Parameters
    ----------
    entry : ParameterEntry
        The parameter entry to classify.
    db_name : str
        The DB name prefix (e.g. "ProcessParameter").

    Returns
    -------
    tuple[str, int | None]
        (section_name, arm_index) where section_name is one of
        "arms", "remote", "drive", "controller", "modbus", "global"
        and arm_index is the arm number for arm params, None otherwise.
    """
    # Strip db_name prefix
    if entry.qualified_path.startswith(db_name + "."):
        suffix = entry.qualified_path[len(db_name) + 1 :]
    else:
        suffix = entry.qualified_path

    # Check for arms[N].* pattern
    arm_match = re.match(r"arms\[(\d+)\]\.", suffix)
    if arm_match:
        return "arms", int(arm_match.group(1))

    # Check for safety arm patterns (arm1, arm2, etc.)
    safety_arm_match = re.match(r"arm(\d+)\.", suffix)
    if safety_arm_match:
        return "safety_arms", int(safety_arm_match.group(1))

    # Check known top-level sections
    for section in ("remote", "drive", "controller", "modbus", "redundancy"):
        if suffix.startswith(section + ".") or suffix == section:
            return section, None

    return "global", None


def group_entries(
    entries: list[ParameterEntry],
    db_name: str,
) -> dict[str, list[ParameterEntry]]:
    """Group parameter entries by section.

    Parameters
    ----------
    entries : list[ParameterEntry]
        Flat list of parameter entries.
    db_name : str
        DB name prefix.

    Returns
    -------
    dict[str, list[ParameterEntry]]
        Entries grouped by section key. Unit sections use keys like "arms.1", "arms.2".
        Safety unit sections use "safety_arms.1", etc.
    """
    groups: dict[str, list[ParameterEntry]] = {}
    for entry in entries:
        section, arm_idx = classify_entry(entry, db_name)
        if arm_idx is not None:
            key = f"{section}.{arm_idx}"
        else:
            key = section
        groups.setdefault(key, []).append(entry)
    return groups
