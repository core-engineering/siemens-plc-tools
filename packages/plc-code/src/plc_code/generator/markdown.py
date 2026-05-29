"""Markdown generation for SCL documentation.

This module provides generation of MkDocs-compatible markdown files
from extracted SCL block documentation.
"""

from dataclasses import dataclass, field
from pathlib import Path

from plc_code.analyzer.db_crossref import get_variable_anchor_link
from plc_code.analyzer.db_extractor import BlockDBDependencies
from plc_code.analyzer.quality import BlockAnalysisResult, MarkdownReporter
from plc_code.analyzer.state_machine import StateMachine, generate_state_diagram_block
from plc_code.extractor.header import ExtractedHeader
from plc_code.extractor.interface import ExtractedInterface, InterfaceVariable, UDTField
from plc_code.parser.models import Block
from plc_code.testing.models import BlockTestResult
from plc_code.testing.reporter import TestReporter


@dataclass
class MarkdownOptions:
    """Options for markdown generation.

    Attributes
    ----------
    include_changelog : bool
        Whether to include changelog table.
    include_hidden_vars : bool
        Whether to include hidden variables.
    include_temp_vars : bool
        Whether to include temporary variables.
    include_constants : bool
        Whether to include constants section.
    show_access_modifiers : bool
        Whether to show access/visibility modifiers.
    include_source_code : bool
        Whether to include full source code in collapsible section.
    language_for_code_blocks : str
        Language identifier for code blocks (scl, text, etc.).
    """

    include_changelog: bool = True
    include_hidden_vars: bool = False
    include_temp_vars: bool = False
    include_constants: bool = True
    show_access_modifiers: bool = True
    include_source_code: bool = True
    language_for_code_blocks: str = "scl"


class MarkdownGenerator:
    """Generates markdown documentation for SCL blocks.

    Parameters
    ----------
    header : ExtractedHeader
        The extracted header information.
    interface : ExtractedInterface
        The extracted interface.
    options : MarkdownOptions | None
        Generation options.
    type_registry : dict[str, str] | None
        Mapping of type names to their relative paths (from docs root).

    Examples
    --------
    >>> generator = MarkdownGenerator(header, interface)
    >>> markdown = generator.generate()
    >>> print(markdown)
    """

    def __init__(
        self,
        header: ExtractedHeader,
        interface: ExtractedInterface,
        options: MarkdownOptions | None = None,
        type_registry: dict[str, str] | None = None,
        current_doc_path: str | None = None,
        source_code: str | None = None,
        state_machine: StateMachine | None = None,
        analysis_result: BlockAnalysisResult | None = None,
        test_result: BlockTestResult | None = None,
        db_dependencies: BlockDBDependencies | None = None,
    ) -> None:
        """Initialize the generator.

        Parameters
        ----------
        header : ExtractedHeader
            The extracted header.
        interface : ExtractedInterface
            The extracted interface.
        options : MarkdownOptions | None
            Optional generation options.
        type_registry : dict[str, str] | None
            Mapping of type names to their paths relative to docs root.
        current_doc_path : str | None
            Current document path relative to docs root (for computing relative links).
        source_code : str | None
            The original SCL source code to include in documentation.
        state_machine : StateMachine | None
            Extracted state machine for diagram generation.
        analysis_result : BlockAnalysisResult | None
            Quality analysis result for the block.
        test_result : BlockTestResult | None
            Unit test result for the block.
        db_dependencies : BlockDBDependencies | None
            Global DB dependencies for the block.
        """
        self.header = header
        self.interface = interface
        self.options = options or MarkdownOptions()
        self.type_registry = type_registry or {}
        self.current_doc_path = current_doc_path or ""
        self.source_code = source_code
        self.state_machine = state_machine
        self.analysis_result = analysis_result
        self.test_result = test_result
        self.db_dependencies = db_dependencies
        self._markdown_reporter = MarkdownReporter()
        self._test_reporter = TestReporter()
        self._lines: list[str] = []

    def generate(self) -> str:
        """Generate the complete markdown document.

        Returns
        -------
        str
            The generated markdown content.
        """
        self._lines = []

        # Title
        title = self.header.title or self.interface.block_name
        self._add_heading(1, title)

        # Block type badge
        self._add_block_type_badge()

        # Unit Tests badge (first)
        if self.test_result:
            self._add_test_badge()

        # Syntax Tests badge (second, with line break)
        if self.analysis_result:
            self._add_quality_badge()

        # Description
        if self.header.comment:
            self._add_line("")
            self._add_line(self.header.comment)

        # Metadata section
        self._add_metadata_section()

        # Description region content
        if self.header.description:
            self._add_line("")
            self._add_heading(2, "Description")
            self._add_line("")
            self._add_line(self.header.description)

        # State machine diagram (after description, before interface)
        if self.state_machine:
            self._add_state_machine_section()

        # Interface section
        if self.interface.block_type == "TYPE":
            self._add_udt_section()
        else:
            self._add_interface_section()

        # Global DB dependencies section
        if self.db_dependencies and self.db_dependencies.references:
            self._add_db_dependencies_section()

        # Quality analysis section (before changelog)
        if self.analysis_result and self.analysis_result.violations:
            self._add_quality_section()

        # Unit test section (before changelog)
        if self.test_result and self.test_result.has_tests:
            self._add_test_section()

        # Changelog
        if self.options.include_changelog and self.header.changelog:
            self._add_changelog_section()

        # Source code (collapsible)
        if self.options.include_source_code and self.source_code:
            self._add_source_code_section()

        return "\n".join(self._lines)

    def _add_line(self, line: str = "") -> None:
        """Add a line to the output."""
        self._lines.append(line)

    def _add_heading(self, level: int, text: str) -> None:
        """Add a heading."""
        prefix = "#" * level
        self._add_line(f"{prefix} {text}")

    def _add_block_type_badge(self) -> None:
        """Add a badge showing the block type."""
        block_type = self.interface.block_type

        if block_type == "FUNCTION_BLOCK":
            badge = "**Function Block**"
        elif block_type == "FUNCTION":
            return_type = self.interface.return_type or "Void"
            badge = f"**Function** → `{return_type}`"
        elif block_type == "TYPE":
            badge = "**User Data Type**"
        else:
            badge = f"**{block_type}**"

        self._add_line("")
        self._add_line(badge)

    def _add_quality_badge(self) -> None:
        """Add a syntax tests (quality) status badge."""
        if not self.analysis_result:
            return

        self._add_line("")  # Line break before syntax tests
        badge = self._markdown_reporter.generate_block_badge(self.analysis_result)
        self._add_line(f"**Syntax Tests:** {badge}")

    def _add_db_dependencies_section(self) -> None:
        """Add global DB dependencies section."""
        if not self.db_dependencies or not self.db_dependencies.references:
            return

        self._add_line("")
        self._add_heading(2, "Global Data Block Dependencies")
        self._add_line("")

        # Summary by DB
        from plc_code.analyzer.db_extractor import get_db_summary

        summary = get_db_summary(self.db_dependencies)

        for db_name in sorted(summary.keys()):
            fields = summary[db_name]
            # Determine access type for the entire DB
            is_read = db_name in self.db_dependencies.read_dbs
            is_write = db_name in self.db_dependencies.write_dbs

            if is_read and is_write:
                access_badge = "R/W"
            elif is_write:
                access_badge = "W"
            else:
                access_badge = "R"

            self._add_line(f"### `{db_name}` ({access_badge})")
            self._add_line("")

            # Table header
            self._add_line("| Variable | Access |")
            self._add_line("|----------|--------|")

            # Table rows with full qualified names and links to cross-reference
            for field_path in fields:
                # Build full qualified name
                full_ref = f'"{db_name}".{field_path}'

                # Determine per-field access type
                is_field_read = any(
                    r.full_reference == full_ref and not r.is_write for r in self.db_dependencies.references
                )
                is_field_write = any(
                    r.full_reference == full_ref and r.is_write for r in self.db_dependencies.references
                )

                if is_field_read and is_field_write:
                    field_access = "R/W"
                elif is_field_write:
                    field_access = "W"
                else:
                    field_access = "R"

                # Create clickable link to cross-reference
                if self.current_doc_path:
                    crossref_link = self._get_crossref_link(db_name, field_path)
                    self._add_line(f"| [`{full_ref}`]({crossref_link}) | {field_access} |")
                else:
                    self._add_line(f"| `{full_ref}` | {field_access} |")

            self._add_line("")

    def _get_crossref_link(self, db_name: str, field_path: str) -> str:
        """Get the relative link to a variable in the cross-reference.

        Parameters
        ----------
        db_name : str
            Name of the data block.
        field_path : str
            The field path.

        Returns
        -------
        str
            Relative link to the cross-reference entry.
        """
        # Get the anchor link (relative to global-data/)
        anchor_link = get_variable_anchor_link(db_name, field_path)

        # Compute relative path from current doc to global-data/
        if self.current_doc_path:
            return self._compute_relative_path(self.current_doc_path, anchor_link.removeprefix("../"))
        return anchor_link

    def _add_quality_section(self) -> None:
        """Add detailed quality issues section."""
        if not self.analysis_result or not self.analysis_result.violations:
            return

        details = self._markdown_reporter.generate_block_details(self.analysis_result)
        if details:
            self._add_line("")
            self._add_line(details)

    def _add_test_badge(self) -> None:
        """Add a unit tests status badge."""
        if not self.test_result:
            return

        self._add_line("")  # Line break after block type
        badge = self._test_reporter.generate_block_badge(self.test_result)
        self._add_line(f"**Unit Tests:** {badge}")

    def _add_test_section(self) -> None:
        """Add detailed test results section."""
        if not self.test_result or not self.test_result.has_tests:
            return

        section = self._test_reporter.generate_block_section(self.test_result)
        if section:
            self._add_line(section)

    def _add_metadata_section(self) -> None:
        """Add metadata section (author, library, version)."""
        metadata: list[tuple[str, str]] = []

        if self.header.library:
            metadata.append(("Library", self.header.library))
        if self.header.author:
            metadata.append(("Author", self.header.author))
        if self.header.copyright:
            metadata.append(("Copyright", self.header.copyright))

        if metadata:
            self._add_line("")
            for key, value in metadata:
                self._add_line(f"- **{key}:** {value}")

    def _add_state_machine_section(self) -> None:
        """Add state machine diagram section."""
        if not self.state_machine:
            return

        self._add_line("")
        self._add_heading(2, "State Machine")
        self._add_line("")

        # Statistics
        self._add_line(f"- **States:** {self.state_machine.state_count}")
        self._add_line(f"- **Transitions:** {self.state_machine.transition_count}")
        if self.state_machine.initial_state:
            self._add_line(f"- **Initial State:** `{self.state_machine.initial_state}`")
        self._add_line("")

        # Diagram
        diagram = generate_state_diagram_block(self.state_machine)
        self._add_line(diagram)

        # State table
        self._add_line("")
        self._add_heading(3, "States")
        self._add_line("")
        self._add_line("| State | Value | Description |")
        self._add_line("|-------|-------|-------------|")
        for state in self.state_machine.states:
            description = state.description if state.description else "-"
            self._add_line(f"| `{state.name}` | `{state.value}` | {description} |")

    def _add_interface_section(self) -> None:
        """Add the interface section for function blocks and functions."""
        # Inputs
        if self.interface.inputs:
            self._add_line("")
            self._add_heading(2, "Inputs")
            self._add_variable_table(self.interface.inputs)

        # Outputs
        if self.interface.outputs:
            self._add_line("")
            self._add_heading(2, "Outputs")
            self._add_variable_table(self.interface.outputs)

        # In-Outs
        if self.interface.in_outs:
            self._add_line("")
            self._add_heading(2, "In-Out Parameters")
            self._add_variable_table(self.interface.in_outs)

        # Static variables
        static_vars = self._filter_static_vars()
        if static_vars:
            self._add_line("")
            self._add_heading(2, "Static Variables")
            self._add_variable_table(static_vars)

        # Temp variables (optional)
        if self.options.include_temp_vars and self.interface.temp_vars:
            self._add_line("")
            self._add_heading(2, "Temporary Variables")
            self._add_variable_table(self.interface.temp_vars)

        # Constants (optional)
        if self.options.include_constants and self.interface.constants:
            self._add_line("")
            self._add_heading(2, "Constants")
            self._add_constant_table(self.interface.constants)

    def _filter_static_vars(self) -> list[InterfaceVariable]:
        """Filter static variables based on options."""
        if self.options.include_hidden_vars:
            return self.interface.static_vars

        return [var for var in self.interface.static_vars if var.visibility != "Hidden"]

    def _add_variable_table(self, variables: list[InterfaceVariable]) -> None:
        """Add a variable table."""
        self._add_line("")

        # Determine columns based on options
        if self.options.show_access_modifiers:
            has_access = any(var.access for var in variables)
        else:
            has_access = False

        # Header
        if has_access:
            self._add_line("| Name | Type | Access | Description |")
            self._add_line("|------|------|--------|-------------|")
        else:
            self._add_line("| Name | Type | Description |")
            self._add_line("|------|------|-------------|")

        # Rows
        for var in variables:
            name = f"`{var.name}`"
            data_type = self._format_type(var.data_type)
            description = var.description or ""

            # Add default value to description if present
            if var.default_value:
                if description:
                    description = f"{description} (default: `{var.default_value}`)"
                else:
                    description = f"Default: `{var.default_value}`"

            if has_access:
                access = var.access or "-"
                self._add_line(f"| {name} | {data_type} | {access} | {description} |")
            else:
                self._add_line(f"| {name} | {data_type} | {description} |")

    def _add_constant_table(self, constants: list[InterfaceVariable]) -> None:
        """Add a constants table."""
        self._add_line("")
        self._add_line("| Name | Type | Value | Description |")
        self._add_line("|------|------|-------|-------------|")

        for const in constants:
            name = f"`{const.name}`"
            data_type = self._format_type(const.data_type)
            value = f"`{const.default_value}`" if const.default_value else "-"
            description = const.description or ""

            self._add_line(f"| {name} | {data_type} | {value} | {description} |")

    def _add_udt_section(self) -> None:
        """Add the UDT fields section."""
        if not self.interface.udt_fields:
            return

        self._add_line("")
        self._add_heading(2, "Fields")
        self._add_udt_table(self.interface.udt_fields)

    def _add_udt_table(self, fields: list[UDTField]) -> None:
        """Add a UDT fields table."""
        self._add_line("")
        self._add_line("| Field | Type | Description |")
        self._add_line("|-------|------|-------------|")

        for udt_field in fields:
            name = f"`{udt_field.name}`"
            data_type = self._format_type(udt_field.data_type)
            description = udt_field.description or ""

            self._add_line(f"| {name} | {data_type} | {description} |")

    def _add_changelog_section(self) -> None:
        """Add the changelog section."""
        self._add_line("")
        self._add_heading(2, "Changelog")
        self._add_line("")
        self._add_line("| Version | Date | Author | Changes |")
        self._add_line("|---------|------|--------|---------|")

        for entry in self.header.changelog:
            version = entry.version
            date = entry.date
            author = entry.author
            changes = entry.changes

            self._add_line(f"| {version} | {date} | {author} | {changes} |")

    def _add_source_code_section(self) -> None:
        """Add the source code section in a collapsible details block."""
        if not self.source_code:
            return

        self._add_line("")
        self._add_heading(2, "Source Code")
        self._add_line("")
        self._add_line('<details markdown="1">')
        self._add_line("<summary>Click to expand SCL source</summary>")
        self._add_line("")
        self._add_line(f"```{self.options.language_for_code_blocks}")
        # Add source code, removing any trailing whitespace
        self._add_line(self.source_code.rstrip())
        self._add_line("```")
        self._add_line("")
        self._add_line("</details>")

    def _format_type(self, data_type: str) -> str:
        """Format a data type for display.

        Parameters
        ----------
        data_type : str
            The raw data type string.

        Returns
        -------
        str
            Formatted type string.
        """
        # Handle library types
        if data_type.startswith("_."):
            type_name = data_type[2:]

            # Check if we have a registry entry for this type
            if type_name in self.type_registry and self.current_doc_path:
                target_path = self.type_registry[type_name]
                relative_link = self._compute_relative_path(self.current_doc_path, target_path)
                return f"[`{type_name}`]({relative_link})"

            # Fallback: just use the type name without link
            return f"`{type_name}`"

        return f"`{data_type}`"

    def _compute_relative_path(self, from_path: str, to_path: str) -> str:
        """Compute relative path from one doc to another.

        Parameters
        ----------
        from_path : str
            Current document path (e.g., "types/Parameters/typeA.md").
        to_path : str
            Target document path (e.g., "types/Data/typeB.md").

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


def generate_markdown(
    header: ExtractedHeader,
    interface: ExtractedInterface,
    options: MarkdownOptions | None = None,
    type_registry: dict[str, str] | None = None,
    current_doc_path: str | None = None,
    source_code: str | None = None,
    state_machine: StateMachine | None = None,
    analysis_result: BlockAnalysisResult | None = None,
    test_result: BlockTestResult | None = None,
    db_dependencies: BlockDBDependencies | None = None,
) -> str:
    """Convenience function to generate markdown.

    Parameters
    ----------
    header : ExtractedHeader
        The extracted header.
    interface : ExtractedInterface
        The extracted interface.
    options : MarkdownOptions | None
        Optional generation options.
    type_registry : dict[str, str] | None
        Mapping of type names to their paths relative to docs root.
    current_doc_path : str | None
        Current document path relative to docs root (for computing relative links).
    source_code : str | None
        The original SCL source code to include in documentation.
    state_machine : StateMachine | None
        Extracted state machine for diagram generation.
    analysis_result : BlockAnalysisResult | None
        Quality analysis result for the block.
    test_result : BlockTestResult | None
        Unit test result for the block.
    db_dependencies : BlockDBDependencies | None
        Global DB dependencies for the block.

    Returns
    -------
    str
        The generated markdown.
    """
    generator = MarkdownGenerator(
        header,
        interface,
        options,
        type_registry,
        current_doc_path,
        source_code,
        state_machine,
        analysis_result,
        test_result,
        db_dependencies,
    )
    return generator.generate()


def generate_block_markdown(
    block: Block,
    header: ExtractedHeader,
    interface: ExtractedInterface,
    output_path: Path,
    options: MarkdownOptions | None = None,
) -> None:
    """Generate markdown file for a block.

    Parameters
    ----------
    block : Block
        The parsed block.
    header : ExtractedHeader
        The extracted header.
    interface : ExtractedInterface
        The extracted interface.
    output_path : Path
        Path to write the markdown file.
    options : MarkdownOptions | None
        Optional generation options.
    """
    content = generate_markdown(header, interface, options)
    output_path.write_text(content, encoding="utf-8")


@dataclass
class NavEntry:
    """A navigation entry for mkdocs.yml.

    Attributes
    ----------
    title : str
        Display title.
    path : str
        Path to markdown file.
    children : list[NavEntry]
        Nested entries.
    """

    title: str
    path: str = ""
    children: list["NavEntry"] = field(default_factory=list)

    def to_dict(self) -> dict | str:
        """Convert to mkdocs.yml nav format."""
        if self.children:
            return {self.title: [child.to_dict() for child in self.children]}
        return {self.title: self.path}


def generate_nav_entry(
    block_name: str,
    block_type: str,
    relative_path: str,
) -> NavEntry:
    """Generate a navigation entry for a block.

    Parameters
    ----------
    block_name : str
        Name of the block.
    block_type : str
        Type of block.
    relative_path : str
        Relative path to markdown file.

    Returns
    -------
    NavEntry
        The navigation entry.
    """
    return NavEntry(title=block_name, path=relative_path)
