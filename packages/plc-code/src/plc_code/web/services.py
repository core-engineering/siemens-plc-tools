"""Service layer for the web API.

This module wraps the analyzer functions and provides a clean interface
for the API routes. It handles parsing, analysis, and data transformation.
"""

from pathlib import Path

from plc_code.analyzer.db_audit import AuditResult, run_global_variable_audit
from plc_code.analyzer.db_crossref import DBCrossReference, build_db_crossref
from plc_code.analyzer.db_extractor import (
    BlockDBDependencies,
    extract_db_references,
)
from plc_code.analyzer.logic_dependency import (
    DependencyChain,
    # Enhanced forward tracing
    ForwardTrace,
    # Tag tracing imports
    TagCollection,
    build_all_output_trees,
    build_dataflow_tree,
    build_dependency_chain,
    extract_dependencies,
    find_all_tag_assignments,
    find_tag_directory,
    generate_block_summary_diagram,
    generate_chain_mermaid,
    generate_dependency_diagram,
    generate_simplified_diagram,
    get_dependency_summary,
    parse_tag_directory,
    trace_input_forward,
)
from plc_code.parser import parse_scl_file
from plc_code.parser.models import Block
from plc_code.project.discovery import discover_blocks

from .schemas import (
    BlockDependencies,
    BlockDetail,
    BlockListResponse,
    BlockSummary,
    DependencyNodeSchema,
    DependencySummary,
    DiagramResponse,
    NodeType,
    OutputDependency,
    SourceLocation,
    VariableInfo,
)


class AnalysisService:
    """Service for analyzing PLC blocks."""

    def __init__(self, source_path: Path | None = None):
        """Initialize the service.

        Parameters
        ----------
        source_path : Path | None
            Path to the PLC program source directory.
        """
        self.source_path = source_path
        self._block_cache: dict[str, Block] = {}
        self._block_files: dict[str, Path] = {}
        self._tags_cache: TagCollection | None = None
        self._all_blocks_cache: list[Block] | None = None
        self._crossref_cache: DBCrossReference | None = None
        self._all_deps_cache: list[BlockDBDependencies] | None = None
        self._audit_cache: AuditResult | None = None

    def set_source_path(self, path: Path) -> None:
        """Set the source path and clear caches."""
        self.source_path = path
        self._block_cache.clear()
        self._block_files.clear()
        self._tags_cache = None
        self._all_blocks_cache = None
        self._crossref_cache = None
        self._all_deps_cache = None
        self._audit_cache = None

    def _discover_blocks(self) -> None:
        """Discover all blocks in the source directory."""
        if not self.source_path or not self.source_path.exists():
            return

        self._block_files.clear()
        blocks_found = discover_blocks(self.source_path)
        for bf in blocks_found:
            # Use stem as key (filename without extension)
            name = bf.source_path.stem
            self._block_files[name] = bf.source_path

    def _get_block(self, name: str) -> Block | None:
        """Get a parsed block by name."""
        # Check cache first
        if name in self._block_cache:
            return self._block_cache[name]

        # Discover blocks if needed
        if not self._block_files:
            self._discover_blocks()

        # Find block file
        block_path = self._block_files.get(name)
        if not block_path:
            # Try case-insensitive search
            for key, path in self._block_files.items():
                if key.lower() == name.lower():
                    block_path = path
                    break

        if not block_path or not block_path.exists():
            return None

        # Parse and cache
        try:
            block = parse_scl_file(block_path)
            self._block_cache[name] = block
            return block
        except Exception:
            return None

    def list_blocks(self) -> BlockListResponse:
        """List all blocks in the source directory."""
        if not self._block_files:
            self._discover_blocks()

        blocks: list[BlockSummary] = []

        for name, path in sorted(self._block_files.items()):
            # Try to get block for more details
            block = self._get_block(name)

            if block:
                # Extract category from path
                parts = path.parts
                category = ""
                subcategory = ""
                for i, part in enumerate(parts):
                    if "Process" in part or "Program blocks" in part:
                        if i + 1 < len(parts):
                            category = parts[i + 1]
                        if i + 2 < len(parts):
                            subcategory = parts[i + 2]
                        break

                summary = BlockSummary(
                    name=block.name,
                    block_type=block.block_type,
                    source_file=str(path),
                    category=category,
                    subcategory=subcategory,
                    input_count=len(block.inputs),
                    output_count=len(block.outputs),
                    outputs=[v.name for v in block.outputs],
                )
            else:
                summary = BlockSummary(
                    name=name,
                    block_type="UNKNOWN",
                    source_file=str(path),
                )

            blocks.append(summary)

        return BlockListResponse(blocks=blocks, total=len(blocks))

    def get_block_detail(self, name: str) -> BlockDetail | None:
        """Get detailed information about a block."""
        block = self._get_block(name)
        if not block:
            return None

        return BlockDetail(
            name=block.name,
            block_type=block.block_type,
            source_file=block.source_file,
            inputs=[
                VariableInfo(name=v.name, data_type=v.data_type, default_value=v.default_value)
                for v in block.inputs
            ],
            outputs=[
                VariableInfo(name=v.name, data_type=v.data_type, default_value=v.default_value)
                for v in block.outputs
            ],
            in_outs=[
                VariableInfo(name=v.name, data_type=v.data_type, default_value=v.default_value)
                for v in block.in_outs
            ],
            static_vars=[
                VariableInfo(name=v.name, data_type=v.data_type, default_value=v.default_value)
                for v in block.static_vars
            ],
            temp_vars=[
                VariableInfo(name=v.name, data_type=v.data_type, default_value=v.default_value)
                for v in block.temp_vars
            ],
            constants=[
                VariableInfo(name=v.name, data_type=v.data_type, default_value=v.default_value)
                for v in block.constants
            ],
        )

    def get_dependencies(self, name: str) -> BlockDependencies | None:
        """Get all dependencies for a block."""
        block = self._get_block(name)
        if not block:
            return None

        # Extract and build dependency trees
        deps = extract_dependencies(block)
        trees = build_all_output_trees(deps)

        outputs: dict[str, OutputDependency] = {}

        for output_name, tree in trees.items():
            summary = get_dependency_summary(tree)

            # Convert to schema types
            input_nodes = [
                DependencyNodeSchema(
                    name=node.name,
                    node_type=NodeType(node.node_type.value),
                    data_type=node.data_type,
                    source_location=(
                        SourceLocation(
                            file_path=node.source_location.file_path,
                            line_number=node.source_location.line_number,
                            region_name=node.source_location.region_name,
                        )
                        if node.source_location
                        else None
                    ),
                )
                for node in tree.all_inputs
            ]

            outputs[output_name] = OutputDependency(
                name=output_name,
                data_type=tree.output.data_type,
                source_location=(
                    SourceLocation(
                        file_path=tree.output.source_location.file_path,
                        line_number=tree.output.source_location.line_number,
                        region_name=tree.output.source_location.region_name,
                    )
                    if tree.output.source_location
                    else None
                ),
                summary=DependencySummary(
                    inputs=summary["inputs"],
                    states=summary["states"],
                    constants=summary["constants"],
                    global_dbs=summary["global_dbs"],
                    intermediate_vars=summary["intermediate"],
                ),
                input_nodes=input_nodes,
            )

        return BlockDependencies(
            block_name=block.name,
            source_file=block.source_file,
            outputs=outputs,
            parse_errors=list(deps.parse_errors),
        )

    def get_output_dependency(self, block_name: str, output_name: str) -> OutputDependency | None:
        """Get dependency information for a specific output."""
        deps = self.get_dependencies(block_name)
        if not deps:
            return None

        return deps.outputs.get(output_name)

    def get_diagram(
        self,
        block_name: str,
        output_name: str | None = None,
        simplified: bool = False,
    ) -> DiagramResponse | None:
        """Generate Mermaid diagram for a block or output."""
        block = self._get_block(block_name)
        if not block:
            return None

        # Extract and build dependency trees
        deps = extract_dependencies(block)
        trees = build_all_output_trees(deps)

        if not trees:
            return None

        if output_name:
            # Generate diagram for specific output
            tree = trees.get(output_name)
            if not tree:
                return None

            if simplified:
                mermaid = generate_simplified_diagram(tree)
            else:
                mermaid = generate_dependency_diagram(tree)

            return DiagramResponse(
                mermaid=mermaid,
                block_name=block_name,
                output_name=output_name,
                simplified=simplified,
            )
        else:
            # Generate summary diagram for all outputs
            if simplified:
                mermaid = generate_block_summary_diagram(block_name, trees)
            else:
                # Generate individual diagrams combined
                diagrams = []
                for out_name, tree in sorted(trees.items()):
                    diagram = generate_dependency_diagram(tree)
                    diagrams.append(f"subgraph {out_name}\n{diagram}\nend")
                mermaid = "\n\n".join(diagrams)

            return DiagramResponse(
                mermaid=mermaid,
                block_name=block_name,
                output_name=None,
                simplified=simplified,
            )

    def get_block_source(self, name: str) -> str | None:
        """Get the raw source code of a block from the .s7dcl file.

        Reads the original file to preserve formatting.

        Parameters
        ----------
        name : str
            Block name.

        Returns
        -------
        str | None
            Source code as a string, or None if not found.
        """
        file_path = self._find_block_file(name)
        if not file_path or not file_path.exists():
            return None

        try:
            return file_path.read_text(encoding="utf-8-sig")
        except Exception:
            return None

    def _find_block_file(self, name: str) -> Path | None:
        """Find the source file path for a block by name."""
        if not self._block_files:
            self._discover_blocks()

        path = self._block_files.get(name)
        if path:
            return path

        # Case-insensitive fallback
        for key, p in self._block_files.items():
            if key.lower() == name.lower():
                return p

        return None

    # ============== Tag Analysis Methods ==============

    def _get_all_blocks(self) -> list[Block]:
        """Get all parsed blocks."""
        if self._all_blocks_cache is not None:
            return self._all_blocks_cache

        if not self._block_files:
            self._discover_blocks()

        blocks = []
        for name in self._block_files:
            block = self._get_block(name)
            if block:
                blocks.append(block)

        self._all_blocks_cache = blocks
        return blocks

    def get_tags(self) -> TagCollection | None:
        """Get all I/O tags from the PLC program.

        Returns
        -------
        TagCollection | None
            Collection of I/O tags, or None if not found.
        """
        if self._tags_cache is not None:
            return self._tags_cache

        if not self.source_path:
            return None

        # Find tag directory
        tag_dir = find_tag_directory(self.source_path)
        if not tag_dir:
            return None

        # Parse tags
        self._tags_cache = parse_tag_directory(tag_dir)
        return self._tags_cache

    def trace_tag(self, tag_name: str) -> DependencyChain | ForwardTrace | None:
        """Build dependency chain for an I/O tag.

        For output tags (DO_, SDO_): traces backward to find what writes to the field.
        For input tags (DI_, SDI_, AI_, SAI_): traces forward to find where the field is used.

        Parameters
        ----------
        tag_name : str
            Name of the tag to trace.

        Returns
        -------
        DependencyChain | ForwardTrace | None
            The dependency chain or forward trace, or None if tag not found.
        """
        tags = self.get_tags()
        if tags is None:
            return None

        tag = tags.get(tag_name)
        if tag is None:
            return None

        blocks = self._get_all_blocks()

        # Use enhanced forward tracing for input tags
        if tag.is_input:
            # Get tag assignments for termination detection
            tag_assignments = find_all_tag_assignments(blocks, tags)

            # Find the initial field assignment
            assignment = tag_assignments.get(tag_name)
            if assignment and assignment.mapped_field:
                trace = trace_input_forward(
                    blocks=blocks,
                    tag_name=tag_name,
                    initial_field=assignment.mapped_field,
                    io_tag_names=tags.all_tag_names(),
                    tag_assignments=tag_assignments,
                    max_depth=15,
                )
                # Build the hierarchical tree
                trace.dataflow_tree = build_dataflow_tree(
                    trace,
                    assignment_block=assignment.block_name,
                    assignment_line=assignment.line_number,
                    tag_assignments=tag_assignments,
                    blocks=blocks,
                )
                return trace

        # Use existing backward tracing for output tags
        return build_dependency_chain(tag, blocks, tags)

    def get_tag_diagram(self, tag_name: str, simplified: bool = False) -> str | None:
        """Generate Mermaid diagram for a tag's dependencies.

        Parameters
        ----------
        tag_name : str
            Name of the tag.
        simplified : bool
            If True, show only termination points.

        Returns
        -------
        str | None
            Mermaid diagram code, or None if tag not found.
        """
        chain = self.trace_tag(tag_name)
        if chain is None or isinstance(chain, ForwardTrace):
            return None

        return generate_chain_mermaid(chain, simplified)

    # ============== Cross-Reference Methods ==============

    def _get_all_deps(self) -> list[BlockDBDependencies]:
        """Get all block DB dependencies (cached)."""
        if self._all_deps_cache is not None:
            return self._all_deps_cache

        blocks = self._get_all_blocks()
        self._all_deps_cache = [extract_db_references(b) for b in blocks]
        return self._all_deps_cache

    def _get_instance_db_names(self) -> set[str]:
        """Get names of instance DBs (DATA_BLOCKs that instantiate an FB).

        Instance DBs (e.g. ``ModuleInstance : Module``) are not global data
        blocks and should be excluded from the cross-reference explorer.
        """
        fb_names = {b.name for b in self._get_all_blocks() if b.block_type == "FUNCTION_BLOCK"}
        instance_dbs: set[str] = set()
        for block in self._get_all_blocks():
            if block.block_type != "DATA_BLOCK":
                continue
            bt = block.base_type
            if not bt:
                continue
            # Instance DB if base_type is a known FB or a system FB type
            if bt in fb_names or not bt.startswith("type"):
                instance_dbs.add(block.name)
        return instance_dbs

    @staticmethod
    def _propagate_struct_refs(crossref: DBCrossReference) -> None:
        """Propagate struct-level readers/writers to child variables.

        When a whole struct is accessed (e.g. ``"ModuleData".userInput := ...``),
        the access applies to every field inside that struct.  This method
        finds such parent entries, copies their readers/writers to every
        matching child variable, then removes the parent entry so only
        leaf-level variables remain in the cross-reference.
        """
        all_refs = sorted(crossref.variables.keys())

        # Find struct-level vars: those that are a prefix of other vars
        parents_to_remove: list[str] = []
        for ref in all_refs:
            prefix = ref + "."
            children = [r for r in all_refs if r.startswith(prefix)]
            if not children:
                continue
            parent = crossref.variables[ref]
            parents_to_remove.append(ref)

            # Propagate readers and writers to each child
            for child_ref in children:
                child = crossref.variables[child_ref]
                for pr in parent.readers:
                    if not any(r.block_name == pr.block_name for r in child.readers):
                        child.readers.append(pr)
                for pw in parent.writers:
                    if not any(w.block_name == pw.block_name for w in child.writers):
                        child.writers.append(pw)

        # Remove parent entries
        for ref in parents_to_remove:
            parent = crossref.variables.pop(ref)
            db_vars = crossref.by_db.get(parent.db_name, [])
            try:
                db_vars.remove(parent)
            except ValueError:
                pass

    def get_crossref(self) -> DBCrossReference:
        """Get the global cross-reference (cached).

        Instance DBs are excluded — only true global data blocks appear.
        Struct-level accesses are propagated down to child variables.
        """
        if self._crossref_cache is not None:
            return self._crossref_cache

        all_deps = self._get_all_deps()
        crossref = build_db_crossref(all_deps, doc_paths={})

        # Remove instance DBs from the crossref
        instance_dbs = self._get_instance_db_names()
        for db_name in instance_dbs:
            if db_name in crossref.by_db:
                for var in crossref.by_db.pop(db_name):
                    crossref.variables.pop(var.full_reference, None)

        # Propagate struct-level accesses to children and remove parents
        self._propagate_struct_refs(crossref)

        self._crossref_cache = crossref
        return self._crossref_cache

    def get_audit(self) -> AuditResult:
        """Get audit results (cached)."""
        if self._audit_cache is not None:
            return self._audit_cache

        crossref = self.get_crossref()
        all_deps = self._get_all_deps()
        self._audit_cache = run_global_variable_audit(crossref, all_deps)
        return self._audit_cache

    def get_violations_for_variable(self, full_reference: str) -> list:
        """Get audit violations for a specific variable."""
        audit = self.get_audit()
        return [v for v in audit.violations if v.full_reference == full_reference]

    def get_block_db_deps(self, block_name: str) -> BlockDBDependencies | None:
        """Get DB dependencies for a specific block."""
        all_deps = self._get_all_deps()
        for deps in all_deps:
            if deps.block_name.lower() == block_name.lower():
                return deps
        return None

    def find_all_reference_lines(
        self,
        block_name: str,
        db_name: str,
        field_path: str,
    ) -> list[tuple[int, str]]:
        """Find all occurrences of a DB reference in the raw source file.

        For each occurrence, resolves the array index to a concrete value
        when possible (backward scan for assignments, constant lookup).

        Parameters
        ----------
        block_name : str
            Block to search in.
        db_name : str
            Data block name (e.g., "ModuleData").
        field_path : str
            Normalized field path (may contain [*] wildcards).

        Returns
        -------
        list[tuple[int, str]]
            List of (line_number, resolved_index) tuples.
            resolved_index is e.g. "1", "2", or "#armNumber" if unresolvable.
            For variables without array access, resolved_index is "".
        """
        source = self.get_block_source(block_name)
        if not source:
            return []

        lines = source.splitlines()
        # Extract the leaf field name for matching
        parts = field_path.replace("[*]", "[").split(".")
        leaf = parts[-1] if parts else field_path

        # Check if the field path contains arrays
        has_array = "[*]" in field_path

        # Build constants lookup from VAR CONSTANT section
        constants = self._extract_constants(lines)

        results: list[tuple[int, str]] = []
        db_pattern = f'"{db_name}"'

        for i, line in enumerate(lines, 1):
            if db_pattern not in line or leaf not in line:
                continue
            if not has_array:
                results.append((i, ""))
                continue

            # Extract the actual index used on this line
            idx = self._extract_index_from_line(line, db_name, field_path)
            if idx is None:
                results.append((i, ""))
                continue

            # Resolve the index
            resolved = self._resolve_index(idx, lines, i, constants)
            results.append((i, resolved))

        return results

    def _extract_constants(self, lines: list[str]) -> dict[str, str]:
        """Extract VAR CONSTANT values from source lines.

        Returns mapping like {"ARM1": "1", "ARM2": "2", ...}.
        """
        import re

        constants: dict[str, str] = {}
        in_const = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("VAR CONSTANT") or stripped.startswith("VAR_CONSTANT"):
                in_const = True
                continue
            if in_const and stripped.startswith("END_VAR"):
                in_const = False
                continue
            if in_const:
                # Parse: NAME : Type := value;
                m = re.match(r"(\w+)\s*:\s*\w+\s*:=\s*(\d+)", stripped)
                if m:
                    constants[m.group(1)] = m.group(2)
        return constants

    def _extract_index_from_line(
        self,
        line: str,
        db_name: str,
        field_path: str,
    ) -> str | None:
        """Extract the array index value from a source line.

        For a line like: "ModuleData".items[#itemIndex].output.forward
        with field_path "arms[*].output.inboardBackward",
        returns "#armIndex".
        """
        import re

        # Find all [...] in this line after the DB name
        db_pos = line.find(f'"{db_name}"')
        if db_pos < 0:
            return None

        after_db = line[db_pos:]
        indices = re.findall(r"\[([^\]]+)\]", after_db)
        return indices[0].strip() if indices else None

    def _resolve_index(
        self,
        idx: str,
        lines: list[str],
        current_line: int,
        constants: dict[str, str],
    ) -> str:
        """Resolve an index expression to a value.

        Handles:
        - Literal numbers: "1" -> "1"
        - Hash-prefixed constants: "#ARM1" -> looks up ARM1 in constants -> "1"
        - Hash-prefixed variables: "#armIndex" -> backward scan for assignment
        - Plain constants: "ARM1" -> looks up in constants
        """
        import re

        raw = idx.strip()

        # Literal number
        if raw.isdigit():
            return raw

        # Strip # prefix for lookups
        name = raw.lstrip("#")

        # Check constants first
        if name in constants:
            return constants[name]

        # Backward scan for most recent assignment: #name := <value>;
        pattern = re.compile(rf"#?{re.escape(name)}\s*:=\s*(\d+)")
        for j in range(current_line - 2, -1, -1):
            m = pattern.search(lines[j])
            if m:
                return m.group(1)

        # Unresolvable — return the original expression
        return raw


# Global service instance
_service: AnalysisService | None = None


def get_service() -> AnalysisService:
    """Get the global service instance."""
    global _service
    if _service is None:
        _service = AnalysisService()
    return _service


def set_source_path(path: Path) -> None:
    """Set the source path for the global service."""
    get_service().set_source_path(path)
