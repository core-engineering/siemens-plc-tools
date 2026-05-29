"""Tests for interface extraction from SCL blocks."""

from plc_code.extractor.interface import (
    ExtractedInterface,
    InterfaceExtractor,
    InterfaceSection,
    InterfaceVariable,
    extract_interface,
)
from plc_code.parser.models import (
    Block,
    MultiLingualText,
    ResourceFile,
    StructField,
    UserDataType,
    VariableAttributes,
    VariableDeclaration,
    VariableSection,
)


class TestInterfaceVariableModel:
    """Tests for InterfaceVariable dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        var = InterfaceVariable(name="test", data_type="Bool")

        assert var.name == "test"
        assert var.data_type == "Bool"
        assert var.default_value is None
        assert var.description == ""
        assert var.access == ""
        assert var.visibility == ""
        assert var.is_library_type is False


class TestInterfaceSectionModel:
    """Tests for InterfaceSection dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        section = InterfaceSection(section_type="VAR_INPUT")

        assert section.section_type == "VAR_INPUT"
        assert section.variables == []
        assert section.is_constant is False


class TestExtractedInterfaceModel:
    """Tests for ExtractedInterface dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        interface = ExtractedInterface()

        assert interface.block_name == ""
        assert interface.block_type == ""
        assert interface.return_type is None
        assert interface.sections == []
        assert interface.udt_fields == []

    def test_property_shortcuts(self) -> None:
        """Test convenience property access."""
        interface = ExtractedInterface(
            sections=[
                InterfaceSection(
                    section_type="VAR_INPUT",
                    variables=[InterfaceVariable(name="in1", data_type="Bool")],
                ),
                InterfaceSection(
                    section_type="VAR_OUTPUT",
                    variables=[InterfaceVariable(name="out1", data_type="Real")],
                ),
                InterfaceSection(
                    section_type="VAR_IN_OUT",
                    variables=[InterfaceVariable(name="io1", data_type="Int")],
                ),
                InterfaceSection(
                    section_type="VAR",
                    variables=[InterfaceVariable(name="stat1", data_type="Time")],
                ),
                InterfaceSection(
                    section_type="VAR_TEMP",
                    variables=[InterfaceVariable(name="tmp1", data_type="DInt")],
                ),
                InterfaceSection(
                    section_type="VAR_CONSTANT",
                    is_constant=True,
                    variables=[InterfaceVariable(name="CONST1", data_type="Int")],
                ),
            ]
        )

        assert len(interface.inputs) == 1
        assert interface.inputs[0].name == "in1"

        assert len(interface.outputs) == 1
        assert interface.outputs[0].name == "out1"

        assert len(interface.in_outs) == 1
        assert interface.in_outs[0].name == "io1"

        assert len(interface.static_vars) == 1
        assert interface.static_vars[0].name == "stat1"

        assert len(interface.temp_vars) == 1
        assert interface.temp_vars[0].name == "tmp1"

        assert len(interface.constants) == 1
        assert interface.constants[0].name == "CONST1"

    def test_empty_section_returns_empty_list(self) -> None:
        """Test that missing sections return empty lists."""
        interface = ExtractedInterface()

        assert interface.inputs == []
        assert interface.outputs == []
        assert interface.in_outs == []
        assert interface.static_vars == []
        assert interface.temp_vars == []
        assert interface.constants == []


class TestInterfaceExtractor:
    """Tests for InterfaceExtractor class."""

    def test_extract_empty_block(self) -> None:
        """Test extracting from block with no variables."""
        block = Block(name="EmptyBlock", block_type="FUNCTION_BLOCK")

        extractor = InterfaceExtractor(block)
        result = extractor.extract()

        assert result.block_name == "EmptyBlock"
        assert result.block_type == "FUNCTION_BLOCK"
        assert result.sections == []

    def test_extract_function_with_return_type(self) -> None:
        """Test extracting function with return type."""
        block = Block(
            name="Calculate",
            block_type="FUNCTION",
            return_type="Real",
        )

        result = extract_interface(block)

        assert result.block_name == "Calculate"
        assert result.block_type == "FUNCTION"
        assert result.return_type == "Real"

    def test_extract_input_variables(self) -> None:
        """Test extracting input variables."""
        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR_INPUT",
                    variables=[
                        VariableDeclaration(name="trigger", data_type="Bool"),
                        VariableDeclaration(name="setpoint", data_type="Real", default_value="0.0"),
                    ],
                )
            ],
        )

        result = extract_interface(block)

        assert len(result.sections) == 1
        assert result.sections[0].section_type == "VAR_INPUT"
        assert len(result.sections[0].variables) == 2
        assert result.inputs[0].name == "trigger"
        assert result.inputs[1].name == "setpoint"
        assert result.inputs[1].default_value == "0.0"

    def test_extract_with_mlc_resolution(self) -> None:
        """Test MLC comment resolution from resource file."""
        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR_INPUT",
                    variables=[
                        VariableDeclaration(
                            name="depth",
                            data_type="Real",
                            attributes=VariableAttributes(mlc_id="MLC_3Vc"),
                        ),
                    ],
                )
            ],
        )

        resource_file = ResourceFile(
            texts={
                "MLC_3Vc": MultiLingualText(id="MLC_3Vc", text="Style 80 depth (m)"),
            }
        )

        result = extract_interface(block, resource_file)

        assert result.inputs[0].description == "Style 80 depth (m)"

    def test_extract_with_block_resource_file(self) -> None:
        """Test using resource file attached to block."""
        resource_file = ResourceFile(
            texts={
                "MLC_abc": MultiLingualText(id="MLC_abc", text="Description from block"),
            }
        )

        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            resource_file=resource_file,
            variable_sections=[
                VariableSection(
                    section_type="VAR_INPUT",
                    variables=[
                        VariableDeclaration(
                            name="value",
                            data_type="Int",
                            attributes=VariableAttributes(mlc_id="MLC_abc"),
                        ),
                    ],
                )
            ],
        )

        result = extract_interface(block)

        assert result.inputs[0].description == "Description from block"

    def test_extract_access_readonly(self) -> None:
        """Test parsing ReadOnly access modifier."""
        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR_OUTPUT",
                    variables=[
                        VariableDeclaration(
                            name="status",
                            data_type="USInt",
                            attributes=VariableAttributes(access="ReadOnly := External"),
                        ),
                    ],
                )
            ],
        )

        result = extract_interface(block)

        assert result.outputs[0].access == "ReadOnly"

    def test_extract_access_readwrite(self) -> None:
        """Test parsing ReadWrite access modifier."""
        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR_INPUT",
                    variables=[
                        VariableDeclaration(
                            name="config",
                            data_type="Int",
                            attributes=VariableAttributes(access="ReadWrite := External"),
                        ),
                    ],
                )
            ],
        )

        result = extract_interface(block)

        assert result.inputs[0].access == "ReadWrite"

    def test_extract_visibility_hidden(self) -> None:
        """Test parsing Hidden visibility modifier."""
        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR",
                    variables=[
                        VariableDeclaration(
                            name="internal",
                            data_type="DInt",
                            attributes=VariableAttributes(visibility="Hidden := External"),
                        ),
                    ],
                )
            ],
        )

        result = extract_interface(block)

        assert result.static_vars[0].visibility == "Hidden"

    def test_extract_library_type_detection(self) -> None:
        """Test detection of library type references."""
        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR_INPUT",
                    variables=[
                        VariableDeclaration(name="alarm", data_type="_.MotorStarter"),
                        VariableDeclaration(name="value", data_type="Real"),
                    ],
                )
            ],
        )

        result = extract_interface(block)

        assert result.inputs[0].is_library_type is True
        assert result.inputs[1].is_library_type is False

    def test_extract_multiple_sections(self) -> None:
        """Test extracting all section types."""
        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR_INPUT",
                    variables=[VariableDeclaration(name="in1", data_type="Bool")],
                ),
                VariableSection(
                    section_type="VAR_OUTPUT",
                    variables=[VariableDeclaration(name="out1", data_type="Bool")],
                ),
                VariableSection(
                    section_type="VAR_IN_OUT",
                    variables=[VariableDeclaration(name="io1", data_type="Real")],
                ),
                VariableSection(
                    section_type="VAR",
                    variables=[VariableDeclaration(name="stat1", data_type="Int")],
                ),
                VariableSection(
                    section_type="VAR_TEMP",
                    variables=[VariableDeclaration(name="tmp1", data_type="DInt")],
                ),
                VariableSection(
                    section_type="VAR_CONSTANT",
                    is_constant=True,
                    variables=[VariableDeclaration(name="MAX", data_type="Int", default_value="100")],
                ),
            ],
        )

        result = extract_interface(block)

        assert len(result.sections) == 6
        assert len(result.inputs) == 1
        assert len(result.outputs) == 1
        assert len(result.in_outs) == 1
        assert len(result.static_vars) == 1
        assert len(result.temp_vars) == 1
        assert len(result.constants) == 1

    def test_extract_constant_section(self) -> None:
        """Test extracting constant section with is_constant flag."""
        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR_CONSTANT",
                    is_constant=True,
                    variables=[VariableDeclaration(name="PI", data_type="Real", default_value="3.14159")],
                ),
            ],
        )

        result = extract_interface(block)

        assert result.sections[0].is_constant is True
        assert result.constants[0].name == "PI"
        assert result.constants[0].default_value == "3.14159"


class TestUDTExtraction:
    """Tests for extracting User Data Type fields."""

    def test_extract_udt_fields(self) -> None:
        """Test extracting fields from UDT."""
        block = Block(
            name="typeUnitGeometry",
            block_type="TYPE",
            user_data_type=UserDataType(
                name="typeUnitGeometry",
                fields=[
                    StructField(name="st80depth", data_type="Real"),
                    StructField(name="inLength", data_type="Real"),
                ],
            ),
        )

        result = extract_interface(block)

        assert len(result.udt_fields) == 2
        assert result.udt_fields[0].name == "st80depth"
        assert result.udt_fields[0].data_type == "Real"
        assert result.udt_fields[1].name == "inLength"

    def test_extract_udt_with_mlc(self) -> None:
        """Test extracting UDT with MLC descriptions."""
        resource_file = ResourceFile(
            texts={
                "MLC_3Vc": MultiLingualText(id="MLC_3Vc", text="Style 80 depth (m)"),
                "MLC_4hP": MultiLingualText(id="MLC_4hP", text="Inboard arm length (m)"),
            }
        )

        block = Block(
            name="typeUnitGeometry",
            block_type="TYPE",
            user_data_type=UserDataType(
                name="typeUnitGeometry",
                fields=[
                    StructField(name="st80depth", data_type="Real", mlc_id="MLC_3Vc"),
                    StructField(name="inLength", data_type="Real", mlc_id="MLC_4hP"),
                ],
            ),
        )

        result = extract_interface(block, resource_file)

        assert result.udt_fields[0].description == "Style 80 depth (m)"
        assert result.udt_fields[1].description == "Inboard arm length (m)"

    def test_extract_udt_with_existing_comment(self) -> None:
        """Test that existing comment is used when no MLC."""
        block = Block(
            name="Test",
            block_type="TYPE",
            user_data_type=UserDataType(
                name="Test",
                fields=[
                    StructField(name="field1", data_type="Int", comment="Existing comment"),
                ],
            ),
        )

        result = extract_interface(block)

        assert result.udt_fields[0].description == "Existing comment"


class TestEdgeCases:
    """Tests for edge cases."""

    def test_mlc_not_found_keeps_original_comment(self) -> None:
        """Test that original comment is kept when MLC not found."""
        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR_INPUT",
                    variables=[
                        VariableDeclaration(
                            name="var1",
                            data_type="Bool",
                            comment="Original comment",
                            attributes=VariableAttributes(mlc_id="MLC_nonexistent"),
                        ),
                    ],
                )
            ],
        )

        resource_file = ResourceFile(texts={})

        result = extract_interface(block, resource_file)

        assert result.inputs[0].description == "Original comment"

    def test_empty_resource_file(self) -> None:
        """Test with empty resource file."""
        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR_INPUT",
                    variables=[
                        VariableDeclaration(
                            name="var1",
                            data_type="Bool",
                            attributes=VariableAttributes(mlc_id="MLC_abc"),
                        ),
                    ],
                )
            ],
        )

        result = extract_interface(block, ResourceFile())

        assert result.inputs[0].description == ""

    def test_unknown_access_modifier(self) -> None:
        """Test parsing unknown access modifier."""
        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR_INPUT",
                    variables=[
                        VariableDeclaration(
                            name="var1",
                            data_type="Bool",
                            attributes=VariableAttributes(access="CustomAccess"),
                        ),
                    ],
                )
            ],
        )

        result = extract_interface(block)

        assert result.inputs[0].access == "CustomAccess"

    def test_unknown_visibility(self) -> None:
        """Test parsing unknown visibility."""
        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR_INPUT",
                    variables=[
                        VariableDeclaration(
                            name="var1",
                            data_type="Bool",
                            attributes=VariableAttributes(visibility="CustomVisibility"),
                        ),
                    ],
                )
            ],
        )

        result = extract_interface(block)

        assert result.inputs[0].visibility == "CustomVisibility"
