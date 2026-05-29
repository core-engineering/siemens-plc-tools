"""Cross-reference data structures for global data block dependencies.

This module provides functionality to aggregate block-level DB dependencies
into a global cross-reference showing which blocks read/write each global variable.
"""

import re
from dataclasses import dataclass, field

from plc_code.analyzer.db_extractor import BlockDBDependencies


@dataclass
class VariableReference:
    """A reference to a global variable from a specific block.

    Attributes
    ----------
    block_name : str
        Name of the block that references this variable.
    is_write : bool
        True if this is a write access.
    doc_path : str
        Path to the block's documentation file.
    original_indices : list[str]
        Original array indices before normalization (e.g., ["#armIndex", "1"]).
    """

    block_name: str
    is_write: bool = False
    doc_path: str = ""
    original_indices: list[str] = field(default_factory=list)


@dataclass
class GlobalVariable:
    """A global variable with all its cross-references.

    Attributes
    ----------
    db_name : str
        Name of the data block (e.g., "ProcessData").
    normalized_path : str
        Field path with arrays normalized to [*] (e.g., "arms[*].status.parked").
    full_reference : str
        Complete reference (e.g., '"ProcessData".arms[*].status.parked').
    readers : list[VariableReference]
        Blocks that read this variable.
    writers : list[VariableReference]
        Blocks that write this variable.
    """

    db_name: str
    normalized_path: str
    full_reference: str
    readers: list[VariableReference] = field(default_factory=list)
    writers: list[VariableReference] = field(default_factory=list)

    @property
    def access_type(self) -> str:
        """Get the access type (R, W, or R/W)."""
        has_readers = len(self.readers) > 0
        has_writers = len(self.writers) > 0

        if has_readers and has_writers:
            return "R/W"
        elif has_writers:
            return "W"
        else:
            return "R"


@dataclass
class DBCrossReference:
    """Cross-reference of all global data block variables.

    Attributes
    ----------
    variables : dict[str, GlobalVariable]
        All variables, keyed by normalized full reference.
    by_db : dict[str, list[GlobalVariable]]
        Variables grouped by data block name.
    """

    variables: dict[str, GlobalVariable] = field(default_factory=dict)
    by_db: dict[str, list[GlobalVariable]] = field(default_factory=dict)

    @property
    def total_dbs(self) -> int:
        """Get the total number of data blocks."""
        return len(self.by_db)

    @property
    def total_variables(self) -> int:
        """Get the total number of unique variables."""
        return len(self.variables)


# Pattern to match array indices: [1], [#armIndex], etc.
ARRAY_INDEX_PATTERN = re.compile(r"\[([^\]]+)\]")


def normalize_array_indices(field_path: str) -> tuple[str, list[str]]:
    """Normalize array indices to wildcards.

    Converts specific array indices to [*] wildcard for grouping
    similar accesses together.

    Parameters
    ----------
    field_path : str
        Field path that may contain array indices.

    Returns
    -------
    tuple[str, list[str]]
        Tuple of (normalized_path, original_indices).

    Examples
    --------
    >>> normalize_array_indices("arms[#armIndex].status.parked")
    ("arms[*].status.parked", ["#armIndex"])

    >>> normalize_array_indices("arms[1].status[2].value")
    ("arms[*].status[*].value", ["1", "2"])

    >>> normalize_array_indices("controller.status.running")
    ("controller.status.running", [])
    """
    original_indices: list[str] = []

    def replace_index(match: re.Match[str]) -> str:
        index = match.group(1)
        original_indices.append(index)
        return "[*]"

    normalized = ARRAY_INDEX_PATTERN.sub(replace_index, field_path)
    return normalized, original_indices


def _is_valid_field_path(field_path: str) -> bool:
    """Check if a field path is valid (complete).

    Parameters
    ----------
    field_path : str
        The field path to validate.

    Returns
    -------
    bool
        True if the path is valid, False otherwise.
    """
    # Check for unclosed brackets (e.g., "arms[" without closing "]")
    if field_path.endswith("["):
        return False

    # Check for balanced brackets
    open_count = field_path.count("[")
    close_count = field_path.count("]")
    if open_count != close_count:
        return False

    # Check for empty path
    if not field_path or not field_path.strip():
        return False

    return True


def build_db_crossref(
    all_deps: list[BlockDBDependencies],
    doc_paths: dict[str, str],
) -> DBCrossReference:
    """Aggregate all block dependencies into a cross-reference.

    Parameters
    ----------
    all_deps : list[BlockDBDependencies]
        Dependencies from all blocks.
    doc_paths : dict[str, str]
        Mapping of block names to their documentation paths.

    Returns
    -------
    DBCrossReference
        Aggregated cross-reference data.
    """
    crossref = DBCrossReference()

    for deps in all_deps:
        block_name = deps.block_name
        doc_path = doc_paths.get(block_name, "")

        for ref in deps.references:
            # Skip invalid field paths (e.g., incomplete array access)
            if not _is_valid_field_path(ref.field_path):
                continue
            # Normalize the field path to group array accesses
            normalized_path, original_indices = normalize_array_indices(ref.field_path)
            normalized_full_ref = f'"{ref.db_name}".{normalized_path}'

            # Get or create the global variable entry
            if normalized_full_ref not in crossref.variables:
                var = GlobalVariable(
                    db_name=ref.db_name,
                    normalized_path=normalized_path,
                    full_reference=normalized_full_ref,
                )
                crossref.variables[normalized_full_ref] = var

                # Also index by DB name
                if ref.db_name not in crossref.by_db:
                    crossref.by_db[ref.db_name] = []
                crossref.by_db[ref.db_name].append(var)
            else:
                var = crossref.variables[normalized_full_ref]

            # Create the reference entry
            var_ref = VariableReference(
                block_name=block_name,
                is_write=ref.is_write,
                doc_path=doc_path,
                original_indices=original_indices,
            )

            # Add to readers or writers (avoid duplicates)
            if ref.is_write:
                # Check if this block is already in writers
                if not any(w.block_name == block_name for w in var.writers):
                    var.writers.append(var_ref)
                # Also add to readers if we haven't already
                if not any(r.block_name == block_name for r in var.readers):
                    # Check if there's a read-only access from this block
                    read_only_refs = [
                        r
                        for r in deps.references
                        if r.field_path == ref.field_path and r.db_name == ref.db_name and not r.is_write
                    ]
                    if read_only_refs:
                        var.readers.append(
                            VariableReference(
                                block_name=block_name,
                                is_write=False,
                                doc_path=doc_path,
                                original_indices=original_indices,
                            )
                        )
            else:
                # Read-only access
                if not any(r.block_name == block_name for r in var.readers):
                    var.readers.append(var_ref)

    # Sort variables within each DB by normalized path
    for db_name in crossref.by_db:
        crossref.by_db[db_name].sort(key=lambda v: v.normalized_path)

    return crossref


def generate_crossref_index(crossref: DBCrossReference) -> str:
    """Generate the main index page for the cross-reference.

    Parameters
    ----------
    crossref : DBCrossReference
        The cross-reference data.

    Returns
    -------
    str
        Markdown content for index.md.
    """
    lines = [
        "# Global Data Block Cross-Reference",
        "",
        "This section documents all global data block variables and which blocks",
        "read and write them. Click on a data block to explore its variables.",
        "",
        ":material-clipboard-check: **[View Audit Report](audit.md)** - "
        "Check for issues with global variable usage",
        "",
        "## Statistics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Data Blocks | {crossref.total_dbs} |",
        f"| Total Variables | {crossref.total_variables} |",
        "",
        "## Data Blocks",
        "",
        "| Data Block | Variables | R/W | Read-Only | Write-Only |",
        "|------------|-----------|-----|-----------|------------|",
    ]

    # Generate table row for each DB
    for db_name in sorted(crossref.by_db.keys()):
        variables = crossref.by_db[db_name]
        total = len(variables)
        rw_count = sum(1 for v in variables if v.access_type == "R/W")
        r_count = sum(1 for v in variables if v.access_type == "R")
        w_count = sum(1 for v in variables if v.access_type == "W")

        lines.append(f"| [`{db_name}`]({db_name}.md) | {total} | {rw_count} | {r_count} | {w_count} |")

    lines.append("")
    return "\n".join(lines)


def generate_db_page(
    db_name: str,
    variables: list[GlobalVariable],
    base_path: str = "",
) -> str:
    """Generate a per-DB page with collapsible hierarchy.

    Parameters
    ----------
    db_name : str
        Name of the data block.
    variables : list[GlobalVariable]
        Variables in this data block.
    base_path : str
        Base path for computing relative links to block docs.

    Returns
    -------
    str
        Markdown content for the DB page.
    """
    lines = [
        f"# `{db_name}`",
        "",
        f"Global variables in the `{db_name}` data block.",
        "",
        "## Statistics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Variables | {len(variables)} |",
        f"| Read/Write | {sum(1 for v in variables if v.access_type == 'R/W')} |",
        f"| Read-Only | {sum(1 for v in variables if v.access_type == 'R')} |",
        f"| Write-Only | {sum(1 for v in variables if v.access_type == 'W')} |",
        "",
        "## Variables",
        "",
    ]

    # Build hierarchical structure from normalized paths
    hierarchy = _build_path_hierarchy(variables)

    # Generate collapsible sections
    _generate_hierarchy_markdown(lines, hierarchy, db_name, base_path, depth=0)

    return "\n".join(lines)


def _build_path_hierarchy(
    variables: list[GlobalVariable],
) -> dict:
    """Build a hierarchical tree from variable paths.

    Parameters
    ----------
    variables : list[GlobalVariable]
        Variables to organize.

    Returns
    -------
    dict
        Nested dictionary representing the path hierarchy.
        Leaf nodes have "_var" key with the GlobalVariable.
    """
    root: dict = {}

    for var in variables:
        # Split path into parts (e.g., "arms[*].status.parked" -> ["arms[*]", "status", "parked"])
        parts = var.normalized_path.split(".")
        current = root

        for i, part in enumerate(parts):
            if part not in current:
                current[part] = {}
            if i == len(parts) - 1:
                # Leaf node - store the variable
                current[part]["_var"] = var
            else:
                current = current[part]

    return root


def _generate_hierarchy_markdown(
    lines: list[str],
    hierarchy: dict,
    db_name: str,
    base_path: str,
    depth: int,
    path_prefix: str = "",
) -> None:
    """Recursively generate markdown for the hierarchy.

    Parameters
    ----------
    lines : list[str]
        Lines to append to.
    hierarchy : dict
        Current level of the hierarchy.
    db_name : str
        Name of the data block.
    base_path : str
        Base path for relative links.
    depth : int
        Current nesting depth.
    path_prefix : str
        Accumulated path prefix for anchor generation.
    """
    # Sort keys, putting _var last
    keys = sorted(k for k in hierarchy.keys() if k != "_var")

    for key in keys:
        value = hierarchy[key]
        current_path = f"{path_prefix}.{key}" if path_prefix else key

        # Check if this is a leaf node (has _var) or has children
        has_var = "_var" in value
        has_children = any(k != "_var" for k in value.keys())

        if has_var and not has_children:
            # Pure leaf node - render the variable directly
            var = value["_var"]
            anchor = _path_to_anchor(var.normalized_path)
            lines.append(f'<a id="{anchor}"></a>')
            lines.append("")
            lines.append(f"### `{var.normalized_path}`")
            lines.append("")
            _render_variable_table(lines, var, base_path)
            lines.append("")

        elif has_children:
            # Has children - use collapsible section
            child_count = _count_variables(value)
            # Determine if we should default to open (fewer items) or closed
            open_attr = " open" if child_count <= 5 else ""

            if has_var:
                # Mixed node - has both a variable and children
                var = value["_var"]
                anchor = _path_to_anchor(var.normalized_path)
                lines.append(f'<a id="{anchor}"></a>')
                lines.append("")
                lines.append(
                    f'<details{open_attr} markdown="1"><summary><code>{key}</code> '
                    f"({child_count} variables)</summary>"
                )
                lines.append("")
                lines.append("**This node:**")
                lines.append("")
                _render_variable_table(lines, var, base_path)
                lines.append("")
            else:
                # Pure branch node
                lines.append(
                    f'<details{open_attr} markdown="1"><summary><code>{key}</code> '
                    f"({child_count} variables)</summary>"
                )
                lines.append("")

            # Recurse into children
            _generate_hierarchy_markdown(lines, value, db_name, base_path, depth + 1, current_path)

            lines.append("</details>")
            lines.append("")


def _count_variables(hierarchy: dict) -> int:
    """Count total variables in a hierarchy subtree."""
    count = 0
    for key, value in hierarchy.items():
        if key == "_var":
            count += 1
        elif isinstance(value, dict):
            count += _count_variables(value)
    return count


def _render_variable_table(
    lines: list[str],
    var: GlobalVariable,
    base_path: str,
) -> None:
    """Render a single variable as a small table.

    Parameters
    ----------
    lines : list[str]
        Lines to append to.
    var : GlobalVariable
        The variable to render.
    base_path : str
        Base path for relative links.
    """
    readers_str = _format_block_links(var.readers, base_path)
    writers_str = _format_block_links(var.writers, base_path)

    lines.append("| Access | Readers | Writers |")
    lines.append("|--------|---------|---------|")
    lines.append(f"| {var.access_type} | {readers_str} | {writers_str} |")


def _path_to_anchor(normalized_path: str) -> str:
    """Convert a normalized path to an HTML anchor ID.

    Parameters
    ----------
    normalized_path : str
        The normalized variable path.

    Returns
    -------
    str
        A valid HTML anchor ID.

    Examples
    --------
    >>> _path_to_anchor("arms[*].status.parked")
    "arms-status-parked"
    """
    # Remove array notation, replace dots with dashes, lowercase
    anchor = re.sub(r"\[\*\]", "", normalized_path)
    anchor = anchor.replace(".", "-").lower()
    # Remove any leading/trailing dashes
    anchor = anchor.strip("-")
    # Replace multiple dashes with single dash
    anchor = re.sub(r"-+", "-", anchor)
    return anchor


def get_variable_anchor_link(db_name: str, field_path: str) -> str:
    """Get the link to a variable in the cross-reference.

    Parameters
    ----------
    db_name : str
        Name of the data block.
    field_path : str
        The field path (may contain specific indices).

    Returns
    -------
    str
        Relative link to the variable's cross-reference entry.
    """
    # Normalize the field path for anchor
    normalized_path, _ = normalize_array_indices(field_path)
    anchor = _path_to_anchor(normalized_path)
    return f"../global-data/{db_name}.md#{anchor}"


def generate_crossref_markdown(
    crossref: DBCrossReference,
    base_path: str = "",
) -> str:
    """Generate markdown documentation for the cross-reference.

    DEPRECATED: Use generate_crossref_index() and generate_db_page() instead.

    Parameters
    ----------
    crossref : DBCrossReference
        The cross-reference data.
    base_path : str
        Base path for computing relative links to block docs.

    Returns
    -------
    str
        Markdown content.
    """
    # Keep for backwards compatibility, but use new format
    return generate_crossref_index(crossref)


def _format_block_links(refs: list[VariableReference], base_path: str) -> str:
    """Format a list of block references as markdown links.

    Parameters
    ----------
    refs : list[VariableReference]
        References to format.
    base_path : str
        Base path for computing relative links.

    Returns
    -------
    str
        Formatted string with links, or "-" if empty.
    """
    if not refs:
        return "-"

    links = []
    for ref in sorted(refs, key=lambda r: r.block_name):
        if ref.doc_path:
            # Compute relative path from base_path to doc_path
            link_path = _compute_relative_path(base_path, ref.doc_path)
            links.append(f"[{ref.block_name}]({link_path})")
        else:
            links.append(ref.block_name)

    return ", ".join(links)


def _compute_relative_path(from_path: str, to_path: str) -> str:
    """Compute relative path from one doc to another.

    Parameters
    ----------
    from_path : str
        Current document path (e.g., "global-data/index.md").
    to_path : str
        Target document path (e.g., "plc-blocks/MyBlock/MyBlock.md").

    Returns
    -------
    str
        Relative path from from_path to to_path.
    """
    from pathlib import PurePosixPath

    from_parts = PurePosixPath(from_path).parent.parts
    to_parts = PurePosixPath(to_path).parts

    # Find common prefix
    common_length = 0
    for i in range(min(len(from_parts), len(to_parts) - 1)):
        if from_parts[i] == to_parts[i]:
            common_length = i + 1
        else:
            break

    # Go up from current location
    ups = len(from_parts) - common_length
    up_path = "../" * ups

    # Go down to target
    down_parts = to_parts[common_length:]

    return up_path + "/".join(down_parts)
