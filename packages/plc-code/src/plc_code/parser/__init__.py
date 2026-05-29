"""SCL parsing module.

This module provides tools to tokenize and parse TIA Portal V21 SCL exports
into structured data models.
"""

from plc_code.parser.lexer import SCLLexer, Token, TokenType, tokenize, tokenize_with_newlines
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
from plc_code.parser.parser import (
    ParseError,
    SCLParser,
    parse_libinfo_file,
    parse_libint_file,
    parse_resource_file,
    parse_scl_file,
)

__all__ = [
    # Lexer
    "SCLLexer",
    "Token",
    "TokenType",
    "tokenize",
    "tokenize_with_newlines",
    # Parser
    "ParseError",
    "SCLParser",
    "parse_scl_file",
    "parse_resource_file",
    "parse_libinfo_file",
    "parse_libint_file",
    # Models
    "Block",
    "BlockAttributes",
    "ChangeLogEntry",
    "HeaderInfo",
    "LibraryInfo",
    "LibraryInterface",
    "MultiLingualText",
    "Network",
    "NetworkAttributes",
    "Region",
    "ResourceFile",
    "StructField",
    "UserDataType",
    "VariableAttributes",
    "VariableDeclaration",
    "VariableSection",
]
