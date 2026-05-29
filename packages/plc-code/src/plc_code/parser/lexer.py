"""SCL lexer for tokenizing TIA Portal V21 exports.

This module provides tokenization of SCL source files, identifying key
structural elements like block declarations, variable sections, regions,
and networks.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum, auto


class TokenType(Enum):
    """Types of tokens in SCL source."""

    # Block structure
    PRAGMA_START = auto()  # {
    PRAGMA_END = auto()  # }
    FUNCTION_BLOCK = auto()  # FUNCTION_BLOCK
    FUNCTION = auto()  # FUNCTION
    TYPE = auto()  # TYPE
    ORGANIZATION_BLOCK = auto()  # ORGANIZATION_BLOCK
    DATA_BLOCK = auto()  # DATA_BLOCK
    END_FUNCTION_BLOCK = auto()  # END_FUNCTION_BLOCK
    END_FUNCTION = auto()  # END_FUNCTION
    END_TYPE = auto()  # END_TYPE
    END_ORGANIZATION_BLOCK = auto()  # END_ORGANIZATION_BLOCK
    END_DATA_BLOCK = auto()  # END_DATA_BLOCK

    # Variable sections
    VAR_INPUT = auto()
    VAR_OUTPUT = auto()
    VAR_IN_OUT = auto()
    VAR = auto()
    VAR_TEMP = auto()
    VAR_CONSTANT = auto()  # VAR CONSTANT
    END_VAR = auto()

    # Struct
    STRUCT = auto()
    END_STRUCT = auto()

    # Code structure
    NETWORK = auto()
    END_NETWORK = auto()
    REGION = auto()
    END_REGION = auto()
    RUNG = auto()
    END_RUNG = auto()

    # Literals and identifiers
    STRING = auto()  # "quoted string"
    IDENTIFIER = auto()  # variable names, type names
    NUMBER = auto()  # numeric literals
    COMMENT = auto()  # // comment
    BLOCK_COMMENT = auto()  # (* ... *)
    PRAGMA_CONTENT = auto()  # S7_xxx := "value"

    # Operators and punctuation
    COLON = auto()  # :
    SEMICOLON = auto()  # ;
    ASSIGN = auto()  # :=
    COMMA = auto()  # ,
    DOT = auto()  # .
    HASH = auto()  # #
    LPAREN = auto()  # (
    RPAREN = auto()  # )
    LBRACKET = auto()  # [
    RBRACKET = auto()  # ]

    # Special
    NEWLINE = auto()
    WHITESPACE = auto()
    EOF = auto()
    UNKNOWN = auto()


@dataclass
class Token:
    """A lexical token from SCL source.

    Attributes
    ----------
    type : TokenType
        The type of token.
    value : str
        The literal value from source.
    line : int
        Line number (1-indexed).
    column : int
        Column number (1-indexed).
    """

    type: TokenType
    value: str
    line: int
    column: int


# Keywords mapping (case-insensitive matching, stored uppercase)
KEYWORDS: dict[str, TokenType] = {
    "FUNCTION_BLOCK": TokenType.FUNCTION_BLOCK,
    "END_FUNCTION_BLOCK": TokenType.END_FUNCTION_BLOCK,
    "FUNCTION": TokenType.FUNCTION,
    "END_FUNCTION": TokenType.END_FUNCTION,
    "TYPE": TokenType.TYPE,
    "END_TYPE": TokenType.END_TYPE,
    "ORGANIZATION_BLOCK": TokenType.ORGANIZATION_BLOCK,
    "END_ORGANIZATION_BLOCK": TokenType.END_ORGANIZATION_BLOCK,
    "DATA_BLOCK": TokenType.DATA_BLOCK,
    "END_DATA_BLOCK": TokenType.END_DATA_BLOCK,
    "VAR_INPUT": TokenType.VAR_INPUT,
    "VAR_OUTPUT": TokenType.VAR_OUTPUT,
    "VAR_IN_OUT": TokenType.VAR_IN_OUT,
    "VAR_TEMP": TokenType.VAR_TEMP,
    "VAR": TokenType.VAR,
    "END_VAR": TokenType.END_VAR,
    "STRUCT": TokenType.STRUCT,
    "END_STRUCT": TokenType.END_STRUCT,
    "NETWORK": TokenType.NETWORK,
    "END_NETWORK": TokenType.END_NETWORK,
    "REGION": TokenType.REGION,
    "END_REGION": TokenType.END_REGION,
    "RUNG": TokenType.RUNG,
    "END_RUNG": TokenType.END_RUNG,
    "CONSTANT": TokenType.VAR_CONSTANT,  # Special: VAR CONSTANT
}


class SCLLexer:
    """Lexer for SCL source files.

    Tokenizes TIA Portal V21 SCL exports into a stream of tokens for parsing.

    Parameters
    ----------
    source : str
        The SCL source code to tokenize.

    Examples
    --------
    >>> lexer = SCLLexer('FUNCTION_BLOCK "Test"')
    >>> tokens = list(lexer.tokenize())
    >>> tokens[0].type == TokenType.FUNCTION_BLOCK
    True
    """

    def __init__(self, source: str) -> None:
        """Initialize the lexer with source code.

        Parameters
        ----------
        source : str
            The SCL source code to tokenize.
        """
        # Remove BOM if present
        if source.startswith("\ufeff"):
            source = source[1:]
        self.source = source
        self.pos = 0
        self.line = 1
        self.column = 1
        self._in_pragma = False

    def tokenize(self) -> Iterator[Token]:
        """Tokenize the source into a stream of tokens.

        Yields
        ------
        Token
            The next token from the source.
        """
        while self.pos < len(self.source):
            token = self._next_token()
            if token is not None:
                yield token

        yield Token(TokenType.EOF, "", self.line, self.column)

    def _next_token(self) -> Token | None:
        """Get the next token from the source.

        Returns
        -------
        Token | None
            The next token, or None for skipped whitespace.
        """
        if self.pos >= len(self.source):
            return None

        char = self.source[self.pos]

        # Skip whitespace (but track newlines)
        if char in " \t\r":
            self._advance()
            return None

        if char == "\n":
            token = Token(TokenType.NEWLINE, "\n", self.line, self.column)
            self.pos += 1
            self.line += 1
            self.column = 1
            return token

        # Comments
        if char == "/" and self._peek(1) == "/":
            return self._scan_comment()

        # Pragmas
        if char == "{":
            self._in_pragma = True
            token = Token(TokenType.PRAGMA_START, "{", self.line, self.column)
            self._advance()
            return token

        if char == "}":
            self._in_pragma = False
            token = Token(TokenType.PRAGMA_END, "}", self.line, self.column)
            self._advance()
            return token

        # Inside pragma, scan pragma content
        if self._in_pragma:
            return self._scan_pragma_content()

        # Strings
        if char == '"':
            return self._scan_string()

        # Single-quoted strings (for parameter values)
        if char == "'":
            return self._scan_single_string()

        # Numbers
        if char.isdigit() or (char == "-" and self._peek(1).isdigit()):
            return self._scan_number()

        # Identifiers and keywords
        if char.isalpha() or char == "_":
            return self._scan_identifier()

        # Hash for local variables
        if char == "#":
            token = Token(TokenType.HASH, "#", self.line, self.column)
            self._advance()
            return token

        # Operators and punctuation
        if char == ":" and self._peek(1) == "=":
            token = Token(TokenType.ASSIGN, ":=", self.line, self.column)
            self._advance(2)
            return token

        if char == ":":
            token = Token(TokenType.COLON, ":", self.line, self.column)
            self._advance()
            return token

        if char == ";":
            token = Token(TokenType.SEMICOLON, ";", self.line, self.column)
            self._advance()
            return token

        if char == ",":
            token = Token(TokenType.COMMA, ",", self.line, self.column)
            self._advance()
            return token

        if char == ".":
            token = Token(TokenType.DOT, ".", self.line, self.column)
            self._advance()
            return token

        if char == "(" and self._peek(1) == "*":
            return self._scan_block_comment()

        if char == "(":
            token = Token(TokenType.LPAREN, "(", self.line, self.column)
            self._advance()
            return token

        if char == ")":
            token = Token(TokenType.RPAREN, ")", self.line, self.column)
            self._advance()
            return token

        if char == "[":
            token = Token(TokenType.LBRACKET, "[", self.line, self.column)
            self._advance()
            return token

        if char == "]":
            token = Token(TokenType.RBRACKET, "]", self.line, self.column)
            self._advance()
            return token

        # Unknown character
        token = Token(TokenType.UNKNOWN, char, self.line, self.column)
        self._advance()
        return token

    def _advance(self, count: int = 1) -> None:
        """Advance the position in the source.

        Parameters
        ----------
        count : int
            Number of characters to advance.
        """
        for _ in range(count):
            if self.pos < len(self.source):
                if self.source[self.pos] == "\n":
                    self.line += 1
                    self.column = 1
                else:
                    self.column += 1
                self.pos += 1

    def _peek(self, offset: int = 0) -> str:
        """Peek at a character without advancing.

        Parameters
        ----------
        offset : int
            Offset from current position.

        Returns
        -------
        str
            The character at position, or empty string if past end.
        """
        pos = self.pos + offset
        if pos < len(self.source):
            return self.source[pos]
        return ""

    def _scan_comment(self) -> Token:
        """Scan a // comment to end of line.

        Returns
        -------
        Token
            The comment token.
        """
        start_line = self.line
        start_col = self.column
        start_pos = self.pos

        # Skip //
        self._advance(2)

        # Read to end of line
        while self.pos < len(self.source) and self.source[self.pos] != "\n":
            self._advance()

        value = self.source[start_pos : self.pos]
        return Token(TokenType.COMMENT, value, start_line, start_col)

    def _scan_block_comment(self) -> Token:
        """Scan a (* ... *) block comment preserving all content.

        Returns
        -------
        Token
            The block comment token with full content including whitespace.
        """
        start_line = self.line
        start_col = self.column
        start_pos = self.pos

        # Skip (*
        self._advance(2)

        # Read until *)
        while self.pos < len(self.source):
            if self.source[self.pos] == "*" and self._peek(1) == ")":
                self._advance(2)  # Skip *)
                break
            # Track newlines for line counting
            if self.source[self.pos] == "\n":
                self.line += 1
                self.column = 1
                self.pos += 1
            else:
                self._advance()

        value = self.source[start_pos : self.pos]
        return Token(TokenType.BLOCK_COMMENT, value, start_line, start_col)

    def _scan_string(self) -> Token:
        """Scan a double-quoted string.

        Returns
        -------
        Token
            The string token.
        """
        start_line = self.line
        start_col = self.column
        start_pos = self.pos

        self._advance()  # Skip opening "

        while self.pos < len(self.source):
            char = self.source[self.pos]
            if char == '"':
                self._advance()  # Skip closing "
                break
            if char == "\n":
                # String continues on next line (shouldn't happen in valid SCL)
                break
            self._advance()

        value = self.source[start_pos : self.pos]
        return Token(TokenType.STRING, value, start_line, start_col)

    def _scan_single_string(self) -> Token:
        """Scan a single-quoted string.

        Returns
        -------
        Token
            The string token.
        """
        start_line = self.line
        start_col = self.column
        start_pos = self.pos

        self._advance()  # Skip opening '

        while self.pos < len(self.source):
            char = self.source[self.pos]
            if char == "'":
                self._advance()  # Skip closing '
                break
            self._advance()

        value = self.source[start_pos : self.pos]
        return Token(TokenType.STRING, value, start_line, start_col)

    def _scan_number(self) -> Token:
        """Scan a numeric literal.

        Returns
        -------
        Token
            The number token.
        """
        start_line = self.line
        start_col = self.column
        start_pos = self.pos

        # Handle negative sign
        if self.source[self.pos] == "-":
            self._advance()

        # Integer part
        while self.pos < len(self.source) and self.source[self.pos].isdigit():
            self._advance()

        # Decimal part
        if self._peek() == "." and self._peek(1).isdigit():
            self._advance()  # Skip .
            while self.pos < len(self.source) and self.source[self.pos].isdigit():
                self._advance()

        # Exponent part
        if self._peek().lower() == "e":
            self._advance()
            if self._peek() in "+-":
                self._advance()
            while self.pos < len(self.source) and self.source[self.pos].isdigit():
                self._advance()

        value = self.source[start_pos : self.pos]
        return Token(TokenType.NUMBER, value, start_line, start_col)

    def _scan_identifier(self) -> Token:
        """Scan an identifier or keyword.

        Returns
        -------
        Token
            The identifier or keyword token.
        """
        start_line = self.line
        start_col = self.column
        start_pos = self.pos

        while self.pos < len(self.source):
            char = self.source[self.pos]
            if char.isalnum() or char == "_":
                self._advance()
            else:
                break

        value = self.source[start_pos : self.pos]
        upper_value = value.upper()

        # Check for keyword
        if upper_value in KEYWORDS:
            return Token(KEYWORDS[upper_value], value, start_line, start_col)

        return Token(TokenType.IDENTIFIER, value, start_line, start_col)

    def _scan_pragma_content(self) -> Token | None:
        """Scan content inside a pragma block.

        Returns
        -------
        Token | None
            The pragma content token or None if whitespace.
        """
        # Skip whitespace and newlines inside pragma
        while self.pos < len(self.source) and self.source[self.pos] in " \t\r\n":
            if self.source[self.pos] == "\n":
                self.line += 1
                self.column = 1
            else:
                self.column += 1
            self.pos += 1

        if self.pos >= len(self.source) or self.source[self.pos] == "}":
            return None

        start_line = self.line
        start_col = self.column
        start_pos = self.pos

        # Read until next ; or }
        while self.pos < len(self.source):
            char = self.source[self.pos]
            if char == "}" or char == ";":
                break
            if char == "\n":
                self.line += 1
                self.column = 1
            else:
                self.column += 1
            self.pos += 1

        # Skip trailing semicolon
        if self.pos < len(self.source) and self.source[self.pos] == ";":
            self.pos += 1
            self.column += 1

        value = self.source[start_pos : self.pos].strip().rstrip(";")
        if not value:
            return None

        return Token(TokenType.PRAGMA_CONTENT, value, start_line, start_col)


def tokenize(source: str) -> list[Token]:
    """Convenience function to tokenize SCL source.

    Parameters
    ----------
    source : str
        The SCL source code.

    Returns
    -------
    list[Token]
        List of all tokens (excluding whitespace, including EOF).
    """
    lexer = SCLLexer(source)
    tokens = []
    for token in lexer.tokenize():
        if token.type not in (TokenType.WHITESPACE, TokenType.NEWLINE):
            tokens.append(token)
    return tokens


def tokenize_with_newlines(source: str) -> list[Token]:
    """Tokenize SCL source, preserving newlines.

    Parameters
    ----------
    source : str
        The SCL source code.

    Returns
    -------
    list[Token]
        List of all tokens including newlines.
    """
    lexer = SCLLexer(source)
    return list(lexer.tokenize())
