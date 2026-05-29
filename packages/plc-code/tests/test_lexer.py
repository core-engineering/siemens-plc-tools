"""Tests for the SCL lexer."""

from pathlib import Path

import pytest

from plc_code.parser.lexer import TokenType, tokenize


class TestBasicTokenization:
    """Tests for basic token recognition."""

    def test_empty_source(self) -> None:
        """Test tokenizing empty source."""
        tokens = tokenize("")
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.EOF

    def test_function_block_keyword(self) -> None:
        """Test FUNCTION_BLOCK keyword recognition."""
        tokens = tokenize("FUNCTION_BLOCK")
        assert tokens[0].type == TokenType.FUNCTION_BLOCK
        assert tokens[0].value == "FUNCTION_BLOCK"

    def test_function_keyword(self) -> None:
        """Test FUNCTION keyword recognition."""
        tokens = tokenize("FUNCTION")
        assert tokens[0].type == TokenType.FUNCTION
        assert tokens[0].value == "FUNCTION"

    def test_type_keyword(self) -> None:
        """Test TYPE keyword recognition."""
        tokens = tokenize("TYPE")
        assert tokens[0].type == TokenType.TYPE

    def test_end_keywords(self) -> None:
        """Test END_* keywords."""
        tokens = tokenize("END_FUNCTION_BLOCK END_FUNCTION END_TYPE")
        assert tokens[0].type == TokenType.END_FUNCTION_BLOCK
        assert tokens[1].type == TokenType.END_FUNCTION
        assert tokens[2].type == TokenType.END_TYPE

    def test_var_section_keywords(self) -> None:
        """Test VAR section keywords."""
        tokens = tokenize("VAR_INPUT VAR_OUTPUT VAR_IN_OUT VAR VAR_TEMP END_VAR")
        assert tokens[0].type == TokenType.VAR_INPUT
        assert tokens[1].type == TokenType.VAR_OUTPUT
        assert tokens[2].type == TokenType.VAR_IN_OUT
        assert tokens[3].type == TokenType.VAR
        assert tokens[4].type == TokenType.VAR_TEMP
        assert tokens[5].type == TokenType.END_VAR

    def test_region_keywords(self) -> None:
        """Test REGION keywords."""
        tokens = tokenize("REGION END_REGION")
        assert tokens[0].type == TokenType.REGION
        assert tokens[1].type == TokenType.END_REGION

    def test_network_keywords(self) -> None:
        """Test NETWORK keywords."""
        tokens = tokenize("NETWORK END_NETWORK")
        assert tokens[0].type == TokenType.NETWORK
        assert tokens[1].type == TokenType.END_NETWORK

    def test_rung_keywords(self) -> None:
        """Test RUNG keywords (LADDER)."""
        tokens = tokenize("RUNG END_RUNG")
        assert tokens[0].type == TokenType.RUNG
        assert tokens[1].type == TokenType.END_RUNG

    def test_struct_keywords(self) -> None:
        """Test STRUCT keywords."""
        tokens = tokenize("STRUCT END_STRUCT")
        assert tokens[0].type == TokenType.STRUCT
        assert tokens[1].type == TokenType.END_STRUCT

    def test_case_insensitive_keywords(self) -> None:
        """Test keywords are case-insensitive."""
        tokens = tokenize("function_block Function_Block FUNCTION_BLOCK")
        assert all(t.type == TokenType.FUNCTION_BLOCK for t in tokens[:3])


class TestLiterals:
    """Tests for literal value tokenization."""

    def test_quoted_string(self) -> None:
        """Test double-quoted string."""
        tokens = tokenize('"MotorStarter"')
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == '"MotorStarter"'

    def test_string_with_spaces(self) -> None:
        """Test string containing spaces."""
        tokens = tokenize('"Block info header"')
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == '"Block info header"'

    def test_single_quoted_string(self) -> None:
        """Test single-quoted string (parameter values)."""
        tokens = tokenize("'transmitter'")
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == "'transmitter'"

    def test_integer_number(self) -> None:
        """Test integer literal."""
        tokens = tokenize("42")
        assert tokens[0].type == TokenType.NUMBER
        assert tokens[0].value == "42"

    def test_negative_number(self) -> None:
        """Test negative number."""
        tokens = tokenize("-100")
        assert tokens[0].type == TokenType.NUMBER
        assert tokens[0].value == "-100"

    def test_float_number(self) -> None:
        """Test floating point literal."""
        tokens = tokenize("3.14159")
        assert tokens[0].type == TokenType.NUMBER
        assert tokens[0].value == "3.14159"

    def test_scientific_notation(self) -> None:
        """Test scientific notation."""
        tokens = tokenize("1.5e-6")
        assert tokens[0].type == TokenType.NUMBER
        assert tokens[0].value == "1.5e-6"

    def test_identifier(self) -> None:
        """Test identifier tokenization."""
        tokens = tokenize("myVariable")
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == "myVariable"

    def test_identifier_with_underscore(self) -> None:
        """Test identifier with underscores."""
        tokens = tokenize("oil_temperature_sensor")
        assert tokens[0].type == TokenType.IDENTIFIER

    def test_identifier_starting_with_underscore(self) -> None:
        """Test identifier starting with underscore."""
        tokens = tokenize("_privateVar")
        assert tokens[0].type == TokenType.IDENTIFIER


class TestOperators:
    """Tests for operator tokenization."""

    def test_colon(self) -> None:
        """Test colon operator."""
        tokens = tokenize(":")
        assert tokens[0].type == TokenType.COLON

    def test_assign(self) -> None:
        """Test assignment operator."""
        tokens = tokenize(":=")
        assert tokens[0].type == TokenType.ASSIGN

    def test_semicolon(self) -> None:
        """Test semicolon."""
        tokens = tokenize(";")
        assert tokens[0].type == TokenType.SEMICOLON

    def test_comma(self) -> None:
        """Test comma."""
        tokens = tokenize(",")
        assert tokens[0].type == TokenType.COMMA

    def test_dot(self) -> None:
        """Test dot operator."""
        tokens = tokenize(".")
        assert tokens[0].type == TokenType.DOT

    def test_hash(self) -> None:
        """Test hash for local variables."""
        tokens = tokenize("#myVar")
        assert tokens[0].type == TokenType.HASH
        assert tokens[1].type == TokenType.IDENTIFIER

    def test_parentheses(self) -> None:
        """Test parentheses."""
        tokens = tokenize("()")
        assert tokens[0].type == TokenType.LPAREN
        assert tokens[1].type == TokenType.RPAREN

    def test_brackets(self) -> None:
        """Test square brackets."""
        tokens = tokenize("[]")
        assert tokens[0].type == TokenType.LBRACKET
        assert tokens[1].type == TokenType.RBRACKET


class TestComments:
    """Tests for comment tokenization."""

    def test_single_line_comment(self) -> None:
        """Test single-line comment."""
        tokens = tokenize("// This is a comment")
        assert tokens[0].type == TokenType.COMMENT
        assert "This is a comment" in tokens[0].value

    def test_comment_before_code(self) -> None:
        """Test comment followed by code."""
        tokens = tokenize("// comment\nVAR")
        assert tokens[0].type == TokenType.COMMENT
        assert tokens[1].type == TokenType.VAR


class TestPragmas:
    """Tests for pragma tokenization."""

    def test_simple_pragma(self) -> None:
        """Test simple pragma block."""
        tokens = tokenize('{ S7_Author := "Example Author" }')
        assert tokens[0].type == TokenType.PRAGMA_START
        assert tokens[1].type == TokenType.PRAGMA_CONTENT
        assert 'S7_Author := "Example Author"' in tokens[1].value
        assert tokens[2].type == TokenType.PRAGMA_END

    def test_multiline_pragma(self) -> None:
        """Test multiline pragma block."""
        source = """{
    S7_Author := "Example Author";
    S7_Version := "2.0"
}"""
        tokens = tokenize(source)
        assert tokens[0].type == TokenType.PRAGMA_START
        # Should have pragma content tokens
        pragma_contents = [t for t in tokens if t.type == TokenType.PRAGMA_CONTENT]
        assert len(pragma_contents) >= 1
        assert tokens[-2].type == TokenType.PRAGMA_END

    def test_pragma_with_mlc(self) -> None:
        """Test pragma with MLC reference."""
        tokens = tokenize('{ S7_MLC := "MLC_3Vc" }')
        assert any(t.type == TokenType.PRAGMA_CONTENT and "S7_MLC" in t.value for t in tokens)


class TestComplexStructures:
    """Tests for complex SCL structures."""

    def test_function_block_declaration(self) -> None:
        """Test function block declaration."""
        source = 'FUNCTION_BLOCK "MotorStarter"'
        tokens = tokenize(source)
        assert tokens[0].type == TokenType.FUNCTION_BLOCK
        assert tokens[1].type == TokenType.STRING
        assert tokens[1].value == '"MotorStarter"'

    def test_function_declaration_with_return(self) -> None:
        """Test function declaration with return type."""
        source = 'FUNCTION "Calculate" : Real'
        tokens = tokenize(source)
        assert tokens[0].type == TokenType.FUNCTION
        assert tokens[1].type == TokenType.STRING
        assert tokens[2].type == TokenType.COLON
        assert tokens[3].type == TokenType.IDENTIFIER
        assert tokens[3].value == "Real"

    def test_variable_declaration(self) -> None:
        """Test variable declaration."""
        source = "myVar : Bool := False;"
        tokens = tokenize(source)
        assert tokens[0].type == TokenType.IDENTIFIER  # myVar
        assert tokens[1].type == TokenType.COLON
        assert tokens[2].type == TokenType.IDENTIFIER  # Bool
        assert tokens[3].type == TokenType.ASSIGN
        assert tokens[4].type == TokenType.IDENTIFIER  # False
        assert tokens[5].type == TokenType.SEMICOLON

    def test_type_reference(self) -> None:
        """Test library type reference."""
        source = "_.typeUnitData"
        tokens = tokenize(source)
        assert tokens[0].type == TokenType.IDENTIFIER  # _
        assert tokens[1].type == TokenType.DOT
        assert tokens[2].type == TokenType.IDENTIFIER  # typeUnitData

    def test_region_block(self) -> None:
        """Test REGION block."""
        source = 'REGION "Block info header"\n// content\nEND_REGION'
        tokens = tokenize(source)
        assert tokens[0].type == TokenType.REGION
        assert tokens[1].type == TokenType.STRING
        assert tokens[2].type == TokenType.COMMENT
        assert tokens[3].type == TokenType.END_REGION

    def test_ladder_elements(self) -> None:
        """Test LADDER language elements."""
        source = "Contact( #input )\nCoil( #output )"
        tokens = tokenize(source)
        assert tokens[0].type == TokenType.IDENTIFIER  # Contact
        assert tokens[1].type == TokenType.LPAREN
        assert tokens[2].type == TokenType.HASH
        assert tokens[3].type == TokenType.IDENTIFIER  # input
        assert tokens[4].type == TokenType.RPAREN


class TestLineColumnTracking:
    """Tests for line and column tracking."""

    def test_single_line_positions(self) -> None:
        """Test token positions on single line."""
        tokens = tokenize("VAR x : Bool;")
        assert tokens[0].line == 1
        assert tokens[0].column == 1
        # x should start at column 5
        assert tokens[1].column == 5

    def test_multiline_positions(self) -> None:
        """Test token positions across lines."""
        source = "VAR\n    x : Bool;"
        tokens = tokenize(source)
        assert tokens[0].line == 1  # VAR
        # After newline, x is on line 2
        x_token = [t for t in tokens if t.value == "x"][0]
        assert x_token.line == 2
        assert x_token.column == 5


class TestBOMHandling:
    """Tests for BOM (Byte Order Mark) handling."""

    def test_utf8_bom(self) -> None:
        """Test UTF-8 BOM is stripped."""
        source = "\ufeffFUNCTION_BLOCK"
        tokens = tokenize(source)
        assert tokens[0].type == TokenType.FUNCTION_BLOCK


class TestRealFileFixture:
    """Tests using real SCL file fixtures."""

    def test_acknowledged_alarm_fixture(self) -> None:
        """Test tokenizing the MotorStarter fixture."""
        fixture_path = Path(__file__).parent / "fixtures" / "MotorStarter.s7dcl"
        if not fixture_path.exists():
            pytest.skip("Fixture file not found")

        source = fixture_path.read_text(encoding="utf-8-sig")
        tokens = tokenize(source)

        # Verify key tokens are present
        token_types = [t.type for t in tokens]

        assert TokenType.PRAGMA_START in token_types
        assert TokenType.FUNCTION_BLOCK in token_types
        assert TokenType.VAR_INPUT in token_types
        assert TokenType.VAR_OUTPUT in token_types
        assert TokenType.END_VAR in token_types
        assert TokenType.NETWORK in token_types
        assert TokenType.REGION in token_types
        assert TokenType.END_REGION in token_types
        assert TokenType.END_FUNCTION_BLOCK in token_types
        assert TokenType.EOF in token_types

        # Verify block name is captured
        fb_idx = token_types.index(TokenType.FUNCTION_BLOCK)
        assert tokens[fb_idx + 1].type == TokenType.STRING
        assert "MotorStarter" in tokens[fb_idx + 1].value
