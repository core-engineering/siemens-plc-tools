"""Tests for the SCL parser."""

from pathlib import Path

import pytest

from plc_code.parser.lexer import tokenize_with_newlines
from plc_code.parser.parser import (
    SCLParser,
    parse_libinfo_file,
    parse_libint_file,
    parse_resource_file,
    parse_scl_file,
)


class TestBlockDeclarations:
    """Tests for parsing block declarations."""

    def test_parse_function_block(self) -> None:
        """Test parsing FUNCTION_BLOCK declaration."""
        source = """
{
    S7_Author := "Test Author";
    S7_Version := "1.0"
}
FUNCTION_BLOCK "TestBlock"
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert block.name == "TestBlock"
        assert block.block_type == "FUNCTION_BLOCK"
        assert block.attributes.author == "Test Author"
        assert block.attributes.version == "1.0"

    def test_parse_function_with_return(self) -> None:
        """Test parsing FUNCTION with return type."""
        source = """
FUNCTION "Calculate" : Real
END_FUNCTION
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert block.name == "Calculate"
        assert block.block_type == "FUNCTION"
        assert block.return_type == "Real"

    def test_parse_function_void_return(self) -> None:
        """Test parsing FUNCTION with Void return."""
        source = """
FUNCTION "Process" : Void
END_FUNCTION
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert block.return_type == "Void"

    def test_parse_ladder_block(self) -> None:
        """Test parsing LADDER (LAD) block."""
        source = """
{
    S7_PreferredLanguage := "LAD"
}
FUNCTION_BLOCK "LadderBlock"
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert block.is_ladder is True
        assert block.is_scl is False


class TestVariableSections:
    """Tests for parsing variable sections."""

    def test_parse_var_input(self) -> None:
        """Test parsing VAR_INPUT section."""
        source = """
FUNCTION_BLOCK "Test"
    VAR_INPUT
        trigger : Bool;
        value : Real;
    END_VAR
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert len(block.inputs) == 2
        assert block.inputs[0].name == "trigger"
        assert block.inputs[0].data_type == "Bool"
        assert block.inputs[1].name == "value"
        assert block.inputs[1].data_type == "Real"

    def test_parse_var_output(self) -> None:
        """Test parsing VAR_OUTPUT section."""
        source = """
FUNCTION_BLOCK "Test"
    VAR_OUTPUT
        result : Int;
    END_VAR
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert len(block.outputs) == 1
        assert block.outputs[0].name == "result"

    def test_parse_var_in_out(self) -> None:
        """Test parsing VAR_IN_OUT section."""
        source = """
FUNCTION_BLOCK "Test"
    VAR_IN_OUT
        buffer : Array[0..99] of Real;
    END_VAR
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert len(block.in_outs) == 1
        assert "Array" in block.in_outs[0].data_type

    def test_parse_var_static(self) -> None:
        """Test parsing VAR (static) section."""
        source = """
FUNCTION_BLOCK "Test"
    VAR
        counter : Int := 0;
    END_VAR
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert len(block.static_vars) == 1
        assert block.static_vars[0].name == "counter"
        assert block.static_vars[0].default_value == "0"

    def test_parse_var_temp(self) -> None:
        """Test parsing VAR_TEMP section."""
        source = """
FUNCTION_BLOCK "Test"
    VAR_TEMP
        tempValue : Real;
    END_VAR
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert len(block.temp_vars) == 1

    def test_parse_var_constant(self) -> None:
        """Test parsing VAR CONSTANT section."""
        source = """
FUNCTION_BLOCK "Test"
    VAR CONSTANT
        MAX_VALUE : Int := 100;
        MIN_VALUE : Int := 0;
    END_VAR
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert len(block.constants) == 2
        assert block.constants[0].name == "MAX_VALUE"
        assert block.constants[0].default_value == "100"

    def test_parse_variable_with_attributes(self) -> None:
        """Test parsing variable with S7 attributes."""
        source = """
FUNCTION_BLOCK "Test"
    VAR_INPUT
        {
            S7_Access := "ReadOnly := External";
            S7_Visibility := "Hidden := External"
        }
        signal : Bool;
    END_VAR
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert block.inputs[0].attributes.access == "ReadOnly := External"
        assert block.inputs[0].attributes.visibility == "Hidden := External"

    def test_parse_library_type_reference(self) -> None:
        """Test parsing library type reference (_.TypeName)."""
        source = """
FUNCTION_BLOCK "Test"
    VAR
        alarm : _.MotorStarter;
    END_VAR
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert block.static_vars[0].data_type == "_.MotorStarter"


class TestRegions:
    """Tests for parsing REGION blocks."""

    def test_parse_simple_region(self) -> None:
        """Test parsing simple REGION."""
        source = """
FUNCTION_BLOCK "Test"
    { S7_Language := "SCL" }
    NETWORK
        REGION "Block info header"
            // Title: Test
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert len(block.networks) == 1
        assert len(block.networks[0].regions) == 1
        assert block.networks[0].regions[0].name == "Block info header"
        assert "Title" in block.networks[0].regions[0].content

    def test_parse_region_with_mlc(self) -> None:
        """Test parsing REGION with MLC pragma."""
        source = """
FUNCTION_BLOCK "Test"
    { S7_Language := "SCL" }
    NETWORK
        REGION "Description"
            { S7_MLC := "MLC_123" }
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert block.networks[0].regions[0].mlc_id == "MLC_123"

    def test_parse_nested_regions(self) -> None:
        """Test parsing nested REGION blocks."""
        source = """
FUNCTION_BLOCK "Test"
    { S7_Language := "SCL" }
    NETWORK
        REGION "Outer"
            REGION "Inner"
                // content
            END_REGION
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        outer = block.networks[0].regions[0]
        assert outer.name == "Outer"
        assert len(outer.nested_regions) == 1
        assert outer.nested_regions[0].name == "Inner"

    def test_a_quoted_region_name_may_be_followed_by_more_words(self) -> None:
        """The rest of the header is part of the name, not part of the code.

        TIA Portal accepts `REGION "RCU" Default Management`. Stopping the name
        at the closing quote left `Default Management` in the region's content
        and tokens, where the transpiler read it as code.
        """
        source = """
FUNCTION_BLOCK "Test"
    { S7_Language := "SCL" }
    NETWORK
        REGION "RCU" Default Management
            #a := TRUE;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
        block = SCLParser(tokenize_with_newlines(source)).parse()

        region = block.networks[0].regions[0]
        assert region.name == "RCU Default Management"
        assert [token.value for token in region.tokens] == ["#", "a", ":=", "TRUE", ";"]
        assert "Default" not in region.content

    def test_a_quoted_region_name_on_its_own_is_unchanged(self) -> None:
        source = """
FUNCTION_BLOCK "Test"
    { S7_Language := "SCL" }
    NETWORK
        REGION "Logic"
            #a := TRUE;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
        block = SCLParser(tokenize_with_newlines(source)).parse()

        region = block.networks[0].regions[0]
        assert region.name == "Logic"
        assert [token.value for token in region.tokens] == ["#", "a", ":=", "TRUE", ";"]

    def test_a_trailing_comment_is_not_part_of_the_name(self) -> None:
        source = """
FUNCTION_BLOCK "Test"
    { S7_Language := "SCL" }
    NETWORK
        REGION "RCU" Management // why it exists
            #a := TRUE;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
        block = SCLParser(tokenize_with_newlines(source)).parse()

        region = block.networks[0].regions[0]
        assert region.name == "RCU Management"

    def test_a_region_nested_under_a_quoted_multi_word_name_is_read(self) -> None:
        source = """
FUNCTION_BLOCK "Test"
    { S7_Language := "SCL" }
    NETWORK
        REGION "RCU" Default Management
            REGION "Inner" Part Two
                #a := TRUE;
            END_REGION
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
        block = SCLParser(tokenize_with_newlines(source)).parse()

        outer = block.networks[0].regions[0]
        assert outer.name == "RCU Default Management"
        assert [nested.name for nested in outer.nested_regions] == ["Inner Part Two"]
        assert [token.value for token in outer.tokens] == ["#", "a", ":=", "TRUE", ";"]


class TestNetworks:
    """Tests for parsing NETWORK blocks."""

    def test_parse_scl_network(self) -> None:
        """Test parsing SCL network."""
        source = """
FUNCTION_BLOCK "Test"
    { S7_Language := "SCL" }
    NETWORK
        REGION "Logic"
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert len(block.networks) == 1
        assert block.networks[0].attributes.language == "SCL"

    def test_parse_network_with_title(self) -> None:
        """Test parsing network with MLC title reference."""
        source = """
FUNCTION_BLOCK "Test"
    {
        S7_Language := "LAD";
        S7_NetworkTitle := "MLC_xyz"
    }
    NETWORK
        RUNG wire
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert block.networks[0].attributes.network_title_mlc == "MLC_xyz"

    def test_parse_ladder_rungs(self) -> None:
        """Test parsing LADDER RUNG elements."""
        source = """
FUNCTION_BLOCK "Test"
    { S7_Language := "LAD" }
    NETWORK
        RUNG wire
            Contact( #input )
            Coil( #output )
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        elements = block.networks[0].ladder_elements
        assert any("Contact" in e for e in elements)
        assert any("Coil" in e for e in elements)


class TestUserDataTypes:
    """Tests for parsing TYPE (UDT) definitions."""

    def test_parse_simple_udt(self) -> None:
        """Test parsing simple UDT."""
        source = """
TYPE
    typeSimple : STRUCT
        field1 : Bool;
        field2 : Real;
    END_STRUCT;
END_TYPE
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert block.block_type == "TYPE"
        assert block.name == "typeSimple"
        assert block.user_data_type is not None
        assert len(block.user_data_type.fields) == 2
        assert block.user_data_type.fields[0].name == "field1"
        assert block.user_data_type.fields[0].data_type == "Bool"

    def test_parse_udt_with_mlc(self) -> None:
        """Test parsing UDT with MLC comments on fields."""
        source = """
TYPE
    typeWithMlc : STRUCT
        { S7_MLC := "MLC_abc" }
        value : Real;
    END_STRUCT;
END_TYPE
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert block.user_data_type is not None
        assert block.user_data_type.fields[0].mlc_id == "MLC_abc"


class TestResourceFiles:
    """Tests for parsing .s7res files."""

    def test_parse_resource_file(self, tmp_path: Path) -> None:
        """Test parsing .s7res resource file."""
        content = """MultiLingualTexts:
  - id: MLC_3Vc
    en-US: Style 80 depth (m)
  - id: MLC_4hP
    en-US: Inboard arm length (m)
"""
        res_file = tmp_path / "test.s7res"
        res_file.write_text(content, encoding="utf-8")

        resource = parse_resource_file(res_file)

        assert len(resource.texts) == 2
        assert resource.get_text("MLC_3Vc") == "Style 80 depth (m)"
        assert resource.get_text("MLC_4hP") == "Inboard arm length (m)"

    def test_parse_resource_file_multiline_text(self, tmp_path: Path) -> None:
        """Test parsing resource file with multiline text."""
        content = """MultiLingualTexts:
  - id: MLC_desc
    en-US: |
      This is a multiline
      description text.
"""
        res_file = tmp_path / "test.s7res"
        res_file.write_text(content, encoding="utf-8")

        resource = parse_resource_file(res_file)

        assert "multiline" in resource.get_text("MLC_desc")

    def test_parse_missing_resource_file(self, tmp_path: Path) -> None:
        """Test parsing non-existent resource file returns empty."""
        resource = parse_resource_file(tmp_path / "nonexistent.s7res")
        assert len(resource.texts) == 0

    def test_numeric_text_is_a_string(self, tmp_path: Path) -> None:
        """A comment that is only digits must not arrive as an int.

        `.s7res` is YAML, so an unquoted `40021` parses as an int and the
        declared `MultiLingualText.text: str` is not enforced at runtime. One
        real project uses Modbus holding-register numbers as rung comments —
        24 of them in a single file — and every string operation downstream
        then raised `AttributeError: 'int' object has no attribute 'lower'`,
        taking down `plc code lint` for the whole project.
        """
        content = """MultiLingualTexts:
  - id: MLC_reg
    en-US: 40021
"""
        res_file = tmp_path / "test.s7res"
        res_file.write_text(content, encoding="utf-8")

        resource = parse_resource_file(res_file)

        assert resource.texts["MLC_reg"].text == "40021"
        assert isinstance(resource.get_text("MLC_reg"), str)

    def test_every_yaml_scalar_shape_becomes_a_string(self, tmp_path: Path) -> None:
        """Floats, booleans and dates are comments too, and YAML coerces them all.

        `ON`/`OFF` and `1.5` are ordinary PLC comment text, and a bare date is
        common in a revision note. Guarding only the integer case would leave
        the same crash one comment away.
        """
        content = """MultiLingualTexts:
  - id: MLC_int
    en-US: 42
  - id: MLC_float
    en-US: 1.5
  - id: MLC_bool
    en-US: ON
  - id: MLC_date
    en-US: 2026-08-17
"""
        res_file = tmp_path / "test.s7res"
        res_file.write_text(content, encoding="utf-8")

        resource = parse_resource_file(res_file)

        for mlc_id in ("MLC_int", "MLC_float", "MLC_bool", "MLC_date"):
            value = resource.texts[mlc_id].text
            assert isinstance(value, str), f"{mlc_id} came back as {type(value).__name__}"
            assert value != ""

    def test_missing_and_null_text_become_empty_strings(self, tmp_path: Path) -> None:
        """An absent or explicitly null `en-US` must give "", never None."""
        content = """MultiLingualTexts:
  - id: MLC_null
    en-US:
  - id: MLC_absent
    de-DE: Beschreibung
"""
        res_file = tmp_path / "test.s7res"
        res_file.write_text(content, encoding="utf-8")

        resource = parse_resource_file(res_file)

        assert resource.texts["MLC_null"].text == ""
        assert resource.texts["MLC_absent"].text == ""


class TestLibraryFiles:
    """Tests for parsing library metadata files."""

    def test_parse_libinfo(self, tmp_path: Path) -> None:
        """Test parsing .libinfo file."""
        content = """LibraryType:
  Guid: b7b1f285-e2de-4f9b-aba4-c8793c715526
LibraryVersion:
  VersionNumber: 2.0.3
  Author: Example Author
  IsDefault: true
"""
        info_file = tmp_path / "test.libinfo"
        info_file.write_text(content, encoding="utf-8")

        info = parse_libinfo_file(info_file)

        assert info.guid == "b7b1f285-e2de-4f9b-aba4-c8793c715526"
        assert info.version_number == "2.0.3"
        assert info.author == "Example Author"
        assert info.is_default is True

    def test_parse_libint(self, tmp_path: Path) -> None:
        """Test parsing .libint file."""
        content = """DocumentHash:
  - FileName: Test.s7dcl
    Hash: abc123==
LibraryVersion:
  Guid: 2ef60b42-07ae-40d6-9995-6e4b9b889fff
  DependsOn:
    - TypeName: MotorStarter
      VersionNumber: 1.0.0
"""
        int_file = tmp_path / "test.libint"
        int_file.write_text(content, encoding="utf-8")

        interface = parse_libint_file(int_file)

        assert interface.guid == "2ef60b42-07ae-40d6-9995-6e4b9b889fff"
        assert len(interface.dependencies) == 1
        assert interface.dependencies[0]["TypeName"] == "MotorStarter"


class TestRealFileFixtures:
    """Tests using real file fixtures."""

    def test_parse_acknowledged_alarm(self) -> None:
        """Test parsing MotorStarter fixture."""
        fixture_path = Path(__file__).parent / "fixtures" / "MotorStarter.s7dcl"
        if not fixture_path.exists():
            pytest.skip("Fixture not found")

        block = parse_scl_file(fixture_path)

        assert block.name == "MotorStarter"
        assert block.block_type == "FUNCTION_BLOCK"
        assert block.attributes.author == "Example Author"
        assert block.attributes.family == "ProcessLib"

        # Check inputs
        assert len(block.inputs) == 3
        input_names = [v.name for v in block.inputs]
        assert "startCommand" in input_names
        assert "stopCommand" in input_names
        assert "faultDetected" in input_names

        # Check outputs
        assert len(block.outputs) == 1
        assert block.outputs[0].name == "motorState"

        # Check static vars
        assert len(block.static_vars) == 1
        assert block.static_vars[0].name == "activeState"

        # Check constants
        assert len(block.constants) == 3
        const_names = [v.name for v in block.constants]
        assert "STOPPED" in const_names
        assert "RUNNING" in const_names
        assert "FAULT" in const_names

        # Check networks and regions
        assert len(block.networks) >= 1
        regions = block.networks[0].regions
        region_names = [r.name for r in regions]
        assert "Block info header" in region_names


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_block(self) -> None:
        """Test parsing empty function block."""
        source = """
FUNCTION_BLOCK "Empty"
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert block.name == "Empty"
        assert len(block.inputs) == 0
        assert len(block.outputs) == 0

    def test_block_without_pragma(self) -> None:
        """Test parsing block without header pragma."""
        source = """
FUNCTION_BLOCK "NoPragma"
    VAR_INPUT
        x : Bool;
    END_VAR
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert block.name == "NoPragma"
        assert block.attributes.author == ""

    def test_multiple_var_sections(self) -> None:
        """Test parsing block with multiple VAR sections."""
        source = """
FUNCTION_BLOCK "Multi"
    VAR_INPUT
        in1 : Bool;
    END_VAR
    VAR_OUTPUT
        out1 : Bool;
    END_VAR
    VAR
        static1 : Int;
    END_VAR
    VAR_TEMP
        temp1 : Real;
    END_VAR
END_FUNCTION_BLOCK
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert len(block.inputs) == 1
        assert len(block.outputs) == 1
        assert len(block.static_vars) == 1
        assert len(block.temp_vars) == 1


class TestRegionNameAfterEndRegion:
    """Tests for TIA Portal style END_REGION <name> syntax.

    TIA Portal emits END_REGION followed by the region name as plain identifiers,
    e.g. ``END_REGION Block info header``.  The parser must not leak those
    identifier tokens into the surrounding network.content.
    """

    def test_end_region_with_trailing_name_does_not_leak(self) -> None:
        """Identifiers after END_REGION must NOT appear in network.content."""
        source = """\
FUNCTION "Test" : Void
    { S7_Language := "SCL" }
    NETWORK
        // some preamble comment
        REGION Block info header
            // title line
        END_REGION Block info header

        #x := 1;
    END_NETWORK
END_FUNCTION
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        assert len(block.networks) == 1
        net = block.networks[0]
        # The region should be parsed correctly
        assert len(net.regions) == 1
        assert net.regions[0].name == "Block info header"
        # The network content must NOT contain any identifier from the region name
        content = net.content or ""
        assert "Block" not in content
        assert "info" not in content
        assert "header" not in content
        # The actual statement after the region should be in region or network content
        # (not tested here - just verify no leakage)

    def test_end_region_unquoted_name_single_word(self) -> None:
        """Single-word unquoted END_REGION name must be consumed."""
        source = """\
FUNCTION "Test" : Void
    { S7_Language := "SCL" }
    NETWORK
        REGION Logic
            #y := 2;
        END_REGION Logic
        #z := 3;
    END_NETWORK
END_FUNCTION
"""
        tokens = tokenize_with_newlines(source)
        parser = SCLParser(tokens)
        block = parser.parse()

        net = block.networks[0]
        assert len(net.regions) == 1
        assert net.regions[0].name == "Logic"
        content = net.content or ""
        assert "Logic" not in content
