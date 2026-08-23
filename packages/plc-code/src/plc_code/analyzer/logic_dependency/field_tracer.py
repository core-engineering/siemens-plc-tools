"""Bidirectional field tracer for PLC programs.

This module traces field dependencies in both directions:
- Backward (for outputs): Find what writes to a field
- Forward (for inputs): Find what reads from a field

Every question here is answered from the block's :mod:`access_index` -- one pass
over the shared SCL and ladder ASTs -- rather than by regexes over the block's
re-spaced text, which is what this module used to do.
"""

import re
from dataclasses import dataclass, field

from plc_code.parser.models import Block

from .access_index import Access, CallContext, access_index


@dataclass
class FieldAccess:
    """Represents an access (read or write) to a global field."""

    field_path: str
    block_name: str
    line_number: int
    access_type: str  # "read" or "write"
    expression: str  # The full expression context
    dependencies: list[str] = field(default_factory=list)  # Variables referenced
    call: CallContext | None = None  # Set when the access is a call's parameter binding
    element: str = ""  # What produced it (see access_index.Access.element)

    @property
    def is_write(self) -> bool:
        """Check if this is a write access."""
        return self.access_type == "write"

    @property
    def is_read(self) -> bool:
        """Check if this is a read access."""
        return self.access_type == "read"


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
    """Find calls that pass a parent struct to a block as a parameter.

    This detects InOut struct pass-through patterns where a parent struct
    (e.g., "SafetyData".arm3.output) is passed to a function block,
    which then writes to sub-fields internally.

    Parameters
    ----------
    blocks : list[Block]
        List of blocks to search.
    parent_path : str
        The parent struct path to look for as a parameter binding.

    Returns
    -------
    list[InOutBinding]
        Every ``:=`` binding of a matching path, with the call's instance name
        and every ``:=`` parameter of that call mapped to its global path.
    """
    normalized_parent = _normalize_field_path(parent_path)
    results = []
    for block in blocks:
        for access in access_index(block).reads():
            call = access.call
            if call is None or call.direction != ":=" or not access.is_global:
                continue
            param_field = _normalize_field_path(access.path)
            if not _fields_match(param_field, normalized_parent):
                continue
            instance_name = call.instance if call.instance is not None else call.callee.strip('"')
            param_mapping = {
                name: _normalize_field_path(value)
                for name, value in call.inputs.items()
                if value.startswith('"')
            }
            results.append(
                InOutBinding(
                    caller_block=block,
                    instance_name=instance_name,
                    param_name=call.parameter,
                    parent_field=param_field,
                    param_mapping=param_mapping,
                    call_expr=call.text.rstrip(";"),
                    line_number=access.line,
                )
            )
    return results


def find_local_subfield_writer(
    block: Block,
    param_name: str,
    suffix: str,
) -> tuple[str, dict[str, str], int] | None:
    """Find a call whose ``=>`` output writes the local ``#param_name.suffix``.

    Parameters
    ----------
    block : Block
        The block to search (the callee whose InOut parameter is written).
    param_name : str
        The InOut parameter's name.
    suffix : str
        The sub-field path below it.

    Returns
    -------
    tuple[str, dict[str, str], int] | None
        ``(call_expr, {output_param: local_ref, input_param: local_ref, ...}, line)``
        for the first such call, or ``None``. The mapping holds the call's ``:=``
        inputs that are local paths (``#a.b``), by parameter name.
    """
    target_local = f"#{param_name}.{suffix}"
    for access in access_index(block).writes():
        call = access.call
        if call is None or call.direction != "=>":
            continue
        if _normalize_field_path(access.path) != target_local:
            continue
        input_deps = {
            name: value for name, value in call.inputs.items() if value.startswith("#") and "." in value
        }
        return (call.text.rstrip(";"), input_deps, access.line)
    return None


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


def _field_access(access: Access, expression: str | None = None) -> FieldAccess:
    return FieldAccess(
        field_path=access.path,
        block_name=access.block_name,
        line_number=access.line,
        access_type=access.kind,
        expression=expression if expression is not None else access.expression,
        dependencies=list(access.dependencies),
        call=access.call,
        element=access.element,
    )


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
        Every write of the field: an assignment, a call's ``=>`` output, a
        ladder coil or a Move box. ``dependencies`` holds what the write reads.
    """
    normalized_target = _normalize_field_path(field_path)
    return [
        _field_access(access)
        for block in blocks
        for access in access_index(block).writes()
        if access.is_global and _fields_match(access.path, normalized_target)
    ]


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
        Every read of the field, one per statement. ``dependencies`` holds what
        the reading statement writes.
    """
    normalized_target = _normalize_field_path(field_path)
    accesses = []
    seen: set[tuple[str, int, str]] = set()
    for block in blocks:
        for access in access_index(block).reads():
            if not access.is_global or not _fields_match(access.path, normalized_target):
                continue
            key = (block.name, access.line, access.statement)
            if key in seen:
                continue  # one entry per statement, however many times it reads the field
            seen.add(key)
            accesses.append(_field_access(access))
    return accesses


def find_all_writes_to_field_pattern(blocks: list[Block], field_pattern: str) -> dict[str, list[FieldAccess]]:
    """Find every assignment whose target matches a wildcard pattern.

    Parameters
    ----------
    blocks : list[Block]
        List of blocks to search.
    field_pattern : str
        A field pattern (e.g., "ProcessData".*.output.*).

    Returns
    -------
    dict[str, list[FieldAccess]]
        Writes grouped by the target as written.
    """
    regex_pattern = field_pattern.replace(".", r"\.").replace("*", r"[a-zA-Z0-9_\[\]#]+")
    pattern_re = re.compile(regex_pattern)
    result: dict[str, list[FieldAccess]] = {}
    for block in blocks:
        for access in access_index(block).writes():
            if access.element != "assignment" or not access.is_global:
                continue
            target = _normalize_field_path(access.path)
            if pattern_re.match(target):
                result.setdefault(target, []).append(_field_access(access))
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
