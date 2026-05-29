"""Tests for SCL Pygments lexer."""

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.token import (
    Comment,
    Keyword,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
)

from plc_code.highlighting import SCLLexer


class TestSCLLexerRegistration:
    """Tests for lexer registration and discovery."""

    def test_lexer_can_be_instantiated(self) -> None:
        """Test that the lexer can be instantiated directly."""
        lexer = SCLLexer()
        assert lexer.name == "SCL"

    def test_lexer_registered_with_pygments(self) -> None:
        """Test that the lexer is registered as a Pygments plugin."""
        lexer = get_lexer_by_name("scl")
        assert lexer.name == "SCL"

    def test_lexer_aliases(self) -> None:
        """Test that all aliases work."""
        for alias in ["scl", "s7scl", "structured-control-language"]:
            lexer = get_lexer_by_name(alias)
            assert lexer.name == "SCL"

    def test_lexer_filenames(self) -> None:
        """Test lexer filename patterns."""
        lexer = SCLLexer()
        assert "*.scl" in lexer.filenames
        assert "*.s7dcl" in lexer.filenames


class TestSCLLexerTokens:
    """Tests for token recognition."""

    def get_tokens(self, code: str) -> list[tuple]:
        """Get tokens from code."""
        lexer = SCLLexer()
        return list(lexer.get_tokens(code))

    def test_block_keywords(self) -> None:
        """Test block declaration keywords are recognized."""
        tokens = self.get_tokens("FUNCTION_BLOCK END_FUNCTION_BLOCK")
        token_types = [t[0] for t in tokens]
        assert Keyword.Declaration in token_types

    def test_function_keyword(self) -> None:
        """Test FUNCTION keyword."""
        tokens = self.get_tokens("FUNCTION END_FUNCTION")
        token_types = [t[0] for t in tokens]
        assert Keyword.Declaration in token_types

    def test_type_keyword(self) -> None:
        """Test TYPE keyword."""
        tokens = self.get_tokens("TYPE END_TYPE STRUCT END_STRUCT")
        token_types = [t[0] for t in tokens]
        assert Keyword.Declaration in token_types

    def test_var_sections(self) -> None:
        """Test variable section keywords."""
        code = "VAR VAR_INPUT VAR_OUTPUT VAR_IN_OUT VAR_TEMP END_VAR"
        tokens = self.get_tokens(code)
        token_types = [t[0] for t in tokens]
        assert Keyword.Declaration in token_types

    def test_control_flow_keywords(self) -> None:
        """Test control flow keywords."""
        code = "IF THEN ELSIF ELSE END_IF CASE OF END_CASE FOR TO DO END_FOR"
        tokens = self.get_tokens(code)
        token_types = [t[0] for t in tokens]
        assert Keyword in token_types

    def test_region_keywords(self) -> None:
        """Test REGION keywords."""
        tokens = self.get_tokens("REGION END_REGION NETWORK END_NETWORK")
        token_types = [t[0] for t in tokens]
        assert Keyword.Namespace in token_types

    def test_logical_operators(self) -> None:
        """Test logical operator keywords."""
        tokens = self.get_tokens("AND OR XOR NOT")
        token_types = [t[0] for t in tokens]
        assert Keyword.Operator in token_types

    def test_boolean_literals(self) -> None:
        """Test TRUE/FALSE keywords."""
        tokens = self.get_tokens("TRUE FALSE")
        token_types = [t[0] for t in tokens]
        assert Keyword.Operator in token_types

    def test_builtin_types(self) -> None:
        """Test builtin type recognition."""
        code = "Bool Int Real String Time DInt UInt USInt"
        tokens = self.get_tokens(code)
        token_types = [t[0] for t in tokens]
        assert Keyword.Type in token_types

    def test_timer_types(self) -> None:
        """Test timer type recognition."""
        code = "TON_TIME TOF_TIME TP_TIME"
        tokens = self.get_tokens(code)
        token_types = [t[0] for t in tokens]
        assert Keyword.Type in token_types

    def test_single_line_comment(self) -> None:
        """Test single-line comment recognition."""
        tokens = self.get_tokens("// This is a comment")
        token_types = [t[0] for t in tokens]
        assert Comment.Single in token_types

    def test_multiline_comment(self) -> None:
        """Test multi-line comment recognition."""
        tokens = self.get_tokens("(* This is\na comment *)")
        token_types = [t[0] for t in tokens]
        assert Comment.Multiline in token_types

    def test_string_literals(self) -> None:
        """Test string literal recognition.

        Note: In SCL, single quotes are for strings, double quotes are for
        block/DB references (e.g., "ProcessData".member).
        """
        tokens = self.get_tokens("'single string'")
        token_types = [t[0] for t in tokens]
        assert String.Single in token_types

    def test_integer_numbers(self) -> None:
        """Test integer number recognition."""
        tokens = self.get_tokens("123 456")
        token_types = [t[0] for t in tokens]
        assert Number.Integer in token_types

    def test_float_numbers(self) -> None:
        """Test float number recognition."""
        tokens = self.get_tokens("3.14 2.0 1e10")
        token_types = [t[0] for t in tokens]
        assert Number.Float in token_types

    def test_hex_numbers(self) -> None:
        """Test hexadecimal number recognition."""
        tokens = self.get_tokens("16#FF 16#ABCD")
        token_types = [t[0] for t in tokens]
        assert Number.Hex in token_types

    def test_binary_numbers(self) -> None:
        """Test binary number recognition."""
        tokens = self.get_tokens("2#1010 2#11110000")
        token_types = [t[0] for t in tokens]
        assert Number.Bin in token_types

    def test_time_literals(self) -> None:
        """Test time literal recognition."""
        tokens = self.get_tokens("T#5s T#1h30m TIME#10ms")
        token_types = [t[0] for t in tokens]
        assert Number in token_types

    def test_instance_variable(self) -> None:
        """Test instance variable (#var) recognition."""
        tokens = self.get_tokens("#myVariable")
        token_types = [t[0] for t in tokens]
        assert Name.Variable.Instance in token_types

    def test_global_variable(self) -> None:
        """Test global variable ("DB".member) recognition."""
        tokens = self.get_tokens('"ProcessData"')
        token_types = [t[0] for t in tokens]
        assert Name.Variable.Global in token_types

    def test_library_type(self) -> None:
        """Test library type (_.) recognition."""
        tokens = self.get_tokens("_.MotorStarter")
        token_types = [t[0] for t in tokens]
        assert Name.Class in token_types

    def test_assignment_operator(self) -> None:
        """Test assignment operator recognition."""
        tokens = self.get_tokens(":=")
        token_types = [t[0] for t in tokens]
        assert Operator in token_types

    def test_output_operator(self) -> None:
        """Test output operator recognition."""
        tokens = self.get_tokens("=>")
        token_types = [t[0] for t in tokens]
        assert Operator in token_types

    def test_comparison_operators(self) -> None:
        """Test comparison operators."""
        tokens = self.get_tokens("<> <= >= < > =")
        token_types = [t[0] for t in tokens]
        assert Operator in token_types

    def test_pragma_block(self) -> None:
        """Test S7 pragma block recognition."""
        code = '{ S7_Author := "Test" }'
        tokens = self.get_tokens(code)
        token_types = [t[0] for t in tokens]
        assert Punctuation in token_types
        assert Name.Attribute in token_types


class TestSCLLexerIntegration:
    """Integration tests for full SCL code blocks."""

    def test_function_block_declaration(self) -> None:
        """Test full function block declaration."""
        code = """
FUNCTION_BLOCK "TestBlock"
    VAR_INPUT
        enable : Bool;
    END_VAR
BEGIN
    // Logic here
END_FUNCTION_BLOCK
"""
        lexer = SCLLexer()
        tokens = list(lexer.get_tokens(code))
        # Should tokenize without errors
        assert len(tokens) > 0

    def test_type_declaration(self) -> None:
        """Test UDT type declaration."""
        code = """
TYPE
    myType : STRUCT
        field1 : Bool;
        field2 : Int := 0;
    END_STRUCT;
END_TYPE
"""
        lexer = SCLLexer()
        tokens = list(lexer.get_tokens(code))
        assert len(tokens) > 0

    def test_region_with_code(self) -> None:
        """Test REGION block with code."""
        code = """
REGION Main logic
    IF #enable AND NOT #disable THEN
        #output := TRUE;
    END_IF;
END_REGION
"""
        lexer = SCLLexer()
        tokens = list(lexer.get_tokens(code))
        assert len(tokens) > 0

    def test_case_statement(self) -> None:
        """Test CASE statement."""
        code = """
CASE #state OF
    0:
        #output := FALSE;
    1, 2:
        #output := TRUE;
END_CASE;
"""
        lexer = SCLLexer()
        tokens = list(lexer.get_tokens(code))
        assert len(tokens) > 0

    def test_html_output(self) -> None:
        """Test that HTML output is generated correctly."""
        code = 'FUNCTION_BLOCK "Test"'
        lexer = SCLLexer()
        formatter = HtmlFormatter()
        result = highlight(code, lexer, formatter)
        assert "<span" in result
        assert "Test" in result
