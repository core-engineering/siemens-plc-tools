"""Tests for markdown generation."""

from pathlib import Path

from plc_code.extractor.header import ExtractedHeader
from plc_code.extractor.interface import (
    ExtractedInterface,
    InterfaceSection,
    InterfaceVariable,
    UDTField,
)
from plc_code.generator.markdown import (
    MarkdownGenerator,
    MarkdownOptions,
    NavEntry,
    generate_block_markdown,
    generate_markdown,
    generate_nav_entry,
)
from plc_code.parser.models import Block, ChangeLogEntry


class TestMarkdownOptions:
    """Tests for MarkdownOptions dataclass."""

    def test_default_values(self) -> None:
        """Test default option values."""
        options = MarkdownOptions()

        assert options.include_changelog is True
        assert options.include_hidden_vars is False
        assert options.include_temp_vars is False
        assert options.include_constants is True
        assert options.show_access_modifiers is True
        assert options.language_for_code_blocks == "scl"


class TestMarkdownGenerator:
    """Tests for MarkdownGenerator class."""

    def test_generate_empty_block(self) -> None:
        """Test generating markdown for empty block."""
        header = ExtractedHeader()
        interface = ExtractedInterface(
            block_name="EmptyBlock",
            block_type="FUNCTION_BLOCK",
        )

        generator = MarkdownGenerator(header, interface)
        result = generator.generate()

        assert "# EmptyBlock" in result
        assert "**Function Block**" in result

    def test_generate_with_title(self) -> None:
        """Test that header title takes precedence."""
        header = ExtractedHeader(title="DisplayTitle")
        interface = ExtractedInterface(
            block_name="InternalName",
            block_type="FUNCTION_BLOCK",
        )

        result = generate_markdown(header, interface)

        assert "# DisplayTitle" in result
        assert "# InternalName" not in result

    def test_generate_function_with_return_type(self) -> None:
        """Test generating markdown for function with return type."""
        header = ExtractedHeader(title="Calculate")
        interface = ExtractedInterface(
            block_name="Calculate",
            block_type="FUNCTION",
            return_type="Real",
        )

        result = generate_markdown(header, interface)

        assert "**Function** → `Real`" in result

    def test_generate_function_void_return(self) -> None:
        """Test generating markdown for function without return type."""
        header = ExtractedHeader()
        interface = ExtractedInterface(
            block_name="DoSomething",
            block_type="FUNCTION",
            return_type=None,
        )

        result = generate_markdown(header, interface)

        assert "**Function** → `Void`" in result

    def test_generate_udt_badge(self) -> None:
        """Test generating markdown for UDT."""
        header = ExtractedHeader()
        interface = ExtractedInterface(
            block_name="typeConfig",
            block_type="TYPE",
        )

        result = generate_markdown(header, interface)

        assert "**User Data Type**" in result

    def test_generate_with_comment(self) -> None:
        """Test generating markdown with block comment."""
        header = ExtractedHeader(
            title="MotorStarter",
            comment="Manage the motor starter state machine",
        )
        interface = ExtractedInterface(
            block_name="MotorStarter",
            block_type="FUNCTION_BLOCK",
        )

        result = generate_markdown(header, interface)

        assert "Manage the motor starter state machine" in result

    def test_generate_metadata_section(self) -> None:
        """Test generating metadata section."""
        header = ExtractedHeader(
            title="Test",
            library="ProcessLib",
            author="Example Author",
            copyright="(c) 2025 Example Author",
        )
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
        )

        result = generate_markdown(header, interface)

        assert "**Library:** ProcessLib" in result
        assert "**Author:** Example Author" in result
        assert "**Copyright:** (c) 2025 Example Author" in result

    def test_generate_description_section(self) -> None:
        """Test generating description section."""
        header = ExtractedHeader(
            title="Test",
            description="This block controls the hydraulic system.\n\n" "Key features:\n- Pressure control",
        )
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
        )

        result = generate_markdown(header, interface)

        assert "## Description" in result
        assert "This block controls the hydraulic system" in result
        assert "Key features:" in result


class TestVariableTables:
    """Tests for variable table generation."""

    def test_generate_inputs_table(self) -> None:
        """Test generating inputs table."""
        header = ExtractedHeader()
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[
                InterfaceSection(
                    section_type="VAR_INPUT",
                    variables=[
                        InterfaceVariable(
                            name="trigger",
                            data_type="Bool",
                            description="Start the operation",
                        ),
                        InterfaceVariable(
                            name="setpoint",
                            data_type="Real",
                            default_value="0.0",
                        ),
                    ],
                )
            ],
        )

        result = generate_markdown(header, interface)

        assert "## Inputs" in result
        assert "`trigger`" in result
        assert "`Bool`" in result
        assert "Start the operation" in result
        assert "Default: `0.0`" in result

    def test_generate_outputs_table(self) -> None:
        """Test generating outputs table."""
        header = ExtractedHeader()
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[
                InterfaceSection(
                    section_type="VAR_OUTPUT",
                    variables=[
                        InterfaceVariable(
                            name="result",
                            data_type="Real",
                            description="Calculation result",
                        ),
                    ],
                )
            ],
        )

        result = generate_markdown(header, interface)

        assert "## Outputs" in result
        assert "`result`" in result

    def test_generate_inout_table(self) -> None:
        """Test generating in-out parameters table."""
        header = ExtractedHeader()
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[
                InterfaceSection(
                    section_type="VAR_IN_OUT",
                    variables=[
                        InterfaceVariable(
                            name="data",
                            data_type="Array[0..99] of Real",
                        ),
                    ],
                )
            ],
        )

        result = generate_markdown(header, interface)

        assert "## In-Out Parameters" in result
        assert "`data`" in result

    def test_generate_with_access_modifiers(self) -> None:
        """Test generating table with access modifiers."""
        header = ExtractedHeader()
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[
                InterfaceSection(
                    section_type="VAR_OUTPUT",
                    variables=[
                        InterfaceVariable(
                            name="status",
                            data_type="USInt",
                            access="ReadOnly",
                        ),
                    ],
                )
            ],
        )

        result = generate_markdown(header, interface)

        assert "| Access |" in result
        assert "| ReadOnly |" in result

    def test_generate_without_access_modifiers(self) -> None:
        """Test generating table without access modifiers."""
        options = MarkdownOptions(show_access_modifiers=False)
        header = ExtractedHeader()
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[
                InterfaceSection(
                    section_type="VAR_INPUT",
                    variables=[
                        InterfaceVariable(
                            name="input",
                            data_type="Bool",
                            access="ReadWrite",
                        ),
                    ],
                )
            ],
        )

        result = generate_markdown(header, interface, options)

        assert "| Access |" not in result

    def test_generate_static_vars_hidden_excluded(self) -> None:
        """Test that hidden static vars are excluded by default."""
        header = ExtractedHeader()
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[
                InterfaceSection(
                    section_type="VAR",
                    variables=[
                        InterfaceVariable(
                            name="visible",
                            data_type="Int",
                            visibility="",
                        ),
                        InterfaceVariable(
                            name="hidden",
                            data_type="Int",
                            visibility="Hidden",
                        ),
                    ],
                )
            ],
        )

        result = generate_markdown(header, interface)

        assert "`visible`" in result
        assert "`hidden`" not in result

    def test_generate_static_vars_hidden_included(self) -> None:
        """Test that hidden static vars can be included."""
        options = MarkdownOptions(include_hidden_vars=True)
        header = ExtractedHeader()
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[
                InterfaceSection(
                    section_type="VAR",
                    variables=[
                        InterfaceVariable(
                            name="hidden",
                            data_type="Int",
                            visibility="Hidden",
                        ),
                    ],
                )
            ],
        )

        result = generate_markdown(header, interface, options)

        assert "`hidden`" in result

    def test_generate_temp_vars_excluded_by_default(self) -> None:
        """Test that temp vars are excluded by default."""
        header = ExtractedHeader()
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[
                InterfaceSection(
                    section_type="VAR_TEMP",
                    variables=[
                        InterfaceVariable(name="temp", data_type="Int"),
                    ],
                )
            ],
        )

        result = generate_markdown(header, interface)

        assert "## Temporary Variables" not in result

    def test_generate_temp_vars_included(self) -> None:
        """Test that temp vars can be included."""
        options = MarkdownOptions(include_temp_vars=True)
        header = ExtractedHeader()
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[
                InterfaceSection(
                    section_type="VAR_TEMP",
                    variables=[
                        InterfaceVariable(name="temp", data_type="Int"),
                    ],
                )
            ],
        )

        result = generate_markdown(header, interface, options)

        assert "## Temporary Variables" in result
        assert "`temp`" in result

    def test_generate_constants_table(self) -> None:
        """Test generating constants table."""
        header = ExtractedHeader()
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[
                InterfaceSection(
                    section_type="VAR_CONSTANT",
                    is_constant=True,
                    variables=[
                        InterfaceVariable(
                            name="MAX_VALUE",
                            data_type="Int",
                            default_value="100",
                            description="Maximum allowed value",
                        ),
                    ],
                )
            ],
        )

        result = generate_markdown(header, interface)

        assert "## Constants" in result
        assert "`MAX_VALUE`" in result
        assert "`100`" in result
        assert "Maximum allowed value" in result


class TestLibraryTypeLinks:
    """Tests for library type linking."""

    def test_library_type_linked_with_registry(self) -> None:
        """Test that library types get linked when registry is provided."""
        header = ExtractedHeader()
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[
                InterfaceSection(
                    section_type="VAR_INPUT",
                    variables=[
                        InterfaceVariable(
                            name="alarm",
                            data_type="_.MotorStarter",
                            is_library_type=True,
                        ),
                    ],
                )
            ],
        )

        # With registry and current path, links are generated
        type_registry = {"MotorStarter": "types/Process/MotorStarter.md"}
        current_doc_path = "blocks/Process/Test.md"

        result = generate_markdown(
            header, interface, type_registry=type_registry, current_doc_path=current_doc_path
        )

        assert "[`MotorStarter`](../../types/Process/MotorStarter.md)" in result

    def test_library_type_without_registry(self) -> None:
        """Test that library types display without link when no registry."""
        header = ExtractedHeader()
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[
                InterfaceSection(
                    section_type="VAR_INPUT",
                    variables=[
                        InterfaceVariable(
                            name="alarm",
                            data_type="_.MotorStarter",
                            is_library_type=True,
                        ),
                    ],
                )
            ],
        )

        # Without registry, no link is generated
        result = generate_markdown(header, interface)

        # Should show type name without link
        assert "`MotorStarter`" in result
        assert "[`MotorStarter`]" not in result

    def test_standard_type_not_linked(self) -> None:
        """Test that standard types are not linked."""
        header = ExtractedHeader()
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[
                InterfaceSection(
                    section_type="VAR_INPUT",
                    variables=[
                        InterfaceVariable(name="value", data_type="Real"),
                    ],
                )
            ],
        )

        result = generate_markdown(header, interface)

        assert "`Real`" in result
        assert "[`Real`]" not in result


class TestUDTGeneration:
    """Tests for UDT documentation generation."""

    def test_generate_udt_fields(self) -> None:
        """Test generating UDT fields table."""
        header = ExtractedHeader(title="typeUnitGeometry")
        interface = ExtractedInterface(
            block_name="typeUnitGeometry",
            block_type="TYPE",
            udt_fields=[
                UDTField(
                    name="st80depth",
                    data_type="Real",
                    description="Style 80 depth (m)",
                ),
                UDTField(
                    name="inLength",
                    data_type="Real",
                    description="Inboard arm length (m)",
                ),
            ],
        )

        result = generate_markdown(header, interface)

        assert "## Fields" in result
        assert "`st80depth`" in result
        assert "Style 80 depth (m)" in result
        assert "`inLength`" in result
        assert "Inboard arm length (m)" in result

    def test_generate_udt_no_interface_sections(self) -> None:
        """Test that UDT doesn't generate interface sections."""
        header = ExtractedHeader()
        interface = ExtractedInterface(
            block_name="Test",
            block_type="TYPE",
            udt_fields=[
                UDTField(name="field1", data_type="Int"),
            ],
        )

        result = generate_markdown(header, interface)

        assert "## Inputs" not in result
        assert "## Outputs" not in result


class TestChangelogGeneration:
    """Tests for changelog generation."""

    def test_generate_changelog(self) -> None:
        """Test generating changelog table."""
        header = ExtractedHeader(
            title="Test",
            changelog=[
                ChangeLogEntry(
                    version="v2.0.0",
                    date="13/06/2025",
                    author="Test Author",
                    changes="Interface modification",
                ),
                ChangeLogEntry(
                    version="v1.0.0",
                    date="25/03/2025",
                    author="Test Author",
                    changes="First released version",
                ),
            ],
        )
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
        )

        result = generate_markdown(header, interface)

        assert "## Changelog" in result
        assert "| v2.0.0 | 13/06/2025 | Test Author | Interface modification |" in result
        assert "| v1.0.0 | 25/03/2025 | Test Author | First released version |" in result

    def test_generate_without_changelog(self) -> None:
        """Test generating without changelog."""
        options = MarkdownOptions(include_changelog=False)
        header = ExtractedHeader(
            title="Test",
            changelog=[
                ChangeLogEntry(
                    version="v1.0.0",
                    date="01/01/2025",
                    author="Author",
                    changes="Initial",
                ),
            ],
        )
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
        )

        result = generate_markdown(header, interface, options)

        assert "## Changelog" not in result


class TestNavEntry:
    """Tests for NavEntry dataclass."""

    def test_simple_nav_entry(self) -> None:
        """Test simple navigation entry."""
        entry = NavEntry(title="MyBlock", path="blocks/MyBlock.md")

        assert entry.to_dict() == {"MyBlock": "blocks/MyBlock.md"}

    def test_nested_nav_entry(self) -> None:
        """Test nested navigation entry."""
        entry = NavEntry(
            title="Function Blocks",
            children=[
                NavEntry(title="MotorStarter", path="fb/MotorStarter.md"),
                NavEntry(title="Alarm", path="fb/Alarm.md"),
            ],
        )

        result = entry.to_dict()

        assert result == {
            "Function Blocks": [
                {"MotorStarter": "fb/MotorStarter.md"},
                {"Alarm": "fb/Alarm.md"},
            ]
        }

    def test_generate_nav_entry(self) -> None:
        """Test generate_nav_entry function."""
        entry = generate_nav_entry("MotorStarter", "FUNCTION_BLOCK", "blocks/MotorStarter.md")

        assert entry.title == "MotorStarter"
        assert entry.path == "blocks/MotorStarter.md"


class TestFileGeneration:
    """Tests for file generation."""

    def test_generate_block_markdown_file(self, tmp_path: Path) -> None:
        """Test generating markdown file."""
        output_path = tmp_path / "Test.md"

        block = Block(name="Test", block_type="FUNCTION_BLOCK")
        header = ExtractedHeader(title="Test", comment="Test block")
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
        )

        generate_block_markdown(block, header, interface, output_path)

        assert output_path.exists()
        content = output_path.read_text()
        assert "# Test" in content
        assert "Test block" in content


class TestRealWorldExample:
    """Tests with real-world example data."""

    def test_full_hpu_block_documentation(self) -> None:
        """Test generating full documentation for MotorStarter block."""
        header = ExtractedHeader(
            title="MotorStarter",
            comment="Manage the motor starter state machine",
            library="ProcessLib",
            author="Example Author",
            copyright="(c) Example Author 2025",
            description="This function block controls the motor starter.\n\n"
            "Features:\n"
            "- Automatic state transitions\n"
            "- Fault monitoring",
            changelog=[
                ChangeLogEntry(
                    version="v2.0.0",
                    date="13/06/2025",
                    author="Example Author",
                    changes="Interface modification",
                ),
                ChangeLogEntry(
                    version="v1.0.0",
                    date="25/03/2025",
                    author="Example Author",
                    changes="First released version",
                ),
            ],
        )

        interface = ExtractedInterface(
            block_name="MotorStarter",
            block_type="FUNCTION_BLOCK",
            sections=[
                InterfaceSection(
                    section_type="VAR_INPUT",
                    variables=[
                        InterfaceVariable(
                            name="enable",
                            data_type="Bool",
                            description="Enable motor control",
                        ),
                        InterfaceVariable(
                            name="config",
                            data_type="_.MotorStarterConfig",
                            description="Configuration parameters",
                            is_library_type=True,
                        ),
                    ],
                ),
                InterfaceSection(
                    section_type="VAR_OUTPUT",
                    variables=[
                        InterfaceVariable(
                            name="status",
                            data_type="USInt",
                            access="ReadOnly",
                            description="Operating status",
                        ),
                        InterfaceVariable(
                            name="pressure",
                            data_type="Real",
                            access="ReadOnly",
                            description="Current pressure (bar)",
                        ),
                    ],
                ),
            ],
        )

        result = generate_markdown(header, interface)

        # Check structure
        assert "# MotorStarter" in result
        assert "**Function Block**" in result
        assert "Manage the motor starter state machine" in result
        assert "**Library:** ProcessLib" in result
        assert "**Author:** Example Author" in result

        # Check description
        assert "## Description" in result
        assert "controls the motor starter" in result

        # Check interface
        assert "## Inputs" in result
        assert "`enable`" in result
        # Without registry, library type is shown without link
        assert "`MotorStarterConfig`" in result

        assert "## Outputs" in result
        assert "`status`" in result
        assert "| ReadOnly |" in result

        # Check changelog
        assert "## Changelog" in result
        assert "v2.0.0" in result
        assert "Interface modification" in result


class TestSourceCodeInclusion:
    """Tests for source code inclusion in generated markdown."""

    def test_source_code_included_by_default(self) -> None:
        """Test that source code is included by default."""
        header = ExtractedHeader(title="Test")
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[],
        )
        source_code = """FUNCTION_BLOCK "Test"
    VAR_INPUT
        enable : Bool;
    END_VAR
END_FUNCTION_BLOCK"""

        result = generate_markdown(header, interface, source_code=source_code)

        assert "## Source Code" in result
        assert "<details" in result
        assert "Click to expand SCL source" in result
        assert "```scl" in result
        assert 'FUNCTION_BLOCK "Test"' in result
        assert "enable : Bool" in result

    def test_source_code_excluded_when_disabled(self) -> None:
        """Test that source code can be excluded via options."""
        header = ExtractedHeader(title="Test")
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[],
        )
        source_code = "FUNCTION_BLOCK Test"
        options = MarkdownOptions(include_source_code=False)

        result = generate_markdown(header, interface, options, source_code=source_code)

        assert "## Source Code" not in result
        assert "<details" not in result

    def test_no_source_code_section_when_none(self) -> None:
        """Test no source code section when source_code is None."""
        header = ExtractedHeader(title="Test")
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[],
        )

        result = generate_markdown(header, interface, source_code=None)

        assert "## Source Code" not in result

    def test_source_code_uses_configured_language(self) -> None:
        """Test that the language for code blocks can be configured."""
        header = ExtractedHeader(title="Test")
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[],
        )
        source_code = "FUNCTION_BLOCK Test"
        options = MarkdownOptions(language_for_code_blocks="pascal")

        result = generate_markdown(header, interface, options, source_code=source_code)

        assert "```pascal" in result
        assert "```scl" not in result

    def test_source_code_trailing_whitespace_stripped(self) -> None:
        """Test that trailing whitespace is stripped from source code."""
        header = ExtractedHeader(title="Test")
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[],
        )
        source_code = "FUNCTION_BLOCK Test\n\n\n"

        result = generate_markdown(header, interface, source_code=source_code)

        # Should not have multiple trailing newlines before closing ```
        assert "Test\n```" in result or "Test\n\n```" in result

    def test_source_code_collapsible_section(self) -> None:
        """Test that source code is in a collapsible details section."""
        header = ExtractedHeader(title="Test")
        interface = ExtractedInterface(
            block_name="Test",
            block_type="FUNCTION_BLOCK",
            sections=[],
        )
        source_code = "FUNCTION_BLOCK Test"

        result = generate_markdown(header, interface, source_code=source_code)

        assert '<details markdown="1">' in result
        assert "<summary>" in result
        assert "</details>" in result
