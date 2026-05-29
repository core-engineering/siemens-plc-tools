"""Bidirectional field tracer for PLC programs.

This module traces field dependencies in both directions:
- Backward (for outputs): Find what writes to a field
- Forward (for inputs): Find what reads from a field
"""

import re
from dataclasses import dataclass, field

from plc_code.parser.models import Block


@dataclass
class FieldAccess:
    """Represents an access (read or write) to a global field."""

    field_path: str
    block_name: str
    line_number: int
    access_type: str  # "read" or "write"
    expression: str  # The full expression context
    dependencies: list[str] = field(default_factory=list)  # Variables referenced

    @property
    def is_write(self) -> bool:
        """Check if this is a write access."""
        return self.access_type == "write"

    @property
    def is_read(self) -> bool:
        """Check if this is a read access."""
        return self.access_type == "read"


# Pattern for global DB references: "DBName".field.path or "DBName".field[index].subfield
# Handles parser-added spaces: "ProcessData" . field . subfield [ # index ]
# Also handles parser-added # before some field names: . # percCollarSwitch
GLOBAL_DB_PATTERN = re.compile(
    r'"([^"]+)"(?:\s*\.\s*#?\s*[a-zA-Z_][a-zA-Z0-9_]*|\s*\[\s*[^\]]+\s*\])+',
)

# Pattern for SCL assignments
# Note: Parser adds spaces around dots and brackets, e.g., "ProcessData" . station . output . field [#index]
# The character class includes spaces/tabs but not newlines or colons, so greedy match stops at :=
ASSIGNMENT_PATTERN = re.compile(
    r'(["\w\[\]#. \t]+)\s*:=\s*([^;]+);',
    re.MULTILINE | re.DOTALL,
)

# Pattern for Ladder Contact: Contact(field)
LADDER_CONTACT_PATTERN = re.compile(
    r"Contact\(\s*([^)]+)\s*\)",
)

# Pattern for Ladder Coil: Coil(field)
LADDER_COIL_PATTERN = re.compile(
    r"Coil\(\s*([^)]+)\s*\)",
)

# Pattern for Move instruction
LADDER_MOVE_PATTERN = re.compile(
    r"Move\(\s*in\s*:=\s*([^,]+)\s*,\s*out1\s*=>\s*([^)]+)\s*\)",
)

# Pattern for function output parameter: paramName => "DB".field
# Parser adds space: paramName = > "DB" . field . subfield
# Also handles parser-added # before some field names
FUNC_OUTPUT_PARAM_PATTERN = re.compile(
    r'(\w+)\s*=\s*>\s*("[^"]+"(?:\s*\.\s*#?\s*[a-zA-Z_][a-zA-Z0-9_]*|\s*\[\s*[^\]]+\s*\])+)',
    re.MULTILINE,
)

# Pattern for function input parameter: paramName := "DB".field
# Also handles parser-added # before some field names
FUNC_INPUT_PARAM_PATTERN = re.compile(
    r'(\w+)\s*:=\s*("[^"]+"(?:\s*\.\s*#?\s*[a-zA-Z_][a-zA-Z0-9_]*|\s*\[\s*[^\]]+\s*\])+)',
    re.MULTILINE,
)

# Pattern for function output to local InOut sub-field: paramName => #inout.subfield
FUNC_OUTPUT_LOCAL_PATTERN = re.compile(
    r"(\w+)\s*=\s*>\s*#(\w+(?:\.\w+)+)",
)

# Pattern for function input from local InOut sub-field: paramName := #inout.subfield
FUNC_INPUT_LOCAL_PATTERN = re.compile(
    r"(\w+)\s*:=\s*#(\w+(?:\.\w+)+)",
)

# Pattern for function call parameter binding (any parameter with global field)
# Matches: paramName := "DB".field.path  (used for InOut struct detection)
# Also handles parser-added # before some field names
PARAM_BINDING_PATTERN = re.compile(
    r'(\w+)\s*:=\s*("[^"]+"(?:\s*\.\s*#?\s*[a-zA-Z_][a-zA-Z0-9_]*|\s*\[\s*[^\]]+\s*\])*)\s*[,)]',
    re.MULTILINE,
)


def _find_enclosing_call_expression(content: str, pos: int) -> str | None:
    """Find the full enclosing function call expression around a position.

    Walks backward from pos to find the unmatched '(', then forward
    to find the matching ')'. Returns the full call expression or None.
    """
    p = pos - 1
    depth = 0
    while p >= 0:
        if content[p] == ")":
            depth += 1
        elif content[p] == "(":
            if depth == 0:
                # Found unmatched ( - find the matching )
                end = p + 1
                count = 1
                while end < len(content) and count > 0:
                    if content[end] == "(":
                        count += 1
                    elif content[end] == ")":
                        count -= 1
                    end += 1
                # Include function name before (
                start = p
                s = p - 1
                while s >= 0 and content[s] in " \t\n":
                    s -= 1
                while s >= 0 and (content[s].isalnum() or content[s] in "_"):
                    s -= 1
                if s >= 0 and content[s] == "#":
                    s -= 1
                # Skip whitespace before function name
                while s >= 0 and content[s] in " \t\n":
                    s -= 1
                start = s + 1
                return content[start:end]
            else:
                depth -= 1
        p -= 1
    return None


def _extract_input_params_from_call(call_expr: str) -> list[str]:
    """Extract global DB field references from input parameters of a function call.

    Input parameters use := operator. Returns list of global field paths.
    """
    deps = []
    for m in FUNC_INPUT_PARAM_PATTERN.finditer(call_expr):
        field_ref = m.group(2).strip()
        if field_ref.startswith('"'):
            deps.append(field_ref)
    return deps


def _split_field_suffix(field_path: str) -> tuple[str, str] | None:
    """Split a field path into parent path and last suffix component.

    For example:
        "SafetyData".arm3.output.armSelection
        -> ("SafetyData".arm3.output, armSelection)

    Returns None if the field can't be split (e.g., only DB name with one field).
    """
    normalized = _normalize_field_path(field_path)
    # Find the last dot that's not inside quotes or brackets
    last_dot = -1
    in_quotes = False
    in_brackets = False
    for i, c in enumerate(normalized):
        if c == '"':
            in_quotes = not in_quotes
        elif c == "[":
            in_brackets = True
        elif c == "]":
            in_brackets = False
        elif c == "." and not in_quotes and not in_brackets:
            last_dot = i

    if last_dot <= 0:
        return None

    parent = normalized[:last_dot]
    suffix = normalized[last_dot + 1 :]
    if not suffix or not parent:
        return None
    return parent, suffix


@dataclass
class InOutBinding:
    """Describes an InOut parameter binding that passes a parent struct."""

    caller_block: Block
    instance_name: str
    param_name: str
    parent_field: str
    param_mapping: dict[str, str]  # param_name -> global field path
    call_expr: str
    line_number: int


def find_inout_struct_binding(
    blocks: list[Block],
    parent_path: str,
) -> list[InOutBinding]:
    """Find function calls where parent_path is passed as a parameter.

    This detects InOut struct pass-through patterns where a parent struct
    (e.g., "SafetyData".arm3.output) is passed to a function block,
    which then writes to sub-fields internally.

    Parameters
    ----------
    blocks : list[Block]
        List of all program blocks.
    parent_path : str
        The parent struct path to search for.

    Returns
    -------
    list[InOutBinding]
        List of bindings found.
    """
    normalized_parent = _normalize_field_path(parent_path)
    results = []

    for block in blocks:
        content = _get_block_content(block)

        for match in PARAM_BINDING_PATTERN.finditer(content):
            param_name = match.group(1)
            param_field = _normalize_field_path(match.group(2).strip())

            if not _fields_match(param_field, normalized_parent):
                continue

            # Found a match - get enclosing call expression
            call_expr = _find_enclosing_call_expression(content, match.start())
            if not call_expr:
                continue

            # Extract instance name (text before the opening '(')
            instance_match = re.match(r"\s*#?\s*(\w+)\s*\(", call_expr)
            if not instance_match:
                continue

            instance_name = instance_match.group(1)
            line_num = _get_line_number(content, match.start())

            # Build full parameter mapping from the call expression
            param_mapping: dict[str, str] = {}
            for pm in PARAM_BINDING_PATTERN.finditer(call_expr):
                pn = pm.group(1)
                pf = _normalize_field_path(pm.group(2).strip())
                param_mapping[pn] = pf

            results.append(
                InOutBinding(
                    caller_block=block,
                    instance_name=instance_name,
                    param_name=param_name,
                    parent_field=param_field,
                    param_mapping=param_mapping,
                    call_expr=call_expr,
                    line_number=line_num,
                )
            )

    return results


def find_local_subfield_writer(
    block: Block,
    param_name: str,
    suffix: str,
) -> tuple[str, dict[str, str], int] | None:
    """Find a write to #param_name.suffix inside a block.

    Searches for function output parameters (=>) that write to a local
    InOut sub-field. Returns the inner call expression, input dependencies
    as local refs, and the line number.

    Parameters
    ----------
    block : Block
        The block to search inside.
    param_name : str
        The InOut parameter name (e.g., "output").
    suffix : str
        The sub-field name (e.g., "armSelection").

    Returns
    -------
    tuple[str, dict[str, str], int] | None
        (inner_call_expr, {output_param: local_ref, input_param: local_ref, ...}, line_number)
        or None if not found.
    """
    content = _get_block_content(block)
    target_local = f"#{param_name}.{suffix}"

    # Search for => writes to the target local field
    for match in FUNC_OUTPUT_LOCAL_PATTERN.finditer(content):
        output_param = match.group(1)
        local_ref = match.group(2)  # e.g., "output.armSelection"

        if local_ref != f"{param_name}.{suffix}":
            continue

        # Found the write - get enclosing call expression
        call_expr = _find_enclosing_call_expression(content, match.start())
        line_num = _get_line_number(content, match.start())

        if not call_expr:
            return (f"{output_param} => {target_local}", {}, line_num)

        # Extract input dependencies from the inner call (local refs)
        input_deps: dict[str, str] = {}
        for inp_m in FUNC_INPUT_LOCAL_PATTERN.finditer(call_expr):
            inp_param = inp_m.group(1)
            inp_local = inp_m.group(2)  # e.g., "status.armSelection"
            input_deps[inp_param] = f"#{inp_local}"

        return (call_expr, input_deps, line_num)

    return None


def _get_line_number(content: str, match_start: int) -> int:
    """Get the line number for a match position."""
    return content[:match_start].count("\n") + 1


def _get_block_content(block: Block) -> str:
    """Get the full content from a block (combining networks, regions, and ladder elements)."""
    parts = []
    for network in block.networks:
        if network.content:
            parts.append(network.content)
        # Include ladder elements for LAD blocks
        if network.ladder_elements:
            parts.append("\n".join(network.ladder_elements))
        for region in network.regions:
            if region.content:
                parts.append(region.content)
            # Handle nested regions
            for nested in region.nested_regions:
                if nested.content:
                    parts.append(nested.content)
    return "\n".join(parts)


def _normalize_field_path(field_path: str) -> str:
    """Normalize a field path for comparison.

    Handles variations like:
    - "ProcessData".arms[1].output.x vs "ProcessData".arms[#ARM1].output.x
    - Removes spaces and normalizes quotes
    - Handles parser-added spaces: "ProcessData" . station . input . field
    - Handles parser-added # before field names: . # percCollarSwitch
    """
    # Remove spaces around dots and brackets
    normalized = re.sub(r"\s*\.\s*", ".", field_path)
    normalized = re.sub(r"\s*\[\s*", "[", normalized)
    normalized = re.sub(r"\s*\]\s*", "]", normalized)
    # Remove # and surrounding spaces in array indices
    normalized = re.sub(r"\[\s*#\s*", "[#", normalized)
    # Remove spurious # prefix on field names (parser artifact)
    # e.g., .#percCollarSwitch or .# percCollarSwitch -> .percCollarSwitch
    # But preserve # inside brackets (array indices like [#armNumber])
    normalized = re.sub(r"\.#\s*([a-zA-Z])", r".\1", normalized)
    return normalized


def _extract_global_fields(text: str) -> list[str]:
    """Extract all global DB field references from text."""
    fields = []
    for match in GLOBAL_DB_PATTERN.finditer(text):
        fields.append(match.group(0))
    return fields


def _extract_variable_refs(text: str) -> list[str]:
    """Extract all variable references from an expression."""
    refs = []

    # Global DB references
    refs.extend(_extract_global_fields(text))

    # I/O tag references: "TAG_NAME" where TAG_NAME starts with IO prefix
    io_tag_pattern = re.compile(r'"((?:DO|SDO|DI|SDI|AI|SAI)_[A-Z0-9_]+)"')
    for match in io_tag_pattern.finditer(text):
        refs.append(match.group(1))

    # Local variable references (#var)
    local_pattern = re.compile(r"#\s*([a-zA-Z_][a-zA-Z0-9_]*)")
    for match in local_pattern.finditer(text):
        refs.append(f"#{match.group(1)}")

    return refs


def _fields_match(target: str, pattern: str) -> bool:
    """Check if a field path matches a pattern.

    Handles array index variations (e.g., [1] vs [#ARM1]).
    """
    target_norm = _normalize_field_path(target)
    pattern_norm = _normalize_field_path(pattern)

    # Direct match
    if target_norm == pattern_norm:
        return True

    # Try matching with index normalization
    # Convert [#anything] to [\d+] for comparison
    target_base = re.sub(r"\[[^\]]+\]", "[*]", target_norm)
    pattern_base = re.sub(r"\[[^\]]+\]", "[*]", pattern_norm)

    return target_base == pattern_base


def find_field_writers(blocks: list[Block], field_path: str) -> list[FieldAccess]:
    """Find all blocks that write to a global field.

    Parameters
    ----------
    blocks : list[Block]
        List of blocks to search.
    field_path : str
        The global field path to trace (e.g., "ProcessData".arms[1].output.x).

    Returns
    -------
    list[FieldAccess]
        List of all write accesses to the field.
    """
    accesses = []
    normalized_target = _normalize_field_path(field_path)

    for block in blocks:
        content = _get_block_content(block)

        # Check SCL assignments
        for match in ASSIGNMENT_PATTERN.finditer(content):
            target = match.group(1).strip()
            expr = match.group(2).strip()

            # Check if target matches our field
            if target.startswith('"') and _fields_match(target, normalized_target):
                line_num = _get_line_number(content, match.start())
                dependencies = _extract_variable_refs(expr)

                accesses.append(
                    FieldAccess(
                        field_path=target,
                        block_name=block.name,
                        line_number=line_num,
                        access_type="write",
                        expression=expr,
                        dependencies=dependencies,
                    )
                )

        # Check Ladder Coil (writes)
        for match in LADDER_COIL_PATTERN.finditer(content):
            target = match.group(1).strip()
            if target.startswith('"') and _fields_match(target, normalized_target):
                line_num = _get_line_number(content, match.start())
                # Extract preceding Contact elements as dependencies
                # In ladder logic, Contact elements before a Coil are its conditions
                coil_deps = []
                preceding = content[: match.start()]
                for cm in LADDER_CONTACT_PATTERN.finditer(preceding):
                    contact_val = cm.group(1).strip()
                    # Only include the last set of contacts (same rung)
                    coil_deps.append(contact_val)
                # Keep only contacts from the last rung (after last Coil)
                last_coil_pos = preceding.rfind("Coil(")
                if last_coil_pos >= 0:
                    rung_text = preceding[last_coil_pos:]
                    coil_deps = []
                    for cm in LADDER_CONTACT_PATTERN.finditer(rung_text):
                        coil_deps.append(cm.group(1).strip())
                accesses.append(
                    FieldAccess(
                        field_path=target,
                        block_name=block.name,
                        line_number=line_num,
                        access_type="write",
                        expression="(ladder coil)",
                        dependencies=coil_deps,
                    )
                )

        # Check Move output
        for match in LADDER_MOVE_PATTERN.finditer(content):
            source = match.group(1).strip()
            target = match.group(2).strip()
            if target.startswith('"') and _fields_match(target, normalized_target):
                line_num = _get_line_number(content, match.start())
                dependencies = _extract_variable_refs(source)
                accesses.append(
                    FieldAccess(
                        field_path=target,
                        block_name=block.name,
                        line_number=line_num,
                        access_type="write",
                        expression=source,
                        dependencies=dependencies,
                    )
                )

        # Check function output parameters: param => field (writes to field)
        for match in FUNC_OUTPUT_PARAM_PATTERN.finditer(content):
            target = match.group(2).strip()
            if target.startswith('"') and _fields_match(target, normalized_target):
                line_num = _get_line_number(content, match.start())
                # Find enclosing function call to extract input parameters
                call_expr = _find_enclosing_call_expression(content, match.start())
                if call_expr:
                    dependencies = _extract_input_params_from_call(call_expr)
                    expression = call_expr
                else:
                    dependencies = []
                    expression = f"{match.group(1)} => {target}"

                accesses.append(
                    FieldAccess(
                        field_path=target,
                        block_name=block.name,
                        line_number=line_num,
                        access_type="write",
                        expression=expression,
                        dependencies=dependencies,
                    )
                )

    return accesses


def find_field_readers(blocks: list[Block], field_path: str) -> list[FieldAccess]:
    """Find all blocks that read from a global field.

    Parameters
    ----------
    blocks : list[Block]
        List of blocks to search.
    field_path : str
        The global field path to trace.

    Returns
    -------
    list[FieldAccess]
        List of all read accesses to the field.
    """
    accesses = []
    normalized_target = _normalize_field_path(field_path)

    for block in blocks:
        content = _get_block_content(block)

        # Check SCL assignments (field on RHS = read)
        for match in ASSIGNMENT_PATTERN.finditer(content):
            target = match.group(1).strip()
            expr = match.group(2).strip()

            # Check if our field appears in the expression
            expr_fields = _extract_global_fields(expr)
            for ef in expr_fields:
                if _fields_match(ef, normalized_target):
                    line_num = _get_line_number(content, match.start())
                    accesses.append(
                        FieldAccess(
                            field_path=ef,
                            block_name=block.name,
                            line_number=line_num,
                            access_type="read",
                            expression=f"{target} := {expr}",
                            dependencies=[target],  # What it's assigned to
                        )
                    )
                    break  # Only add once per assignment

        # Check Ladder Contact (reads)
        for match in LADDER_CONTACT_PATTERN.finditer(content):
            source = match.group(1).strip()
            if source.startswith('"') and _fields_match(source, normalized_target):
                line_num = _get_line_number(content, match.start())
                accesses.append(
                    FieldAccess(
                        field_path=source,
                        block_name=block.name,
                        line_number=line_num,
                        access_type="read",
                        expression="(ladder contact)",
                        dependencies=[],
                    )
                )

        # Check Move input
        for match in LADDER_MOVE_PATTERN.finditer(content):
            source = match.group(1).strip()
            target = match.group(2).strip()
            if source.startswith('"') and _fields_match(source, normalized_target):
                line_num = _get_line_number(content, match.start())
                accesses.append(
                    FieldAccess(
                        field_path=source,
                        block_name=block.name,
                        line_number=line_num,
                        access_type="read",
                        expression=f"Move to {target}",
                        dependencies=[target],
                    )
                )

    return accesses


def find_all_writes_to_field_pattern(blocks: list[Block], field_pattern: str) -> dict[str, list[FieldAccess]]:
    """Find all writes to fields matching a pattern.

    Parameters
    ----------
    blocks : list[Block]
        List of blocks to search.
    field_pattern : str
        A field pattern (e.g., "ProcessData".*.output.*).

    Returns
    -------
    dict[str, list[FieldAccess]]
        Dictionary mapping field paths to their write accesses.
    """
    # Convert pattern to regex
    regex_pattern = field_pattern.replace(".", r"\.")
    regex_pattern = regex_pattern.replace("*", r"[a-zA-Z0-9_\[\]]+")
    pattern_re = re.compile(regex_pattern)

    result: dict[str, list[FieldAccess]] = {}

    for block in blocks:
        content = _get_block_content(block)

        for match in ASSIGNMENT_PATTERN.finditer(content):
            target = match.group(1).strip()
            if target.startswith('"') and pattern_re.match(target):
                if target not in result:
                    result[target] = []

                expr = match.group(2).strip()
                line_num = _get_line_number(content, match.start())
                dependencies = _extract_variable_refs(expr)

                result[target].append(
                    FieldAccess(
                        field_path=target,
                        block_name=block.name,
                        line_number=line_num,
                        access_type="write",
                        expression=expr,
                        dependencies=dependencies,
                    )
                )

    return result


def trace_field_through_blocks(
    blocks: list[Block], start_field: str, direction: str = "backward", max_depth: int = 10
) -> list[tuple[str, FieldAccess]]:
    """Trace a field through blocks following assignments.

    Parameters
    ----------
    blocks : list[Block]
        List of blocks to search.
    start_field : str
        The starting field path.
    direction : str
        "backward" to trace writes (what writes to this field),
        "forward" to trace reads (where is this field used).
    max_depth : int
        Maximum depth to trace.

    Returns
    -------
    list[tuple[str, FieldAccess]]
        List of (field_path, access) pairs in trace order.
    """
    trace = []
    visited = set()
    queue = [(start_field, 0)]

    while queue:
        current_field, depth = queue.pop(0)

        if depth >= max_depth or current_field in visited:
            continue

        visited.add(current_field)

        if direction == "backward":
            accesses = find_field_writers(blocks, current_field)
        else:
            accesses = find_field_readers(blocks, current_field)

        for access in accesses:
            trace.append((current_field, access))

            # Add dependencies to queue for further tracing
            for dep in access.dependencies:
                if dep.startswith('"') and dep not in visited:
                    queue.append((dep, depth + 1))

    return trace
