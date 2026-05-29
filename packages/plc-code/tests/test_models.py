"""Tests for parser data models."""

from plc_code.parser.models import (
    Block,
    BlockAttributes,
    ChangeLogEntry,
    HeaderInfo,
    LibraryInfo,
    LibraryInterface,
    MultiLingualText,
    Network,
    NetworkAttributes,
    Region,
    ResourceFile,
    StructField,
    UserDataType,
    VariableAttributes,
    VariableDeclaration,
    VariableSection,
)


class TestVariableDeclaration:
    """Tests for VariableDeclaration model."""

    def test_basic_variable(self) -> None:
        """Test creating a basic variable declaration."""
        var = VariableDeclaration(name="myVar", data_type="Bool")

        assert var.name == "myVar"
        assert var.data_type == "Bool"
        assert var.default_value is None
        assert var.comment == ""

    def test_variable_with_default(self) -> None:
        """Test variable with default value."""
        var = VariableDeclaration(
            name="counter",
            data_type="Int",
            default_value="0",
        )

        assert var.default_value == "0"

    def test_variable_with_attributes(self) -> None:
        """Test variable with S7 attributes."""
        attrs = VariableAttributes(
            access="ReadOnly := External",
            visibility="Hidden := External",
        )
        var = VariableDeclaration(
            name="status",
            data_type="USInt",
            attributes=attrs,
        )

        assert var.attributes.access == "ReadOnly := External"
        assert var.attributes.visibility == "Hidden := External"

    def test_variable_with_complex_type(self) -> None:
        """Test variable with library type reference."""
        var = VariableDeclaration(
            name="alarm",
            data_type="_.MotorStarter",
        )

        assert var.data_type == "_.MotorStarter"


class TestVariableSection:
    """Tests for VariableSection model."""

    def test_empty_section(self) -> None:
        """Test empty variable section."""
        section = VariableSection(section_type="VAR_INPUT")

        assert section.section_type == "VAR_INPUT"
        assert section.variables == []
        assert section.is_constant is False

    def test_section_with_variables(self) -> None:
        """Test section with multiple variables."""
        vars_list = [
            VariableDeclaration(name="input1", data_type="Bool"),
            VariableDeclaration(name="input2", data_type="Real"),
        ]
        section = VariableSection(section_type="VAR_INPUT", variables=vars_list)

        assert len(section.variables) == 2
        assert section.variables[0].name == "input1"

    def test_constant_section(self) -> None:
        """Test VAR CONSTANT section."""
        section = VariableSection(
            section_type="VAR_CONSTANT",
            is_constant=True,
            variables=[
                VariableDeclaration(name="MAX_VALUE", data_type="Int", default_value="100"),
            ],
        )

        assert section.is_constant is True


class TestBlock:
    """Tests for Block model."""

    def test_function_block_creation(self) -> None:
        """Test creating a FUNCTION_BLOCK."""
        block = Block(
            name="MotorStarter",
            block_type="FUNCTION_BLOCK",
        )

        assert block.name == "MotorStarter"
        assert block.block_type == "FUNCTION_BLOCK"
        assert block.return_type is None

    def test_function_creation(self) -> None:
        """Test creating a FUNCTION with return type."""
        block = Block(
            name="Calculate",
            block_type="FUNCTION",
            return_type="Real",
        )

        assert block.return_type == "Real"

    def test_block_with_attributes(self) -> None:
        """Test block with S7 attributes."""
        attrs = BlockAttributes(
            author="Example Author",
            version="2.0",
            family="ProcessLib",
            optimized=True,
        )
        block = Block(
            name="MotorStarter",
            block_type="FUNCTION_BLOCK",
            attributes=attrs,
        )

        assert block.attributes.author == "Example Author"
        assert block.attributes.version == "2.0"

    def test_get_variables_by_section(self) -> None:
        """Test retrieving variables by section type."""
        input_section = VariableSection(
            section_type="VAR_INPUT",
            variables=[
                VariableDeclaration(name="trigger", data_type="Bool"),
            ],
        )
        output_section = VariableSection(
            section_type="VAR_OUTPUT",
            variables=[
                VariableDeclaration(name="result", data_type="Real"),
            ],
        )
        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            variable_sections=[input_section, output_section],
        )

        inputs = block.get_variables_by_section("VAR_INPUT")
        assert len(inputs) == 1
        assert inputs[0].name == "trigger"

        outputs = block.get_variables_by_section("VAR_OUTPUT")
        assert len(outputs) == 1
        assert outputs[0].name == "result"

        # Non-existent section
        temps = block.get_variables_by_section("VAR_TEMP")
        assert temps == []

    def test_block_property_shortcuts(self) -> None:
        """Test convenience properties for variable access."""
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
                    variables=[VariableDeclaration(name="inout1", data_type="Real")],
                ),
            ],
        )

        assert len(block.inputs) == 1
        assert len(block.outputs) == 1
        assert len(block.in_outs) == 1
        assert len(block.static_vars) == 0

    def test_is_ladder_property(self) -> None:
        """Test is_ladder property."""
        scl_block = Block(
            name="SclBlock",
            block_type="FUNCTION_BLOCK",
            attributes=BlockAttributes(editor_mode="SCL"),
        )
        ladder_block = Block(
            name="LadderBlock",
            block_type="FUNCTION_BLOCK",
            attributes=BlockAttributes(preferred_language="LAD"),
        )

        assert scl_block.is_scl is True
        assert scl_block.is_ladder is False
        assert ladder_block.is_ladder is True
        assert ladder_block.is_scl is False


class TestResourceFile:
    """Tests for ResourceFile model."""

    def test_empty_resource_file(self) -> None:
        """Test empty resource file."""
        res = ResourceFile()

        assert res.texts == {}
        assert res.get_text("MLC_123") == ""

    def test_resource_file_with_texts(self) -> None:
        """Test resource file with MLC entries."""
        res = ResourceFile(
            texts={
                "MLC_3Vc": MultiLingualText(id="MLC_3Vc", text="Style 80 depth (m)"),
                "MLC_4hP": MultiLingualText(id="MLC_4hP", text="Inboard arm length (m)"),
            }
        )

        assert res.get_text("MLC_3Vc") == "Style 80 depth (m)"
        assert res.get_text("MLC_4hP") == "Inboard arm length (m)"
        assert res.get_text("nonexistent") == ""


class TestHeaderInfo:
    """Tests for HeaderInfo model."""

    def test_empty_header(self) -> None:
        """Test empty header info."""
        header = HeaderInfo()

        assert header.title == ""
        assert header.changelog == []

    def test_header_with_changelog(self) -> None:
        """Test header with changelog entries."""
        header = HeaderInfo(
            title="MotorStarter",
            comment="Manage the motor starter state machine",
            author="Example Author",
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

        assert header.title == "MotorStarter"
        assert len(header.changelog) == 2
        assert header.changelog[0].version == "v2.0.0"


class TestRegion:
    """Tests for Region model."""

    def test_simple_region(self) -> None:
        """Test simple region without nesting."""
        region = Region(name="Block info header", content="// Title: MyBlock")

        assert region.name == "Block info header"
        assert "Title" in region.content

    def test_nested_regions(self) -> None:
        """Test region with nested regions."""
        inner = Region(name="Inner", content="inner content")
        outer = Region(name="Outer", nested_regions=[inner])

        assert len(outer.nested_regions) == 1
        assert outer.nested_regions[0].name == "Inner"


class TestNetwork:
    """Tests for Network model."""

    def test_scl_network(self) -> None:
        """Test SCL network."""
        network = Network(
            attributes=NetworkAttributes(language="SCL"),
            regions=[Region(name="Logic", content="#output := #input;")],
        )

        assert network.attributes.language == "SCL"
        assert len(network.regions) == 1

    def test_ladder_network(self) -> None:
        """Test LADDER network with elements."""
        network = Network(
            attributes=NetworkAttributes(
                language="LAD",
                network_title_mlc="MLC_3V6",
            ),
            ladder_elements=[
                "Contact( #physicalSignal )",
                "Coil( #logicalSignal )",
            ],
        )

        assert network.attributes.language == "LAD"
        assert len(network.ladder_elements) == 2
        assert "Contact" in network.ladder_elements[0]


class TestUserDataType:
    """Tests for UserDataType model."""

    def test_simple_udt(self) -> None:
        """Test simple UDT creation."""
        udt = UserDataType(
            name="typeUnitGeometry",
            fields=[
                StructField(name="st80depth", data_type="Real", mlc_id="MLC_3Vc"),
                StructField(name="inLength", data_type="Real", mlc_id="MLC_4hP"),
            ],
        )

        assert udt.name == "typeUnitGeometry"
        assert len(udt.fields) == 2
        assert udt.fields[0].mlc_id == "MLC_3Vc"


class TestLibraryFiles:
    """Tests for library metadata models."""

    def test_library_info(self) -> None:
        """Test LibraryInfo model."""
        info = LibraryInfo(
            guid="b7b1f285-e2de-4f9b-aba4-c8793c715526",
            version_number="2.0.3",
            author="Example Author",
            is_default=True,
        )

        assert info.version_number == "2.0.3"
        assert info.is_default is True

    def test_library_interface(self) -> None:
        """Test LibraryInterface model."""
        interface = LibraryInterface(
            guid="2ef60b42-07ae-40d6-9995-6e4b9b889fff",
            dependencies=[
                {"TypeName": "MotorStarter", "VersionNumber": "1.0.0"},
                {"TypeName": "ScalingAnalogicInput", "VersionNumber": "1.0.0"},
            ],
        )

        assert len(interface.dependencies) == 2
        assert interface.dependencies[0]["TypeName"] == "MotorStarter"
