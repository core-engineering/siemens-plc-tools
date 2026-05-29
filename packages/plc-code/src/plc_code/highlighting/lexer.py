"""Pygments lexer for TIA Portal SCL (Structured Control Language).

This module provides syntax highlighting for SCL code exported from
TIA Portal V21, including support for:
- Block declarations (FUNCTION_BLOCK, FUNCTION, TYPE)
- Variable sections (VAR, VAR_INPUT, VAR_OUTPUT, VAR_IN_OUT, VAR_TEMP, VAR CONSTANT)
- Control structures (IF/ELSIF/ELSE, CASE, FOR, WHILE, REPEAT)
- REGIONs and NETWORKs
- S7 pragmas and attributes
- Data types (Bool, Int, Real, String, Time, etc.)
- Comments (// and (* *))
"""

from pygments.lexer import RegexLexer, bygroups, words
from pygments.token import (
    Comment,
    Keyword,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
    Whitespace,
)


class SCLLexer(RegexLexer):
    """Pygments lexer for TIA Portal SCL syntax.

    Handles SCL (Structured Control Language) as used in Siemens
    TIA Portal V21 for PLC programming.
    """

    name = "SCL"
    aliases = ["scl", "s7scl", "structured-control-language"]
    filenames = ["*.scl", "*.s7dcl"]
    mimetypes = ["text/x-scl"]

    # SCL keywords (case-insensitive)
    keywords = (
        "AND",
        "OR",
        "XOR",
        "NOT",
        "MOD",
        "DIV",
        "TRUE",
        "FALSE",
    )

    # Block declaration keywords
    block_keywords = (
        "FUNCTION_BLOCK",
        "END_FUNCTION_BLOCK",
        "FUNCTION",
        "END_FUNCTION",
        "TYPE",
        "END_TYPE",
        "STRUCT",
        "END_STRUCT",
        "ORGANIZATION_BLOCK",
        "END_ORGANIZATION_BLOCK",
        "DATA_BLOCK",
        "END_DATA_BLOCK",
    )

    # Variable section keywords
    var_keywords = (
        "VAR",
        "VAR_INPUT",
        "VAR_OUTPUT",
        "VAR_IN_OUT",
        "VAR_TEMP",
        "VAR_GLOBAL",
        "VAR_EXTERNAL",
        "END_VAR",
        "CONSTANT",
    )

    # Control flow keywords
    control_keywords = (
        "IF",
        "THEN",
        "ELSIF",
        "ELSE",
        "END_IF",
        "CASE",
        "OF",
        "END_CASE",
        "FOR",
        "TO",
        "BY",
        "DO",
        "END_FOR",
        "WHILE",
        "END_WHILE",
        "REPEAT",
        "UNTIL",
        "END_REPEAT",
        "EXIT",
        "CONTINUE",
        "RETURN",
        "GOTO",
    )

    # Structure keywords
    structure_keywords = (
        "REGION",
        "END_REGION",
        "NETWORK",
        "END_NETWORK",
        "BEGIN",
        "END",
        "LABEL",
        "END_LABEL",
    )

    # Data types
    builtin_types = (
        # Basic types
        "Bool",
        "Byte",
        "Word",
        "DWord",
        "LWord",
        "Int",
        "DInt",
        "LInt",
        "UInt",
        "UDInt",
        "ULInt",
        "SInt",
        "USInt",
        "Real",
        "LReal",
        "Char",
        "WChar",
        "String",
        "WString",
        "Time",
        "LTime",
        "Date",
        "Time_Of_Day",
        "TOD",
        "Date_And_Time",
        "DT",
        "LDT",
        "DTL",
        "S5Time",
        # Pointer and reference types
        "Pointer",
        "Any",
        "Variant",
        # Array
        "Array",
        # Timer and counter types
        "Timer",
        "Counter",
        "TON",
        "TOF",
        "TP",
        "TON_TIME",
        "TOF_TIME",
        "TP_TIME",
        "CTU",
        "CTD",
        "CTUD",
        # IEC types
        "IEC_TIMER",
        "IEC_COUNTER",
    )

    # Built-in functions
    builtins = (
        # Type conversions
        "INT_TO_REAL",
        "REAL_TO_INT",
        "DINT_TO_REAL",
        "REAL_TO_DINT",
        "BOOL_TO_INT",
        "INT_TO_BOOL",
        "BYTE_TO_INT",
        "INT_TO_BYTE",
        "WORD_TO_INT",
        "INT_TO_WORD",
        "DWORD_TO_DINT",
        "DINT_TO_DWORD",
        # Math functions
        "ABS",
        "SQR",
        "SQRT",
        "EXP",
        "EXPD",
        "LN",
        "LOG",
        "SIN",
        "COS",
        "TAN",
        "ASIN",
        "ACOS",
        "ATAN",
        "TRUNC",
        "ROUND",
        "CEIL",
        "FLOOR",
        "MAX",
        "MIN",
        "LIMIT",
        "SEL",
        "MUX",
        # Bit operations
        "ROL",
        "ROR",
        "SHL",
        "SHR",
        # String operations
        "LEN",
        "LEFT",
        "RIGHT",
        "MID",
        "CONCAT",
        "INSERT",
        "DELETE",
        "REPLACE",
        "FIND",
    )

    tokens = {
        "root": [
            # Whitespace
            (r"\s+", Whitespace),
            # S7 pragma blocks { ... }
            (r"\{", Punctuation, "pragma"),
            # Comments
            (r"//.*$", Comment.Single),
            (r"\(\*", Comment.Multiline, "comment"),
            # String literals (single quotes only - double quotes are for DB references)
            (r"'[^']*'", String.Single),
            # Numbers - hex/bin/oct must come before integer to match the prefix
            (r"16#[0-9A-Fa-f_]+", Number.Hex),
            (r"2#[01_]+", Number.Bin),
            (r"8#[0-7_]+", Number.Oct),
            (r"\b\d+\.\d*(?:[eE][+-]?\d+)?\b", Number.Float),
            (r"\b\d+[eE][+-]?\d+\b", Number.Float),
            (r"\b\d+\b", Number.Integer),
            # Time literals
            (r"T#[0-9dhms_]+", Number),
            (r"t#[0-9dhms_]+", Number),
            (r"TIME#[0-9dhms_]+", Number),
            # Date literals
            (r"\bD#[\d\-]+\b", Number),
            (r"\bDATE#[\d\-]+\b", Number),
            (r"\bDT#[\d\-:\.]+\b", Number),
            (r"\bTOD#[\d:\.]+\b", Number),
            # Block declarations
            (
                words(block_keywords, prefix=r"\b", suffix=r"\b"),
                Keyword.Declaration,
            ),
            # Variable sections
            (
                words(var_keywords, prefix=r"\b", suffix=r"\b"),
                Keyword.Declaration,
            ),
            # Control flow
            (
                words(control_keywords, prefix=r"\b", suffix=r"\b"),
                Keyword,
            ),
            # Structure keywords (REGION, NETWORK)
            (
                words(structure_keywords, prefix=r"\b", suffix=r"\b"),
                Keyword.Namespace,
            ),
            # Logical/arithmetic operators as keywords
            (
                words(keywords, prefix=r"\b", suffix=r"\b"),
                Keyword.Operator,
            ),
            # Built-in types
            (
                words(builtin_types, prefix=r"\b", suffix=r"\b"),
                Keyword.Type,
            ),
            # Built-in functions
            (
                words(builtins, prefix=r"\b", suffix=r"\b"),
                Name.Builtin,
            ),
            # Library type reference (_.)
            (r"_\.(\w+)", bygroups(Name.Class)),
            # Instance variable reference (#)
            (r"#(\w+)", bygroups(Name.Variable.Instance)),
            # Global data block reference ("BlockName" or "BlockName".member)
            (r'"[A-Za-z_]\w*"', Name.Variable.Global),
            # Function/block call or identifier
            (r"\b[A-Za-z_]\w*\b", Name),
            # Operators
            (r":=", Operator),  # Assignment
            (r"=>", Operator),  # Output assignment
            (r"<>", Operator),  # Not equal
            (r"<=", Operator),
            (r">=", Operator),
            (r"[+\-*/=<>]", Operator),
            # Punctuation
            (r"[()[\]{}.,;:]", Punctuation),
        ],
        "pragma": [
            # S7 pragma content
            (r"S7_\w+", Name.Attribute),
            (r":=", Operator),
            (r'"[^"]*"', String.Double),
            (r"'[^']*'", String.Single),
            (r"\w+", Name.Attribute),
            (r"\s+", Whitespace),
            (r"\}", Punctuation, "#pop"),
        ],
        "comment": [
            (r"\*\)", Comment.Multiline, "#pop"),
            (r"[^*]+", Comment.Multiline),
            (r"\*", Comment.Multiline),
        ],
    }

    def analyse_text(text: str) -> float:
        """Determine if text is likely SCL code.

        Parameters
        ----------
        text : str
            The text to analyze.

        Returns
        -------
        float
            Probability that the text is SCL code (0.0 to 1.0).
        """
        score = 0.0

        # Check for common SCL patterns
        if "FUNCTION_BLOCK" in text or "END_FUNCTION_BLOCK" in text:
            score += 0.4
        if "VAR_INPUT" in text or "VAR_OUTPUT" in text:
            score += 0.2
        if "END_REGION" in text or "REGION" in text:
            score += 0.2
        if "S7_" in text:
            score += 0.1
        if ":=" in text:
            score += 0.1

        return min(score, 1.0)
