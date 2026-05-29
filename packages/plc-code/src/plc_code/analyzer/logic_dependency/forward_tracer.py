"""Enhanced forward tracer for PLC input tags.

This module traces input tags forward through the program,
following data flow through function calls until reaching
termination points (state variables or output tags).
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from plc_code.parser.models import Block

from .index_resolver import (
    TagIndexInfo,
    extract_indices_from_tag,
    normalize_and_resolve,
)
from .state_detector import is_io_tag, is_state_variable


@dataclass
class DataFlowNode:
    """A node in the data flow graph."""

    field_path: str  # Resolved field path (e.g., "ProcessData".arms[3].input.x)
    block_name: str
    line_number: int
    access_type: str  # "read", "write", "function_input", "function_output"
    expression: str
    output_fields: list[str] = field(default_factory=list)  # For function calls
    is_terminal: bool = False
    terminal_reason: str | None = None  # "state_var", "io_tag", "max_depth"
    called_block_name: str | None = None  # e.g., "MotorDrive"
    input_param_name: str | None = None  # e.g., "percAxis"
    output_param_map: dict[str, str] = field(default_factory=dict)  # output_field -> param_name


@dataclass
class DataFlowTreeNode:
    """A node in the hierarchical data flow tree.

    Represents a field in the data flow with its source block reference
    and child nodes (downstream fields it feeds into).
    """

    field_path: str
    block_name: str
    line_number: int
    node_type: str  # "io_tag", "field", "state_var", "output_tag"
    tag_name: str | None = None  # For IO tag terminal nodes
    children: list["DataFlowTreeNode"] = field(default_factory=list)


@dataclass
class ForwardTrace:
    """Complete forward trace for an input tag."""

    tag_name: str
    resolved_field: str  # Initial field with resolved indices
    nodes: list[DataFlowNode]
    blocks_involved: list[str]
    terminal_fields: list[str]
    trace_path: list[str]  # Ordered list of field paths in the trace
    dataflow_tree: DataFlowTreeNode | None = None  # Hierarchical tree


# Pattern for function call parameters: name := field , or name => field
# Note: Parser may add space between = and > (e.g., "= >")
FUNC_PARAM_PATTERN = re.compile(r'(\w+)\s*(:=|=\s*>)\s*("[^"]+[^,)]+)', re.MULTILINE)

# Pattern to extract output parameters (=> or = > means output)
# Captures parameter name and the global field path
OUTPUT_PARAM_PATTERN = re.compile(r'(\w+)\s*=\s*>\s*("[^"]+[^,)\n]+)', re.MULTILINE)


def _get_block_content(block: Block) -> str:
    """Get the full content from a block."""
    parts = []
    for network in block.networks:
        if network.content:
            parts.append(network.content)
        if network.ladder_elements:
            parts.append("\n".join(network.ladder_elements))
        for region in network.regions:
            if region.content:
                parts.append(region.content)
            for nested in region.nested_regions:
                if nested.content:
                    parts.append(nested.content)
    return "\n".join(parts)


def _normalize_field(field_path: str) -> str:
    """Normalize a field path for comparison."""
    normalized = re.sub(r"\s*\.\s*", ".", field_path)
    normalized = re.sub(r"\s*\[\s*", "[", normalized)
    normalized = re.sub(r"\s*\]\s*", "]", normalized)
    return normalized


def _get_line_number(content: str, match_start: int) -> int:
    """Get the line number for a match position."""
    return content[:match_start].count("\n") + 1


def _extract_output_fields_from_expression(expression: str, indices: TagIndexInfo) -> list[str]:
    """Extract output fields from a function call expression.

    Looks for patterns like: output => "ProcessData".field, result => "ProcessData".other
    """
    output_fields = []
    for match in OUTPUT_PARAM_PATTERN.finditer(expression):
        field_path = match.group(2).strip()  # Strip whitespace
        # Resolve indices in the output field
        resolved = normalize_and_resolve(field_path, None)
        # Apply index resolution
        for var, val in indices.get_replacements().items():
            resolved = re.sub(
                r"\[\s*#\s*" + re.escape(var) + r"\s*\]", f"[{val}]", resolved, flags=re.IGNORECASE
            )
        output_fields.append(resolved.strip())  # Ensure no trailing whitespace
    return output_fields


def _find_enclosing_call(content: str, pos: int) -> tuple[int, int] | None:
    """Find the enclosing function call parentheses around a position.

    Walks backward from pos counting parens to find the innermost
    enclosing (...). Returns (start, end) of the enclosing parentheses
    or None if pos is not inside any parentheses.

    Parameters
    ----------
    content : str
        The full block content.
    pos : int
        Position to check.

    Returns
    -------
    tuple[int, int] | None
        (start, end) of enclosing parens, or None.
    """
    p = pos - 1
    depth = 0
    while p >= 0:
        if content[p] == ")":
            depth += 1
        elif content[p] == "(":
            if depth == 0:
                # Found unmatched ( - this encloses our position
                # Now find the matching )
                end = p + 1
                count = 1
                while end < len(content) and count > 0:
                    if content[end] == "(":
                        count += 1
                    elif content[end] == ")":
                        count -= 1
                    end += 1
                return (p, end)
            else:
                depth -= 1
        p -= 1
    return None


def _extract_call_metadata(
    content: str,
    expr_start: int,
    expr_end: int,
    field_path: str,
    block: Block,
    indices: TagIndexInfo,
) -> tuple[str | None, str | None, dict[str, str]]:
    """Extract function call metadata from an expression.

    Identifies the called block name, which input parameter our field
    is assigned to, and maps output parameters to their global field paths.

    Parameters
    ----------
    content : str
        The full block content.
    expr_start : int
        Start position of the enclosing '('.
    expr_end : int
        End position (after the closing ')').
    field_path : str
        The field path being traced.
    block : Block
        The block containing the function call (for resolving instance types).
    indices : TagIndexInfo
        Index information for field matching.

    Returns
    -------
    tuple[str | None, str | None, dict[str, str]]
        (called_block_name, input_param_name, output_param_map)
    """
    # 1. Find function/instance name before '('
    p = expr_start - 1
    while p >= 0 and content[p] in " \t\n":
        p -= 1
    name_end = p + 1
    # Check for # prefix
    while p >= 0 and (content[p].isalnum() or content[p] == "_"):
        p -= 1
    if p >= 0 and content[p] == "#":
        p -= 1
    instance_name = content[p + 1 : name_end].strip().lstrip("#")

    if not instance_name:
        return None, None, {}

    # 2. Resolve instance name to block type via caller's static vars
    called_block = None
    for var in block.static_vars:
        if var.name == instance_name:
            type_name = var.data_type
            # Strip "_." prefix (TIA Portal library type convention)
            if type_name.startswith("_."):
                type_name = type_name[2:]
            called_block = type_name
            break

    # 3. Find which input param our field is assigned to
    expression = content[expr_start:expr_end]
    input_param = None
    for m in FUNC_PARAM_PATTERN.finditer(expression):
        param_name = m.group(1)
        operator = m.group(2).strip()
        param_field = m.group(3).strip()
        if ":=" in operator:  # input parameter
            if _fields_match(field_path, param_field, indices):
                input_param = param_name
                break

    # 4. Build output param map: resolved_field -> param_name
    output_map: dict[str, str] = {}
    for m in OUTPUT_PARAM_PATTERN.finditer(expression):
        param_name = m.group(1)
        output_field = m.group(2).strip()
        resolved = normalize_and_resolve(output_field, None)
        for var_name, val in indices.get_replacements().items():
            resolved = re.sub(
                r"\[\s*#\s*" + re.escape(var_name) + r"\s*\]",
                f"[{val}]",
                resolved,
                flags=re.IGNORECASE,
            )
        output_map[resolved.strip()] = param_name

    return called_block, input_param, output_map


def _find_connection_line(
    blocks: list[Block],
    block_name: str | None,
    input_var: str | None,
    output_var: str,
) -> int:
    """Find the line where input_var influences output_var inside a block.

    Searches the called block's content for a line where the output
    local variable is assigned and the input local variable is referenced
    nearby (in the same IF condition or expression).

    Note: The parser may add spaces after '#' (e.g., '# slewingLeft'),
    so we use regex patterns to match with optional whitespace.

    Parameters
    ----------
    blocks : list[Block]
        All parsed blocks.
    block_name : str
        Name of the called block to search in.
    input_var : str
        Input parameter name (without # prefix).
    output_var : str
        Output parameter name (without # prefix).

    Returns
    -------
    int
        Line number, or 0 if not found.
    """
    if block_name is None or input_var is None:
        return 0
    # Build patterns that handle parser-added spaces after #
    input_pattern = re.compile(r"#\s*" + re.escape(input_var) + r"\b")
    output_pattern = re.compile(r"#\s*" + re.escape(output_var) + r"\b")

    for block in blocks:
        if block.name != block_name:
            continue
        content = _get_block_content(block)
        lines = content.split("\n")

        if not input_pattern.search(content):
            return 0

        # First pass: find lines where output_var is assigned
        for i, line_text in enumerate(lines, 1):
            if output_pattern.search(line_text) and ":=" in line_text:
                return i

        # Second pass: find first reference to input_var
        for i, line_text in enumerate(lines, 1):
            if input_pattern.search(line_text):
                return i

    return 0


def _fields_match(target: str, candidate: str, indices: TagIndexInfo) -> bool:
    """Check if two field paths match, considering index variations."""
    # Normalize both
    target_norm = _normalize_field(target)
    candidate_norm = normalize_and_resolve(candidate, None)

    # Apply index resolution to candidate
    for var, val in indices.get_replacements().items():
        candidate_norm = re.sub(
            r"\[\s*#\s*" + re.escape(var) + r"\s*\]", f"[{val}]", candidate_norm, flags=re.IGNORECASE
        )

    # Direct match
    if target_norm == candidate_norm:
        return True

    # Match with wildcard indices
    def wildcard(s: str) -> str:
        return re.sub(r"\[[^\]]+\]", "[*]", s)

    return wildcard(target_norm) == wildcard(candidate_norm)


def find_field_usages(
    blocks: list[Block],
    field_path: str,
    indices: TagIndexInfo,
    exclude_writes: bool = True,
) -> Iterator[DataFlowNode]:
    """Find all usages of a field in the codebase.

    Parameters
    ----------
    blocks : list[Block]
        All parsed blocks.
    field_path : str
        The resolved field path to search for.
    indices : TagIndexInfo
        Index information for matching.
    exclude_writes : bool
        If True, exclude write accesses (only find reads).

    Yields
    ------
    DataFlowNode
        Nodes representing field usages.
    """
    # Pattern to find the field in content
    # We search for the base DB name and then check the full path
    field_norm = _normalize_field(field_path)

    # Extract the DB name for initial filtering
    db_match = re.match(r'"([^"]+)"', field_norm)
    if not db_match:
        return

    db_name = db_match.group(1)

    for block in blocks:
        content = _get_block_content(block)
        if db_name not in content:
            continue

        # Search for all global field references
        global_pattern = re.compile(
            r'"([^"]+)"(?:\s*\.\s*[a-zA-Z_][a-zA-Z0-9_]*|\s*\[\s*[^\]]+\s*\])+',
        )

        for match in global_pattern.finditer(content):
            candidate = match.group(0)
            if not _fields_match(field_path, candidate, indices):
                continue

            # Determine access type from context
            line_start = content.rfind("\n", 0, match.start()) + 1
            line_end = content.find("\n", match.end())
            if line_end == -1:
                line_end = len(content)
            line = content[line_start:line_end]

            # Check if it's a write (field := ...) or read
            # Find position of field in line and check what follows
            field_pos = match.start() - line_start
            before_field = line[:field_pos].strip()
            after_field = line[field_pos + len(candidate) :].strip()

            # Skip if this is a write access and we want only reads
            is_write = after_field.startswith(":=")
            is_function_output = "=>" in before_field or "= >" in before_field
            if exclude_writes and (is_write or is_function_output):
                continue

            # Determine access type
            if is_write:
                access_type = "write"
            elif ":=" in before_field:
                # Field is on RHS of assignment (being read)
                access_type = "read"
            elif is_function_output:
                # Field is target of output parameter
                access_type = "function_output"
            else:
                access_type = "read"

            # Get the full expression context (for function calls)
            # Use proper parenthesis-aware enclosure detection
            enclosing = _find_enclosing_call(content, match.start())
            called_block_name = None
            input_param_name = None
            output_param_map: dict[str, str] = {}

            if enclosing:
                expr_start, expr_end = enclosing
                expression = content[expr_start:expr_end]

                # Extract function call metadata
                called_block_name, input_param_name, output_param_map = _extract_call_metadata(
                    content,
                    expr_start,
                    expr_end,
                    field_path,
                    block,
                    indices,
                )
            else:
                # Not inside a function call - just use the line
                expression = line

            # Extract output fields from function call
            output_fields = _extract_output_fields_from_expression(expression, indices)

            line_number = _get_line_number(content, match.start())

            yield DataFlowNode(
                field_path=normalize_and_resolve(candidate, None),
                block_name=block.name,
                line_number=line_number,
                access_type=access_type,
                expression=expression.strip(),
                output_fields=output_fields,
                called_block_name=called_block_name,
                input_param_name=input_param_name,
                output_param_map=output_param_map,
            )


def trace_input_forward(
    blocks: list[Block],
    tag_name: str,
    initial_field: str,
    io_tag_names: set[str],
    tag_assignments: dict | None = None,
    max_depth: int = 10,
) -> ForwardTrace:
    """Trace an input tag forward through the program.

    Parameters
    ----------
    blocks : list[Block]
        All parsed blocks.
    tag_name : str
        The input tag name.
    initial_field : str
        The field the tag is assigned to.
    io_tag_names : set[str]
        Set of all I/O tag names (for termination detection).
    tag_assignments : dict | None
        Dictionary mapping tag names to TagAssignment objects
        (from find_all_tag_assignments).
    max_depth : int
        Maximum tracing depth.

    Returns
    -------
    ForwardTrace
        The complete forward trace.
    """
    indices = extract_indices_from_tag(tag_name)
    resolved_field = normalize_and_resolve(initial_field, tag_name)

    nodes: list[DataFlowNode] = []
    blocks_involved: set[str] = set()
    terminal_fields: list[str] = []
    trace_path: list[str] = [resolved_field]

    # Build resolved field-to-tag lookup for output tags only
    # Maps resolved_field_path -> tag_name
    resolved_field_to_tag: dict[str, str] = {}
    if tag_assignments:
        for tag, assignment in tag_assignments.items():
            # Only include output tags (DO_, SDO_)
            if not (tag.startswith("DO_") or tag.startswith("SDO_")):
                continue
            if not assignment.mapped_field or assignment.mapped_field == "(ladder network)":
                continue
            # Resolve indices in the field path using the tag name
            resolved = normalize_and_resolve(assignment.mapped_field, tag)
            resolved_field_to_tag[resolved] = tag

    def _check_output_tag_termination(field: str) -> str | None:
        """Check if field is assigned to an output tag. Returns tag name if so."""
        norm = _normalize_field(field)

        # Direct lookup
        if norm in resolved_field_to_tag:
            return resolved_field_to_tag[norm]

        return None

    # BFS through the data flow
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(resolved_field, 0)]

    while queue:
        current_field, depth = queue.pop(0)

        if current_field in visited or depth >= max_depth:
            if depth >= max_depth:
                # Mark as terminal due to max depth
                terminal_fields.append(f"{current_field} [MAX_DEPTH]")
            continue

        visited.add(current_field)

        # Check if this field is a termination point
        if is_state_variable(current_field):
            terminal_fields.append(f"{current_field} [STATE_VAR]")
            continue

        # Check if field references an I/O tag
        field_base = _normalize_field(current_field).strip('"').split(".")[0]
        if field_base in io_tag_names or is_io_tag(field_base):
            terminal_fields.append(f"{current_field} [IO_TAG]")
            continue

        # Check if this field is assigned to an output tag
        output_tag = _check_output_tag_termination(current_field)
        if output_tag:
            terminal_fields.append(f"{current_field} -> {output_tag}")
            continue

        # Find usages of this field
        usages = list(find_field_usages(blocks, current_field, indices))

        for usage in usages:
            nodes.append(usage)
            blocks_involved.add(usage.block_name)

            # Add output fields to the queue for further tracing
            for output_field in usage.output_fields:
                if output_field not in visited:
                    queue.append((output_field, depth + 1))
                    if output_field not in trace_path:
                        trace_path.append(output_field)

    trace = ForwardTrace(
        tag_name=tag_name,
        resolved_field=resolved_field,
        nodes=nodes,
        blocks_involved=sorted(blocks_involved),
        terminal_fields=terminal_fields,
        trace_path=trace_path,
    )
    return trace


def build_dataflow_tree(
    trace: ForwardTrace,
    assignment_block: str = "",
    assignment_line: int = 0,
    tag_assignments: dict | None = None,
    blocks: list[Block] | None = None,
) -> DataFlowTreeNode:
    """Build a hierarchical tree from a forward trace.

    Constructs a tree starting from the input tag, through the resolved
    field, and following output fields recursively until terminal points.

    Parameters
    ----------
    trace : ForwardTrace
        The flat forward trace to convert into a tree.
    assignment_block : str
        Block name where the tag is initially assigned.
    assignment_line : int
        Line number of the initial assignment.
    tag_assignments : dict | None
        Optional dict mapping tag names to TagAssignment objects
        for enriching terminal DO tag nodes with block info.
    blocks : list[Block] | None
        All parsed blocks, used for looking up called block content
        to find intermediate local variable connections.

    Returns
    -------
    DataFlowTreeNode
        Root node of the data flow tree.
    """

    def _wildcard(s: str) -> str:
        """Replace array indices with wildcard for matching."""
        return re.sub(r"\[[^\]]+\]", "[*]", _normalize_field(s))

    # Build index: wildcard_field -> list of DataFlowNodes that read it
    # Using wildcard keys because node field_paths may have unresolved indices
    # (e.g., [#armNumber]) while the resolved_field has concrete indices (e.g., [3])
    field_readers: dict[str, list[DataFlowNode]] = {}
    for node in trace.nodes:
        key = _wildcard(node.field_path)
        field_readers.setdefault(key, []).append(node)

    # Parse terminal_fields into structured info
    # Format: "field -> TAG_NAME" or "field [STATE_VAR]" or "field [IO_TAG]" or "field [MAX_DEPTH]"
    terminal_info: dict[str, tuple[str, str | None]] = {}
    for t in trace.terminal_fields:
        if " -> " in t:
            field_part, tag_part = t.rsplit(" -> ", 1)
            terminal_info[_wildcard(field_part.strip())] = ("output_tag", tag_part.strip())
        elif " [STATE_VAR]" in t:
            field_part = t.replace(" [STATE_VAR]", "").strip()
            terminal_info[_wildcard(field_part)] = ("state_var", None)
        elif " [IO_TAG]" in t:
            field_part = t.replace(" [IO_TAG]", "").strip()
            terminal_info[_wildcard(field_part)] = ("io_tag", None)
        elif " [MAX_DEPTH]" in t:
            field_part = t.replace(" [MAX_DEPTH]", "").strip()
            terminal_info[_wildcard(field_part)] = ("field", None)

    def _build_children(field_path: str, visited: set[str]) -> list[DataFlowTreeNode]:
        wc = _wildcard(field_path)
        if wc in visited:
            return []
        visited.add(wc)

        # Check if this field is a terminal
        if wc in terminal_info:
            return []

        readers = field_readers.get(wc, [])
        children: list[DataFlowTreeNode] = []

        for reader in readers:
            for output_field in reader.output_fields:
                # Build the intermediate local variable node if metadata available
                has_call_info = (
                    reader.called_block_name and reader.input_param_name and reader.output_param_map
                )
                output_param = (
                    reader.output_param_map.get(
                        output_field,
                        reader.output_param_map.get(_wildcard(output_field), ""),
                    )
                    if has_call_info
                    else ""
                )

                # Check if output_field is terminal
                term = terminal_info.get(_wildcard(output_field))
                if term:
                    term_type, term_tag = term
                    # For output tags, add the DO tag as a final leaf child
                    node_children: list[DataFlowTreeNode] = []
                    if term_type == "output_tag" and term_tag:
                        # Enrich with assignment info if available
                        do_block = ""
                        do_line = 0
                        if tag_assignments and term_tag in tag_assignments:
                            do_assign = tag_assignments[term_tag]
                            do_block = do_assign.block_name
                            do_line = do_assign.line_number
                        node_children.append(
                            DataFlowTreeNode(
                                field_path=term_tag,
                                block_name=do_block,
                                line_number=do_line,
                                node_type="io_tag",
                                tag_name=term_tag,
                            )
                        )

                    # Create the output field node
                    output_node = DataFlowTreeNode(
                        field_path=output_field,
                        block_name=reader.block_name,
                        line_number=reader.line_number,
                        node_type=term_type if term_type != "output_tag" else "field",
                        tag_name=term_tag,
                        children=node_children,
                    )

                    # Wrap with intermediate local node if we have call metadata
                    if has_call_info and output_param:
                        conn_line = 0
                        if blocks:
                            conn_line = _find_connection_line(
                                blocks,
                                reader.called_block_name,
                                reader.input_param_name,
                                output_param,
                            )
                        children.append(
                            DataFlowTreeNode(
                                field_path=f"#{reader.input_param_name} \u2192 #{output_param}",
                                block_name=reader.called_block_name or "",
                                line_number=conn_line,
                                node_type="local",
                                children=[output_node],
                            )
                        )
                    else:
                        children.append(output_node)
                else:
                    sub_children = _build_children(output_field, visited)

                    # Create the output field node
                    output_node = DataFlowTreeNode(
                        field_path=output_field,
                        block_name=reader.block_name,
                        line_number=reader.line_number,
                        node_type="field",
                        children=sub_children,
                    )

                    # Wrap with intermediate local node if we have call metadata
                    if has_call_info and output_param:
                        conn_line = 0
                        if blocks:
                            conn_line = _find_connection_line(
                                blocks,
                                reader.called_block_name,
                                reader.input_param_name,
                                output_param,
                            )
                        children.append(
                            DataFlowTreeNode(
                                field_path=f"#{reader.input_param_name} \u2192 #{output_param}",
                                block_name=reader.called_block_name or "",
                                line_number=conn_line,
                                node_type="local",
                                children=[output_node],
                            )
                        )
                    else:
                        children.append(output_node)

        return children

    # Build children from resolved_field
    first_children = _build_children(trace.resolved_field, set())

    # Level 1: the resolved field (with assignment block/line)
    resolved_node = DataFlowTreeNode(
        field_path=trace.resolved_field,
        block_name=assignment_block,
        line_number=assignment_line,
        node_type="field",
        children=first_children,
    )

    # Root: the DI tag itself
    root = DataFlowTreeNode(
        field_path=trace.tag_name,
        block_name="",
        line_number=0,
        node_type="io_tag",
        tag_name=trace.tag_name,
        children=[resolved_node],
    )

    return root
