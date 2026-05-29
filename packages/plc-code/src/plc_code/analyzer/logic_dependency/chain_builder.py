"""Dependency chain builder for I/O tag tracing.

This module builds complete dependency chains from physical I/O tags
to their termination points (state variables or other I/O tags).
"""

import re
from dataclasses import dataclass, field

from plc_code.parser.models import Block

from .field_tracer import (
    FUNC_INPUT_PARAM_PATTERN,
    FUNC_OUTPUT_PARAM_PATTERN,
    LADDER_MOVE_PATTERN,
    FieldAccess,
    InOutBinding,
    _fields_match,
    _get_block_content,
    _get_line_number,
    _normalize_field_path,
    _split_field_suffix,
    find_field_readers,
    find_field_writers,
    find_inout_struct_binding,
    find_local_subfield_writer,
)
from .index_resolver import extract_indices_from_tag, normalize_and_resolve
from .state_detector import classify_variable, get_state_variable_names
from .tag_assignment import TagAssignment, find_all_tag_assignments
from .tag_parser import IOTag, TagCollection


@dataclass
class DependencyNode:
    """A node in the dependency tree."""

    name: str
    node_type: str  # "io_tag", "state_var", "field", "local"
    block_name: str | None = None
    line_number: int | None = None
    expression: str | None = None
    children: list["DependencyNode"] = field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        """Check if this is a terminal node (no children)."""
        return len(self.children) == 0

    @property
    def is_termination_point(self) -> bool:
        """Check if this is a termination point type."""
        return self.node_type in ("io_tag", "state_var")


@dataclass
class DependencyChain:
    """Complete dependency chain for an I/O tag."""

    root_tag: IOTag
    assignment: TagAssignment | None
    dependency_tree: DependencyNode
    blocks_involved: list[str]
    terminal_nodes: list[str]
    direction: str  # "backward" (outputs) or "forward" (inputs)

    @property
    def depth(self) -> int:
        """Get the maximum depth of the dependency tree."""

        def _depth(node: DependencyNode) -> int:
            if not node.children:
                return 0
            return 1 + max(_depth(c) for c in node.children)

        return _depth(self.dependency_tree)


class ChainBuilder:
    """Builds dependency chains for I/O tags."""

    def __init__(
        self,
        blocks: list[Block],
        tags: TagCollection,
        max_depth: int = 10,
    ):
        """Initialize the chain builder.

        Parameters
        ----------
        blocks : list[Block]
            List of all program blocks.
        tags : TagCollection
            Collection of I/O tags.
        max_depth : int
            Maximum depth for dependency tracing.
        """
        self.blocks = blocks
        self.tags = tags
        self.max_depth = max_depth
        self.tag_name: str = ""  # Set per build_chain() call

        # Pre-compute useful lookups
        self.io_tag_names = tags.all_tag_names()
        self.state_var_names = get_state_variable_names(blocks)
        self.tag_assignments = find_all_tag_assignments(blocks, tags)

    def build_chain(self, tag: IOTag) -> DependencyChain:
        """Build the dependency chain for an I/O tag.

        Parameters
        ----------
        tag : IOTag
            The I/O tag to trace.

        Returns
        -------
        DependencyChain
            The complete dependency chain.
        """
        self.tag_name = tag.name
        assignment = self.tag_assignments.get(tag.name)
        direction = "backward" if tag.is_output else "forward"

        # Build the root node
        root = DependencyNode(
            name=tag.name,
            node_type="io_tag",
            block_name=assignment.block_name if assignment else None,
            line_number=assignment.line_number if assignment else None,
        )

        blocks_involved: set[str] = set()
        terminal_nodes: list[str] = []
        visited: set[str] = set()

        if assignment:
            blocks_involved.add(assignment.block_name)

            # Start tracing from the mapped field
            if assignment.mapped_field and assignment.mapped_field != "(ladder network)":
                # Normalize spaces and resolve indices (e.g., #armIndex -> 3)
                resolved_field = normalize_and_resolve(assignment.mapped_field, tag.name)
                # Update assignment so API response shows clean path
                assignment.mapped_field = resolved_field

                mapped_node = self._trace_field(
                    resolved_field,
                    direction,
                    visited,
                    blocks_involved,
                    terminal_nodes,
                    depth=0,
                )
                if mapped_node:
                    root.children.append(mapped_node)

        return DependencyChain(
            root_tag=tag,
            assignment=assignment,
            dependency_tree=root,
            blocks_involved=sorted(blocks_involved),
            terminal_nodes=terminal_nodes,
            direction=direction,
        )

    def _trace_field(
        self,
        field_path: str,
        direction: str,
        visited: set,
        blocks_involved: set,
        terminal_nodes: list,
        depth: int,
    ) -> DependencyNode | None:
        """Recursively trace a field's dependencies.

        Parameters
        ----------
        field_path : str
            The field to trace.
        direction : str
            "backward" or "forward".
        visited : set
            Set of already visited fields.
        blocks_involved : set
            Set to collect involved block names.
        terminal_nodes : list
            List to collect terminal node names.
        depth : int
            Current depth.

        Returns
        -------
        DependencyNode | None
            The dependency node, or None if already visited.
        """
        if depth >= self.max_depth or field_path in visited:
            return None

        visited.add(field_path)

        # Classify the field
        node_type = classify_variable(
            field_path,
            self.io_tag_names,
            self.state_var_names,
        )

        node = DependencyNode(
            name=field_path,
            node_type=node_type,
        )

        # Check if this is a termination point
        if node_type == "io_tag":
            terminal_nodes.append(field_path)
            return node
        if node_type == "state_var" and direction != "backward":
            terminal_nodes.append(field_path)
            return node
        # For state_var in backward direction, continue tracing to find
        # the source (e.g., Move bulk copy from another DB). If no source
        # is found, it will remain a terminal leaf with no children.

        # Find accesses based on direction
        if direction == "backward":
            # For outputs, trace what writes to this field
            accesses = find_field_writers(self.blocks, field_path)
        else:
            # For inputs, trace what reads this field
            accesses = find_field_readers(self.blocks, field_path)

        if accesses:
            # Select best access matching the tag's arm index
            access = _select_best_access(accesses, self.tag_name)
            node.block_name = access.block_name
            node.line_number = access.line_number
            node.expression = access.expression
            blocks_involved.add(access.block_name)

            # Check if this is a function call output (=> in expression)
            if direction == "backward" and _is_function_call_writer(access):
                self._trace_function_call_backward(
                    access,
                    node,
                    visited,
                    blocks_involved,
                    terminal_nodes,
                    depth,
                )
            else:
                # Standard tracing for direct assignments
                for dep in access.dependencies:
                    # Normalize field paths for clean display
                    resolved_dep = normalize_and_resolve(dep, self.tag_name) if dep.startswith('"') else dep
                    child = self._trace_dependency(
                        resolved_dep,
                        direction,
                        visited,
                        blocks_involved,
                        terminal_nodes,
                        depth + 1,
                    )
                    if child:
                        # Skip terminal local variables (e.g., #armNumber) -
                        # they are just index parameters, not data dependencies
                        if child.node_type == "local" and child.is_terminal:
                            continue
                        node.children.append(child)
        elif direction == "backward":
            # Fallback 1: try InOut struct resolution
            # When no direct writer is found, check if a parent struct is
            # passed as an InOut parameter to a function block that writes
            # to the sub-field internally.
            self._trace_inout_struct_backward(
                field_path,
                node,
                visited,
                blocks_involved,
                terminal_nodes,
                depth,
            )
            # Fallback 2: try Move bulk copy resolution
            # Check if a parent DB is copied via Move(in := sourceDB, out1 => targetDB)
            if not node.children:
                self._trace_move_bulk_copy_backward(
                    field_path,
                    node,
                    visited,
                    blocks_involved,
                    terminal_nodes,
                    depth,
                )

        return node

    def _trace_function_call_backward(
        self,
        access: FieldAccess,
        node: DependencyNode,
        visited: set,
        blocks_involved: set,
        terminal_nodes: list,
        depth: int,
    ) -> None:
        """Trace backward through a function call output.

        Extracts call metadata and inserts intermediate local variable nodes.
        """
        metadata = _extract_backward_call_metadata(
            access,
            self.blocks,
            self.tag_name,
        )
        if metadata:
            for input_field, input_param, output_param, called_block, conn_line in metadata:
                # Normalize input field path
                resolved_input = normalize_and_resolve(input_field, self.tag_name)
                intermediate = DependencyNode(
                    name=f"#{output_param} \u2190 #{input_param}",
                    node_type="local",
                    block_name=called_block,
                    line_number=conn_line,
                )
                child = self._trace_field(
                    resolved_input,
                    "backward",
                    visited,
                    blocks_involved,
                    terminal_nodes,
                    depth + 1,
                )
                if child:
                    intermediate.children.append(child)
                node.children.append(intermediate)
        else:
            # Fallback: trace dependencies without intermediate nodes
            for dep in access.dependencies:
                resolved_dep = normalize_and_resolve(dep, self.tag_name)
                child = self._trace_dependency(
                    resolved_dep,
                    "backward",
                    visited,
                    blocks_involved,
                    terminal_nodes,
                    depth + 1,
                )
                if child:
                    node.children.append(child)

    def _trace_inout_struct_backward(
        self,
        field_path: str,
        node: DependencyNode,
        visited: set,
        blocks_involved: set,
        terminal_nodes: list,
        depth: int,
    ) -> None:
        """Trace backward through InOut struct parameter binding.

        When a field like "SafetyData".arm3.output.armSelection has no
        direct writer, this checks if a parent struct ("SafetyData".arm3.output)
        is passed as an InOut parameter to a function block that writes to
        the sub-field internally.
        """
        split = _split_field_suffix(field_path)
        if split:
            parent_path, suffix = split

            # Find function calls that pass the parent path as a parameter
            bindings = find_inout_struct_binding(self.blocks, parent_path)
            if bindings:
                self._resolve_inout_subfield(
                    bindings,
                    suffix,
                    field_path,
                    node,
                    visited,
                    blocks_involved,
                    terminal_nodes,
                    depth,
                )

        # Fallback: the full field is a struct passed as InOut parameter
        # e.g., armSetpoint := "ProcessData".arms[3].setpoint in Motion.s7dcl
        # Motion controllers (UserAngular etc.) write sub-fields via InOut.
        if not node.children:
            self._trace_inout_whole_struct_backward(
                field_path,
                node,
                visited,
                blocks_involved,
                terminal_nodes,
                depth,
            )

    def _resolve_inout_subfield(
        self,
        bindings: list[InOutBinding],
        suffix: str,
        field_path: str,
        node: DependencyNode,
        visited: set,
        blocks_involved: set,
        terminal_nodes: list,
        depth: int,
    ) -> None:
        """Resolve a sub-field write through InOut struct parameter binding."""
        # Select the best binding (prefer matching arm index)
        binding = bindings[0]
        if len(bindings) > 1:
            indices = extract_indices_from_tag(self.tag_name)
            arm_idx = indices.arm_index
            if arm_idx is not None:
                arm_str = f"arm{arm_idx}"
                for candidate in bindings:
                    if arm_str in candidate.call_expr.lower():
                        binding = candidate
                        break

        # Resolve the called block type
        called_block_name = _resolve_instance_to_block(
            binding.instance_name,
            binding.caller_block,
        )
        if not called_block_name:
            called_block_name = binding.instance_name

        # Find the called block object
        called_block = None
        for b in self.blocks:
            if b.name == called_block_name:
                called_block = b
                break
        if not called_block:
            return

        # Search inside the called block for writes to #param_name.suffix
        result = find_local_subfield_writer(
            called_block,
            binding.param_name,
            suffix,
        )
        if not result:
            return

        inner_call_expr, input_deps, inner_line = result
        node.block_name = called_block_name
        node.line_number = inner_line
        node.expression = inner_call_expr
        blocks_involved.add(binding.caller_block.name)
        blocks_involved.add(called_block_name)

        # Resolve input dependencies through the InOut parameter mapping
        # input_deps maps: {input_param_name: "#inout.subfield"}
        for _input_param, local_ref in input_deps.items():
            # Resolve local ref (e.g., #status.armSelection) to global path
            # by looking up #status in the caller's parameter mapping
            global_field = _resolve_local_to_global(
                local_ref,
                binding.param_mapping,
            )
            if global_field:
                resolved_global = normalize_and_resolve(global_field, self.tag_name)
                intermediate = DependencyNode(
                    name=f"#{binding.param_name}.{suffix} \u2190 {local_ref}",
                    node_type="local",
                    block_name=called_block_name,
                    line_number=inner_line,
                )
                child = self._trace_field(
                    resolved_global,
                    "backward",
                    visited,
                    blocks_involved,
                    terminal_nodes,
                    depth + 1,
                )
                if child:
                    intermediate.children.append(child)
                node.children.append(intermediate)

    def _trace_inout_whole_struct_backward(
        self,
        field_path: str,
        node: DependencyNode,
        visited: set,
        blocks_involved: set,
        terminal_nodes: list,
        depth: int,
    ) -> None:
        """Trace backward when a whole struct is passed as InOut parameter.

        Handles cases like "ProcessData".arms[3].setpoint which is passed as InOut
        to Motion controllers (UserAngular, SafetyAngular, etc.) that write
        sub-fields internally.

        Searches for function calls where the exact field is a parameter value,
        excludes calls from blocks already in the trace to avoid cycles.
        """
        bindings = find_inout_struct_binding(self.blocks, field_path)
        if not bindings:
            return

        # Exclude bindings from blocks already in the trace to avoid cycles
        # e.g., the #axis call in MyBlock.s7dcl reads setpoint, don't re-trace it
        new_bindings = [b for b in bindings if b.caller_block.name not in blocks_involved]
        if not new_bindings:
            return

        # Select the best binding (prefer matching arm index)
        binding = new_bindings[0]
        if len(new_bindings) > 1:
            indices = extract_indices_from_tag(self.tag_name)
            arm_idx = indices.arm_index
            if arm_idx is not None:
                arm_str = str(arm_idx)
                for b in new_bindings:
                    if arm_str in b.call_expr:
                        binding = b
                        break

        node.block_name = binding.caller_block.name
        node.line_number = binding.line_number
        node.expression = binding.call_expr
        blocks_involved.add(binding.caller_block.name)

        # Extract input parameters from the call as dependencies
        # Skip the parameter that matches our field (self-reference)
        normalized_target = _normalize_field_path(field_path)
        for m in FUNC_INPUT_PARAM_PATTERN.finditer(binding.call_expr):
            input_field = m.group(2).strip()
            input_norm = _normalize_field_path(input_field)

            # Skip self-references (the setpoint param itself)
            if _fields_match(input_norm, normalized_target):
                continue

            resolved = normalize_and_resolve(input_field, self.tag_name)
            child = self._trace_field(
                resolved,
                "backward",
                visited,
                blocks_involved,
                terminal_nodes,
                depth + 1,
            )
            if child:
                # Skip terminal local variables
                if child.node_type == "local" and child.is_terminal:
                    continue
                node.children.append(child)

    def _trace_move_bulk_copy_backward(
        self,
        field_path: str,
        node: DependencyNode,
        visited: set,
        blocks_involved: set,
        terminal_nodes: list,
        depth: int,
    ) -> None:
        """Trace backward through a Move bulk struct copy.

        Handles patterns like:
            Move(in := "SafetyData", out1 => "InterfaceSafetyProcess")

        When looking for writers of "InterfaceSafetyProcess".arm3.input.percArmed,
        detects that the entire "InterfaceSafetyProcess" is written via Move from
        "SafetyData", and maps to "SafetyData".arm3.input.percArmed.
        """
        normalized = _normalize_field_path(field_path)

        for block in self.blocks:
            content = _get_block_content(block)

            for match in LADDER_MOVE_PATTERN.finditer(content):
                source = _normalize_field_path(match.group(1).strip())
                target = _normalize_field_path(match.group(2).strip())

                # Check if target is a parent prefix of our field path
                if not target.startswith('"'):
                    continue
                if not normalized.startswith(target):
                    continue
                # Ensure it's a proper prefix (followed by . or end)
                suffix = normalized[len(target) :]
                if suffix and not suffix.startswith("."):
                    continue

                # Map to source field: source + suffix
                source_field = source + suffix
                line_num = _get_line_number(content, match.start())

                node.block_name = block.name
                node.line_number = line_num
                node.expression = f"Move({source} => {target})"
                blocks_involved.add(block.name)

                # Continue tracing the source field
                child = self._trace_field(
                    source_field,
                    "backward",
                    visited,
                    blocks_involved,
                    terminal_nodes,
                    depth + 1,
                )
                if child:
                    node.children.append(child)
                return

    def _trace_dependency(
        self,
        dep: str,
        direction: str,
        visited: set,
        blocks_involved: set,
        terminal_nodes: list,
        depth: int,
    ) -> DependencyNode | None:
        """Trace a single dependency.

        Parameters
        ----------
        dep : str
            The dependency (field or variable).
        direction : str
            "backward" or "forward".
        visited : set
            Set of already visited items.
        blocks_involved : set
            Set to collect involved block names.
        terminal_nodes : list
            List to collect terminal node names.
        depth : int
            Current depth.

        Returns
        -------
        DependencyNode | None
            The dependency node, or None if should be skipped.
        """
        if depth >= self.max_depth or dep in visited:
            return None

        # Classify the dependency
        node_type = classify_variable(
            dep,
            self.io_tag_names,
            self.state_var_names,
        )

        # I/O tags are always termination points
        if node_type == "io_tag":
            visited.add(dep)
            node = DependencyNode(name=dep, node_type=node_type)
            terminal_nodes.append(dep)
            return node

        # For state_var global fields in backward direction, delegate to
        # _trace_field so Move bulk copy resolution can run
        if node_type == "state_var":
            if direction == "backward" and dep.startswith('"'):
                return self._trace_field(
                    dep,
                    direction,
                    visited,
                    blocks_involved,
                    terminal_nodes,
                    depth,
                )
            visited.add(dep)
            node = DependencyNode(name=dep, node_type=node_type)
            terminal_nodes.append(dep)
            return node

        # For global fields, delegate to _trace_field (which manages visited)
        if dep.startswith('"'):
            return self._trace_field(
                dep,
                direction,
                visited,
                blocks_involved,
                terminal_nodes,
                depth,
            )

        # For local variables, mark visited and return as leaf
        visited.add(dep)
        return DependencyNode(name=dep, node_type=node_type)


def _select_best_access(
    accesses: list[FieldAccess],
    tag_name: str,
) -> FieldAccess:
    """Select the best matching access for a tag.

    When multiple writers exist (e.g., one per arm), prefer the one
    whose expression references the same arm index as the tag.
    """
    if len(accesses) == 1:
        return accesses[0]

    # Extract arm index from tag name (e.g., ARM3 -> "3")
    indices = extract_indices_from_tag(tag_name)
    arm_idx = indices.arm_index

    if arm_idx is not None:
        arm_str = f"ARM{arm_idx}"
        for access in accesses:
            expr = access.expression or ""
            if arm_str in expr.upper():
                return access

    return accesses[0]


def _is_function_call_writer(access: FieldAccess) -> bool:
    """Check if a write access comes from a function call output parameter."""
    expr = access.expression or ""
    return "= >" in expr or "=>" in expr


def _find_connection_line(
    blocks: list[Block],
    block_name: str,
    input_var: str,
    output_var: str,
) -> int:
    """Find the line where input_var influences output_var inside a block."""
    from .forward_tracer import _get_block_content as _ft_get_content

    input_pattern = re.compile(r"#\s*" + re.escape(input_var) + r"\b")
    output_pattern = re.compile(r"#\s*" + re.escape(output_var) + r"\b")

    for block in blocks:
        if block.name != block_name:
            continue
        content = _ft_get_content(block)
        lines = content.split("\n")
        # First pass: find lines where output_var is assigned
        for i, line in enumerate(lines):
            if output_pattern.search(line) and ":=" in line:
                return i + 1
        # Second pass: find first reference to input_var
        for i, line in enumerate(lines):
            if input_pattern.search(line):
                return i + 1
    return 0


def _resolve_instance_to_block(
    instance_name: str,
    caller_block: Block | None,
) -> str | None:
    """Resolve a function instance name to its block type name.

    Looks up the instance in the caller block's static vars.
    """
    if caller_block is None:
        return None
    for var in caller_block.static_vars:
        if var.name == instance_name:
            # Type name may have _ prefix (TIA Portal convention)
            type_name = var.data_type
            if type_name:
                type_name = type_name.lstrip("_").lstrip(".")
                # Remove quotes if present
                type_name = type_name.strip('"')
            return type_name
    return None


def _extract_backward_call_metadata(
    access: FieldAccess,
    blocks: list[Block],
    tag_name: str,
) -> list[tuple[str, str, str, str, int]] | None:
    """Extract function call metadata for backward tracing.

    Returns list of (input_field, input_param, output_param, called_block, line)
    tuples, or None if extraction fails.
    """
    expression = access.expression or ""

    # Find the output parameter name that writes to our target field
    target_norm = _normalize_field_path(access.field_path)
    output_param = None
    for m in FUNC_OUTPUT_PARAM_PATTERN.finditer(expression):
        field = _normalize_field_path(m.group(2).strip())
        # Wildcard match (replace all indices with *)
        target_base = re.sub(r"\[[^\]]+\]", "[*]", target_norm)
        field_base = re.sub(r"\[[^\]]+\]", "[*]", field)
        if target_base == field_base:
            output_param = m.group(1)
            break

    if not output_param:
        return None

    # Find the caller block object to resolve instance types
    caller_block = None
    for b in blocks:
        if b.name == access.block_name:
            caller_block = b
            break

    # Find the function instance name (text before the opening '(')
    # expression starts with something like "# axis ( ..."
    instance_match = re.match(r"\s*#?\s*(\w+)\s*\(", expression)
    instance_name = instance_match.group(1) if instance_match else None

    # Resolve instance to block type
    called_block = None
    if instance_name:
        called_block = _resolve_instance_to_block(instance_name, caller_block)
    called_block = called_block or instance_name or "unknown"

    # Extract input parameters and build result tuples
    result = []
    for m in FUNC_INPUT_PARAM_PATTERN.finditer(expression):
        input_param = m.group(1)
        input_field = m.group(2).strip()

        # Find connection line inside the called block
        conn_line = _find_connection_line(
            blocks,
            called_block,
            input_param,
            output_param,
        )

        result.append(
            (
                input_field,
                input_param,
                output_param,
                called_block,
                conn_line,
            )
        )

    return result if result else None


def _resolve_local_to_global(
    local_ref: str,
    param_mapping: dict[str, str],
) -> str | None:
    """Resolve a local InOut reference to a global field path.

    For example, given local_ref="#status.armSelection" and
    param_mapping={"status": '"SafetyData".arm3.status'},
    returns '"SafetyData".arm3.status.armSelection'.

    Parameters
    ----------
    local_ref : str
        The local reference (e.g., "#status.armSelection").
    param_mapping : dict[str, str]
        Mapping from parameter names to global field paths.

    Returns
    -------
    str | None
        The resolved global field path, or None if not resolvable.
    """
    # Strip leading #
    ref = local_ref.lstrip("#")

    # Split into param_name and suffix
    parts = ref.split(".", 1)
    if len(parts) < 2:
        return None

    param_name, suffix = parts
    global_parent = param_mapping.get(param_name)
    if not global_parent:
        return None

    return f"{global_parent}.{suffix}"


def build_dependency_chain(
    tag: IOTag,
    blocks: list[Block],
    tags: TagCollection,
    max_depth: int = 10,
) -> DependencyChain:
    """Build a dependency chain for an I/O tag.

    Parameters
    ----------
    tag : IOTag
        The I/O tag to trace.
    blocks : list[Block]
        List of all program blocks.
    tags : TagCollection
        Collection of I/O tags.
    max_depth : int
        Maximum tracing depth.

    Returns
    -------
    DependencyChain
        The complete dependency chain.
    """
    builder = ChainBuilder(blocks, tags, max_depth)
    return builder.build_chain(tag)


def build_all_chains(
    blocks: list[Block],
    tags: TagCollection,
    max_depth: int = 10,
) -> dict[str, DependencyChain]:
    """Build dependency chains for all I/O tags.

    Parameters
    ----------
    blocks : list[Block]
        List of all program blocks.
    tags : TagCollection
        Collection of I/O tags.
    max_depth : int
        Maximum tracing depth.

    Returns
    -------
    dict[str, DependencyChain]
        Dictionary mapping tag names to their dependency chains.
    """
    builder = ChainBuilder(blocks, tags, max_depth)
    chains = {}

    for tag in tags.tags:
        chains[tag.name] = builder.build_chain(tag)

    return chains


def generate_chain_mermaid(chain: DependencyChain, simplified: bool = False) -> str:
    """Generate a Mermaid diagram for a dependency chain.

    Parameters
    ----------
    chain : DependencyChain
        The dependency chain.
    simplified : bool
        If True, show only termination points.

    Returns
    -------
    str
        Mermaid diagram code.
    """
    lines = ["graph TD"]
    node_id = 0
    node_ids: dict[str, str] = {}

    def _sanitize(text: str) -> str:
        """Sanitize text for Mermaid."""
        return text.replace('"', "'").replace("[", "(").replace("]", ")")

    def _get_node_id(name: str) -> str:
        nonlocal node_id
        if name not in node_ids:
            node_ids[name] = f"n{node_id}"
            node_id += 1
        return node_ids[name]

    def _get_shape(node: DependencyNode) -> tuple[str, str]:
        """Get Mermaid shape brackets for node type."""
        if node.node_type == "io_tag":
            return "[[", "]]"  # Stadium shape for I/O
        elif node.node_type == "state_var":
            return "{{", "}}"  # Hexagon for state
        elif node.node_type == "local":
            return "(", ")"  # Rounded for local
        else:
            return "[", "]"  # Rectangle for fields

    def _add_node(node: DependencyNode, parent_id: str | None = None) -> None:
        nid = _get_node_id(node.name)
        left, right = _get_shape(node)

        # Create label
        label = _sanitize(node.name)
        if node.block_name:
            label = f"{label}<br/>{node.block_name}"
            if node.line_number:
                label = f"{label}:{node.line_number}"

        lines.append(f"    {nid}{left}{label}{right}")

        # Add edge from parent
        if parent_id:
            arrow = "-->" if chain.direction == "forward" else "-->"
            lines.append(f"    {parent_id} {arrow} {nid}")

        # Add children
        for child in node.children:
            if not simplified or child.is_termination_point or child.children:
                _add_node(child, nid)

    _add_node(chain.dependency_tree)

    # Add styling
    lines.append("")
    lines.append("    %% Styling")
    lines.append("    classDef ioTag fill:#4CAF50,stroke:#2E7D32,color:white")
    lines.append("    classDef stateVar fill:#FF9800,stroke:#F57C00,color:white")
    lines.append("    classDef field fill:#2196F3,stroke:#1565C0,color:white")
    lines.append("    classDef local fill:#9E9E9E,stroke:#616161,color:white")

    # Apply styles
    for name, nid in node_ids.items():
        node_type = classify_variable(name)
        if node_type == "io_tag":
            lines.append(f"    class {nid} ioTag")
        elif node_type == "state_var":
            lines.append(f"    class {nid} stateVar")
        elif node_type == "local":
            lines.append(f"    class {nid} local")
        else:
            lines.append(f"    class {nid} field")

    return "\n".join(lines)
