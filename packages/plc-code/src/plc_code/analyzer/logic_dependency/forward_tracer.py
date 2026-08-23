"""Enhanced forward tracer for PLC input tags.

This module traces input tags forward through the program,
following data flow through function calls until reaching
termination points (state variables or output tags).
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from plc_code.parser.models import Block

from .access_index import Access, CallContext, access_index
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
def _normalize_field(field_path: str) -> str:
    """Normalize a field path for comparison."""
    normalized = re.sub(r"\s*\.\s*", ".", field_path)
    normalized = re.sub(r"\s*\[\s*", "[", normalized)
    normalized = re.sub(r"\s*\]\s*", "]", normalized)
    return normalized


def _resolve_output_field(field_path: str, indices: TagIndexInfo) -> str:
    """A call output's global path with the tag's indices substituted in."""
    resolved = normalize_and_resolve(field_path, None)
    for var, val in indices.get_replacements().items():
        resolved = re.sub(r"\[\s*#\s*" + re.escape(var) + r"\s*\]", f"[{val}]", resolved, flags=re.IGNORECASE)
    return resolved.strip()


def _output_fields(call: CallContext | None, indices: TagIndexInfo) -> list[str]:
    """The global paths a call writes through its ``=>`` outputs, indices resolved."""
    if call is None:
        return []
    return [_resolve_output_field(value, indices) for value in call.outputs.values() if value.startswith('"')]


def _call_metadata(
    access: Access,
    field_path: str,
    block: Block,
    indices: TagIndexInfo,
) -> tuple[str | None, str | None, dict[str, str]]:
    """``(called_block_name, input_param_name, output_param_map)`` for a call binding.

    The called block is the instance variable's declared type (``_.`` prefix
    stripped) when the callee is an FB instance of this block; the input
    parameter is the one whose value matches ``field_path``; the output map
    goes from each ``=>`` output's resolved global path to its parameter name.
    """
    call = access.call
    if call is None:
        return None, None, {}
    called_block = None
    if call.instance is not None:
        for var in block.static_vars:
            if var.name == call.instance:
                called_block = var.data_type[2:] if var.data_type.startswith("_.") else var.data_type
                break
    input_param = None
    for name, value in call.inputs.items():
        if value.startswith('"') and _fields_match(field_path, value, indices):
            input_param = name
            break
    output_map = {
        _resolve_output_field(value, indices): name
        for name, value in call.outputs.items()
        if value.startswith('"')
    }
    return called_block, input_param, output_map


def _find_connection_line(
    blocks: list[Block],
    block_name: str | None,
    input_var: str | None,
    output_var: str,
) -> int:
    """The line inside the called block where ``input_var`` influences ``output_var``.

    The first write of ``#output_var`` when ``#input_var`` is read anywhere in
    the block; failing that, the first read of ``#input_var``; ``0`` otherwise.
    """
    if block_name is None or input_var is None:
        return 0
    for block in blocks:
        if block.name != block_name:
            continue
        index = access_index(block)
        if not any(_local_root(a.path) == input_var for a in index.reads()):
            return 0
        for access in index.writes():
            if _local_root(access.path) == output_var:
                return access.line
        for access in index.reads():
            if _local_root(access.path) == input_var:
                return access.line
    return 0


def _local_root(path: str) -> str | None:
    if not path.startswith("#"):
        return None
    return path[1:].split(".")[0].split("[")[0]


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
    """Find all usages of a global field in the codebase.

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
        One node per statement that uses the field. ``access_type`` is ``write``
        for an assignment target, ``function_output`` for a call's ``=>`` output,
        ``read`` otherwise.
    """
    if not field_path.strip().startswith('"'):
        return
    for block in blocks:
        seen: set[tuple[int, str]] = set()
        for access in access_index(block).accesses:
            if not access.is_global or not _fields_match(field_path, access.path, indices):
                continue
            is_function_output = access.is_write and access.call is not None
            if exclude_writes and access.is_write:
                continue
            key = (access.line, access.statement)
            if key in seen:
                continue
            seen.add(key)
            if is_function_output:
                access_type = "function_output"
            elif access.is_write:
                access_type = "write"
            else:
                access_type = "read"
            called_block_name, input_param_name, output_param_map = _call_metadata(
                access, field_path, block, indices
            )
            yield DataFlowNode(
                field_path=normalize_and_resolve(access.path, None),
                block_name=block.name,
                line_number=access.line,
                access_type=access_type,
                expression=access.statement.rstrip(";"),
                output_fields=_output_fields(access.call, indices),
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
