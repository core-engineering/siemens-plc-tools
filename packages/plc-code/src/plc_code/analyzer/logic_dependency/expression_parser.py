"""Expression parser for SCL boolean and comparison expressions.

This module provides a tokenizer and recursive descent parser for
parsing SCL expressions into LogicExpression trees. Handles:
- Boolean operators: AND, OR, NOT, XOR
- Comparison operators: =, <>, <, >, <=, >=
- Variable references: #var, "DB".field
- Parenthesized expressions
- Function calls (as terminal nodes)
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum, auto

from .models import (
    DependencyNode,
    LogicExpression,
    NodeType,
    OperatorType,
    SourceLocation,
)


class TokenType(Enum):
    """Token types for the lexer."""

    # Literals and identifiers
    LOCAL_VAR = auto()  # #variableName
    GLOBAL_REF = auto()  # "DBName".field.path
    IDENTIFIER = auto()  # plain identifier
    NUMBER = auto()  # numeric literal
    STRING = auto()  # string literal
    BOOL_LITERAL = auto()  # TRUE/FALSE

    # Boolean operators
    AND = auto()
    OR = auto()
    NOT = auto()
    XOR = auto()

    # Comparison operators
    EQ = auto()  # =
    NE = auto()  # <>
    LT = auto()  # <
    GT = auto()  # >
    LE = auto()  # <=
    GE = auto()  # >=

    # Delimiters
    LPAREN = auto()  # (
    RPAREN = auto()  # )
    LBRACKET = auto()  # [
    RBRACKET = auto()  # ]
    COMMA = auto()  # ,
    DOT = auto()  # .
    ASSIGN = auto()  # :=
    OUTPUT_ASSIGN = auto()  # =>

    # Special
    EOF = auto()
    UNKNOWN = auto()


@dataclass
class Token:
    """A lexical token.

    Attributes
    ----------
    type : TokenType
        The type of token.
    value : str
        The token's string value.
    position : int
        Position in source string.
    """

    type: TokenType
    value: str
    position: int = 0


class Lexer:
    """Tokenizer for SCL expressions.

    Converts a string expression into a sequence of tokens.
    """

    # Token patterns (order matters - longer matches first)
    PATTERNS = [
        # Assignment operators (before comparison)
        (r":=", TokenType.ASSIGN),
        (r"=>", TokenType.OUTPUT_ASSIGN),
        # Comparison operators (multi-char first)
        (r"<>", TokenType.NE),
        (r"<=", TokenType.LE),
        (r">=", TokenType.GE),
        (r"<", TokenType.LT),
        (r">", TokenType.GT),
        (r"=", TokenType.EQ),
        # Boolean operators (case-insensitive)
        (r"\bAND\b", TokenType.AND),
        (r"\bOR\b", TokenType.OR),
        (r"\bNOT\b", TokenType.NOT),
        (r"\bXOR\b", TokenType.XOR),
        (r"\bTRUE\b", TokenType.BOOL_LITERAL),
        (r"\bFALSE\b", TokenType.BOOL_LITERAL),
        # Local variable reference: #varName or # varName (parser may add space after #)
        (r"#\s*[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*", TokenType.LOCAL_VAR),
        # Global DB reference: "DBName".field.path or "DBName".field["index"]
        (r'"[^"]+"\.[a-zA-Z_][a-zA-Z0-9_.\[\]"]*', TokenType.GLOBAL_REF),
        # Plain identifier (function names, type names, etc.)
        (r"[a-zA-Z_][a-zA-Z0-9_]*", TokenType.IDENTIFIER),
        # Numeric literals (including negative, floats, time literals)
        (r"-?\d+\.?\d*(?:[eE][+-]?\d+)?", TokenType.NUMBER),
        (r"T#[0-9a-zA-Z_]+", TokenType.NUMBER),  # Time literal
        # String literal
        (r"'[^']*'", TokenType.STRING),
        # Delimiters
        (r"\(", TokenType.LPAREN),
        (r"\)", TokenType.RPAREN),
        (r"\[", TokenType.LBRACKET),
        (r"\]", TokenType.RBRACKET),
        (r",", TokenType.COMMA),
        (r"\.", TokenType.DOT),
    ]

    def __init__(self, text: str) -> None:
        """Initialize lexer with input text.

        Parameters
        ----------
        text : str
            The expression to tokenize.
        """
        self.text = text
        self.pos = 0
        self.compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), token_type) for pattern, token_type in self.PATTERNS
        ]

    def tokenize(self) -> list[Token]:
        """Tokenize the entire input.

        Returns
        -------
        list[Token]
            List of tokens, ending with EOF.
        """
        tokens = []
        for token in self._generate_tokens():
            tokens.append(token)
        return tokens

    def _generate_tokens(self) -> Iterator[Token]:
        """Generate tokens from input text."""
        while self.pos < len(self.text):
            # Skip whitespace and newlines
            if self.text[self.pos].isspace():
                self.pos += 1
                continue

            # Skip comments
            if self.text[self.pos : self.pos + 2] == "//":
                # Skip to end of line
                while self.pos < len(self.text) and self.text[self.pos] != "\n":
                    self.pos += 1
                continue

            # Try each pattern
            matched = False
            for pattern, token_type in self.compiled_patterns:
                match = pattern.match(self.text, self.pos)
                if match:
                    value = match.group(0)
                    yield Token(token_type, value, self.pos)
                    self.pos = match.end()
                    matched = True
                    break

            if not matched:
                # Unknown character
                yield Token(TokenType.UNKNOWN, self.text[self.pos], self.pos)
                self.pos += 1

        yield Token(TokenType.EOF, "", self.pos)


class ParseError(Exception):
    """Exception raised for parsing errors."""

    pass


class ExpressionParser:
    """Recursive descent parser for SCL expressions.

    Parses tokenized expressions into LogicExpression trees.

    Operator precedence (low to high):
    1. OR
    2. XOR
    3. AND
    4. NOT (unary)
    5. Comparisons (=, <>, <, >, <=, >=)
    6. Primary (variables, literals, parenthesized expressions)
    """

    def __init__(
        self,
        variable_lookup: dict[str, NodeType] | None = None,
        source_file: str = "",
        base_line: int = 0,
    ) -> None:
        """Initialize parser.

        Parameters
        ----------
        variable_lookup : dict[str, NodeType] | None
            Mapping from variable name to its type.
        source_file : str
            Source file path for location tracking.
        base_line : int
            Base line number offset.
        """
        self.variable_lookup = variable_lookup or {}
        self.source_file = source_file
        self.base_line = base_line
        self.tokens: list[Token] = []
        self.pos = 0

    def parse(self, expression: str) -> LogicExpression:
        """Parse an expression string into a LogicExpression tree.

        Parameters
        ----------
        expression : str
            The expression to parse.

        Returns
        -------
        LogicExpression
            The parsed expression tree.

        Raises
        ------
        ParseError
            If the expression cannot be parsed.
        """
        lexer = Lexer(expression)
        self.tokens = lexer.tokenize()
        self.pos = 0

        result = self._parse_or_expression()

        # Check for unconsumed tokens (except EOF)
        if self.current_token.type != TokenType.EOF:
            # Allow trailing content (might be part of larger statement)
            pass

        return result

    @property
    def current_token(self) -> Token:
        """Get the current token."""
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return Token(TokenType.EOF, "", len(self.tokens))

    def _advance(self) -> Token:
        """Consume and return the current token."""
        token = self.current_token
        self.pos += 1
        return token

    def _expect(self, token_type: TokenType) -> Token:
        """Expect a specific token type.

        Raises
        ------
        ParseError
            If the current token doesn't match.
        """
        if self.current_token.type != token_type:
            raise ParseError(
                f"Expected {token_type.name}, got {self.current_token.type.name} "
                f"'{self.current_token.value}' at position {self.current_token.position}"
            )
        return self._advance()

    def _parse_or_expression(self) -> LogicExpression:
        """Parse OR expression (lowest precedence)."""
        left = self._parse_xor_expression()

        while self.current_token.type == TokenType.OR:
            self._advance()
            right = self._parse_xor_expression()
            left = LogicExpression(
                operator=OperatorType.OR,
                operands=[left, right],
            )

        return left

    def _parse_xor_expression(self) -> LogicExpression:
        """Parse XOR expression."""
        left = self._parse_and_expression()

        while self.current_token.type == TokenType.XOR:
            self._advance()
            right = self._parse_and_expression()
            left = LogicExpression(
                operator=OperatorType.XOR,
                operands=[left, right],
            )

        return left

    def _parse_and_expression(self) -> LogicExpression:
        """Parse AND expression."""
        left = self._parse_not_expression()

        while self.current_token.type == TokenType.AND:
            self._advance()
            right = self._parse_not_expression()
            left = LogicExpression(
                operator=OperatorType.AND,
                operands=[left, right],
            )

        return left

    def _parse_not_expression(self) -> LogicExpression:
        """Parse NOT expression (unary)."""
        if self.current_token.type == TokenType.NOT:
            self._advance()
            # NOT can be followed by parentheses or directly by operand
            if self.current_token.type == TokenType.LPAREN:
                self._advance()
                operand = self._parse_or_expression()
                self._expect(TokenType.RPAREN)
            else:
                operand = self._parse_not_expression()  # Allow NOT NOT x
            return LogicExpression(
                operator=OperatorType.NOT,
                operands=[operand],
            )

        return self._parse_comparison_expression()

    def _parse_comparison_expression(self) -> LogicExpression:
        """Parse comparison expression."""
        left = self._parse_primary()

        # Check for comparison operator
        comparison_ops = {
            TokenType.EQ: OperatorType.COMPARE_EQ,
            TokenType.NE: OperatorType.COMPARE_NE,
            TokenType.LT: OperatorType.COMPARE_LT,
            TokenType.GT: OperatorType.COMPARE_GT,
            TokenType.LE: OperatorType.COMPARE_LE,
            TokenType.GE: OperatorType.COMPARE_GE,
        }

        if self.current_token.type in comparison_ops:
            op = comparison_ops[self.current_token.type]
            self._advance()
            right = self._parse_primary()
            return LogicExpression(
                operator=op,
                operands=[left, right],
            )

        return left

    def _parse_primary(self) -> LogicExpression:
        """Parse primary expression (variables, literals, parenthesized)."""
        token = self.current_token

        # Parenthesized expression
        if token.type == TokenType.LPAREN:
            self._advance()
            expr = self._parse_or_expression()
            self._expect(TokenType.RPAREN)
            return expr

        # Local variable reference
        if token.type == TokenType.LOCAL_VAR:
            self._advance()
            return self._create_variable_expression(token.value)

        # Global DB reference
        if token.type == TokenType.GLOBAL_REF:
            self._advance()
            return self._create_global_db_expression(token.value)

        # Boolean literal
        if token.type == TokenType.BOOL_LITERAL:
            self._advance()
            return self._create_constant_expression(token.value, "Bool")

        # Numeric literal
        if token.type == TokenType.NUMBER:
            self._advance()
            return self._create_constant_expression(token.value, "Number")

        # String literal
        if token.type == TokenType.STRING:
            self._advance()
            return self._create_constant_expression(token.value, "String")

        # Identifier (could be function call, constant, or type conversion)
        if token.type == TokenType.IDENTIFIER:
            self._advance()
            # Check for function call
            if self.current_token.type == TokenType.LPAREN:
                return self._parse_function_call(token.value)
            # Plain identifier (likely a constant reference)
            return self._create_identifier_expression(token.value)

        # EOF or unknown
        if token.type == TokenType.EOF:
            raise ParseError("Unexpected end of expression")

        raise ParseError(f"Unexpected token {token.type.name} '{token.value}' at position {token.position}")

    def _parse_function_call(self, func_name: str) -> LogicExpression:
        """Parse a function call and return as a single node.

        Function calls are treated as opaque operations that depend on
        all their input arguments.
        """
        self._expect(TokenType.LPAREN)

        # Collect all arguments as dependencies
        args: list[LogicExpression] = []
        while self.current_token.type != TokenType.RPAREN:
            if self.current_token.type == TokenType.EOF:
                raise ParseError("Unclosed function call")

            # Skip parameter names in named arguments (param := value)
            if (
                self.current_token.type == TokenType.IDENTIFIER
                and self.pos + 1 < len(self.tokens)
                and self.tokens[self.pos + 1].type == TokenType.ASSIGN
            ):
                self._advance()  # Skip identifier
                self._advance()  # Skip :=

            # Skip output parameters (param => value)
            if (
                self.current_token.type == TokenType.IDENTIFIER
                and self.pos + 1 < len(self.tokens)
                and self.tokens[self.pos + 1].type == TokenType.OUTPUT_ASSIGN
            ):
                # Skip entire output assignment
                self._advance()  # Skip identifier
                self._advance()  # Skip =>
                self._skip_until_comma_or_rparen()
                if self.current_token.type == TokenType.COMMA:
                    self._advance()
                continue

            # Parse argument expression
            try:
                arg = self._parse_or_expression()
                args.append(arg)
            except ParseError:
                # Skip unparseable content
                self._skip_until_comma_or_rparen()

            if self.current_token.type == TokenType.COMMA:
                self._advance()

        self._expect(TokenType.RPAREN)

        # Create function call node
        func_node = DependencyNode(
            name=func_name,
            node_type=NodeType.FUNCTION_CALL,
            data_type="",
            raw_reference=func_name,
        )

        if args:
            # Return AND of function node and all args (represents dependencies)
            return LogicExpression(
                operator=OperatorType.AND,
                operands=[
                    LogicExpression(operator=OperatorType.IDENTITY, operands=[func_node]),
                    *args,
                ],
            )
        else:
            return LogicExpression(
                operator=OperatorType.IDENTITY,
                operands=[func_node],
            )

    def _skip_until_comma_or_rparen(self) -> None:
        """Skip tokens until comma or right paren."""
        depth = 0
        while self.current_token.type != TokenType.EOF:
            if self.current_token.type == TokenType.LPAREN:
                depth += 1
            elif self.current_token.type == TokenType.RPAREN:
                if depth == 0:
                    return
                depth -= 1
            elif self.current_token.type == TokenType.COMMA and depth == 0:
                return
            self._advance()

    def _create_variable_expression(self, reference: str) -> LogicExpression:
        """Create expression for a variable reference."""
        # Strip # prefix and any spaces (parser may store as "# varName")
        name = reference.lstrip("#").strip()

        # Look up type
        node_type = self.variable_lookup.get(name, NodeType.UNKNOWN)

        node = DependencyNode(
            name=name,
            node_type=node_type,
            data_type="",
            source_location=SourceLocation(self.source_file, self.base_line),
            raw_reference=reference,
        )

        return LogicExpression(operator=OperatorType.IDENTITY, operands=[node])

    def _create_global_db_expression(self, reference: str) -> LogicExpression:
        """Create expression for a global DB reference."""
        node = DependencyNode(
            name=reference,
            node_type=NodeType.GLOBAL_DB,
            data_type="",
            source_location=SourceLocation(self.source_file, self.base_line),
            raw_reference=reference,
        )

        return LogicExpression(operator=OperatorType.IDENTITY, operands=[node])

    def _create_constant_expression(self, value: str, data_type: str) -> LogicExpression:
        """Create expression for a constant/literal."""
        node = DependencyNode(
            name=value,
            node_type=NodeType.CONSTANT,
            data_type=data_type,
            raw_reference=value,
        )

        return LogicExpression(operator=OperatorType.IDENTITY, operands=[node])

    def _create_identifier_expression(self, name: str) -> LogicExpression:
        """Create expression for an identifier (likely constant or type)."""
        # Check if it's a known variable
        node_type = self.variable_lookup.get(name, NodeType.CONSTANT)

        node = DependencyNode(
            name=name,
            node_type=node_type,
            data_type="",
            raw_reference=name,
        )

        return LogicExpression(operator=OperatorType.IDENTITY, operands=[node])


def parse_expression(
    expression: str,
    variable_lookup: dict[str, NodeType] | None = None,
    source_file: str = "",
    base_line: int = 0,
) -> LogicExpression:
    """Convenience function to parse an expression.

    Parameters
    ----------
    expression : str
        The expression to parse.
    variable_lookup : dict[str, NodeType] | None
        Mapping from variable name to its type.
    source_file : str
        Source file path for location tracking.
    base_line : int
        Base line number offset.

    Returns
    -------
    LogicExpression
        The parsed expression tree.
    """
    parser = ExpressionParser(variable_lookup, source_file, base_line)
    return parser.parse(expression)
