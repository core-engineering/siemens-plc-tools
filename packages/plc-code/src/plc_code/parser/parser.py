"""SCL parser for TIA Portal V21 exports.

This module provides parsing of tokenized SCL source into structured
Block objects containing all metadata, variables, and code regions.
"""

from pathlib import Path

import yaml

from plc_code.parser.lexer import Token, TokenType, tokenize_with_newlines
from plc_code.parser.models import (
    Block,
    BlockAttributes,
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


class ParseError(Exception):
    """Exception raised when parsing fails."""

    pass


class SCLParser:
    """Parser for TIA Portal V21 SCL exports.

    Parses tokenized SCL source into structured Block objects.

    Parameters
    ----------
    tokens : list[Token]
        List of tokens from the lexer.

    Examples
    --------
    >>> tokens = tokenize_with_newlines(source)
    >>> parser = SCLParser(tokens)
    >>> block = parser.parse()
    """

    def __init__(self, tokens: list[Token]) -> None:
        """Initialize the parser.

        Parameters
        ----------
        tokens : list[Token]
            List of tokens from the lexer.
        """
        self.tokens = tokens
        self.pos = 0
        self.current_block: Block | None = None

    def parse(self) -> Block:
        """Parse tokens into a Block.

        Returns
        -------
        Block
            The parsed block structure.

        Raises
        ------
        ParseError
            When parsing fails.
        """
        # Skip initial newlines
        self._skip_newlines()

        # Parse block attributes (pragma before block declaration)
        attributes = self._parse_block_attributes()

        # Parse block declaration
        block = self._parse_block_declaration(attributes)
        self.current_block = block

        # Parse block content
        self._parse_block_content(block)

        return block

    def _current(self) -> Token:
        """Get current token.

        Returns
        -------
        Token
            Current token.
        """
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return Token(TokenType.EOF, "", 0, 0)

    def _peek(self, offset: int = 1) -> Token:
        """Peek at a future token.

        Parameters
        ----------
        offset : int
            Offset from current position.

        Returns
        -------
        Token
            Token at offset position.
        """
        pos = self.pos + offset
        if pos < len(self.tokens):
            return self.tokens[pos]
        return Token(TokenType.EOF, "", 0, 0)

    def _advance(self) -> Token:
        """Advance to next token.

        Returns
        -------
        Token
            The token that was current before advancing.
        """
        token = self._current()
        self.pos += 1
        return token

    def _skip_newlines(self) -> None:
        """Skip any newline tokens."""
        while self._current().type == TokenType.NEWLINE:
            self._advance()

    def _skip_pragma(self) -> None:
        """Skip an inline pragma block { ... }."""
        if self._current().type != TokenType.PRAGMA_START:
            return
        self._advance()  # Skip {
        # Skip until we find the closing }
        while self._current().type not in (TokenType.PRAGMA_END, TokenType.EOF):
            self._advance()
        if self._current().type == TokenType.PRAGMA_END:
            self._advance()  # Skip }

    def _expect(self, token_type: TokenType) -> Token:
        """Expect a specific token type.

        Parameters
        ----------
        token_type : TokenType
            Expected token type.

        Returns
        -------
        Token
            The matched token.

        Raises
        ------
        ParseError
            When token type doesn't match.
        """
        token = self._current()
        if token.type != token_type:
            raise ParseError(
                f"Expected {token_type.name} at line {token.line}, "
                f"got {token.type.name} ({token.value!r})"
            )
        return self._advance()

    def _parse_block_attributes(self) -> BlockAttributes:
        """Parse block header attributes from pragma.

        Returns
        -------
        BlockAttributes
            Parsed attributes.
        """
        attrs = BlockAttributes()

        if self._current().type != TokenType.PRAGMA_START:
            return attrs

        self._advance()  # Skip {
        self._skip_newlines()

        while self._current().type == TokenType.PRAGMA_CONTENT:
            content = self._current().value
            self._advance()
            self._skip_newlines()

            # Parse S7_xxx := "value" patterns
            if ":=" in content:
                key, value = content.split(":=", 1)
                key = key.strip()
                value = value.strip().strip('"')

                if key == "S7_Author":
                    attrs.author = value
                elif key == "S7_Version":
                    attrs.version = value
                elif key == "S7_Family":
                    attrs.family = value
                elif key == "S7_Optimized":
                    attrs.optimized = value.upper() == "TRUE"
                elif key == "S7_Safety":
                    attrs.is_safety = value.upper() == "TRUE"
                elif key == "S7_EditorMode":
                    attrs.editor_mode = value
                elif key == "S7_PreferredLanguage":
                    attrs.preferred_language = value  # type: ignore[assignment]
                elif key == "S7_BlockTitle":
                    attrs.block_title_mlc = value
                elif key == "S7_BlockComment":
                    attrs.block_comment_mlc = value

        if self._current().type == TokenType.PRAGMA_END:
            self._advance()

        self._skip_newlines()
        return attrs

    def _parse_block_declaration(self, attributes: BlockAttributes) -> Block:
        """Parse block declaration (FUNCTION_BLOCK, FUNCTION, TYPE, or ORGANIZATION_BLOCK).

        Parameters
        ----------
        attributes : BlockAttributes
            Already parsed attributes.

        Returns
        -------
        Block
            Block with basic info filled in.

        Raises
        ------
        ParseError
            When no valid block declaration found.
        """
        token = self._current()

        if token.type == TokenType.FUNCTION_BLOCK:
            self._advance()
            name = self._parse_block_name()
            return Block(
                name=name,
                block_type="FUNCTION_BLOCK",
                attributes=attributes,
            )

        elif token.type == TokenType.FUNCTION:
            self._advance()
            name = self._parse_block_name()
            return_type = self._parse_return_type()
            return Block(
                name=name,
                block_type="FUNCTION",
                attributes=attributes,
                return_type=return_type,
            )

        elif token.type == TokenType.TYPE:
            self._advance()
            self._skip_newlines()
            # TYPE declarations have name inside
            return Block(
                name="",  # Will be filled when parsing UDT
                block_type="TYPE",
                attributes=attributes,
            )

        elif token.type == TokenType.ORGANIZATION_BLOCK:
            self._advance()
            name = self._parse_block_name()
            return Block(
                name=name,
                block_type="ORGANIZATION_BLOCK",
                attributes=attributes,
            )

        elif token.type == TokenType.DATA_BLOCK:
            self._advance()
            name = self._parse_block_name()
            base_type = self._parse_data_block_type()
            return Block(
                name=name,
                block_type="DATA_BLOCK",
                attributes=attributes,
                base_type=base_type,
            )

        raise ParseError(f"Expected block declaration at line {token.line}, " f"got {token.type.name}")

    def _parse_block_name(self) -> str:
        """Parse block name from string token.

        Returns
        -------
        str
            Block name without quotes.
        """
        self._skip_newlines()
        token = self._current()

        if token.type == TokenType.STRING:
            self._advance()
            # Remove quotes
            return token.value.strip('"')

        if token.type == TokenType.IDENTIFIER:
            self._advance()
            return token.value

        raise ParseError(f"Expected block name at line {token.line}")

    def _parse_return_type(self) -> str | None:
        """Parse function return type.

        Returns
        -------
        str | None
            Return type or None if not specified.
        """
        self._skip_newlines()
        if self._current().type == TokenType.COLON:
            self._advance()
            self._skip_newlines()
            token = self._expect(TokenType.IDENTIFIER)
            return token.value
        return None

    def _parse_data_block_type(self) -> str | None:
        """Parse data block base type (e.g., DATA_BLOCK name : typeName).

        Returns
        -------
        str | None
            Base type name or None if not specified.
        """
        self._skip_newlines()
        if self._current().type == TokenType.COLON:
            self._advance()
            self._skip_newlines()
            token = self._current()
            if token.type == TokenType.IDENTIFIER:
                self._advance()
                return token.value
        return None

    def _parse_block_content(self, block: Block) -> None:
        """Parse the content of a block.

        Parameters
        ----------
        block : Block
            Block to fill with content.
        """
        self._skip_newlines()

        # For TYPE blocks, parse UDT structure
        if block.block_type == "TYPE":
            self._parse_udt(block)
            return

        # For DATA_BLOCK, skip to END_DATA_BLOCK (content is initial values)
        if block.block_type == "DATA_BLOCK":
            while self._current().type != TokenType.EOF:
                if self._current().type == TokenType.END_DATA_BLOCK:
                    self._advance()
                    return
                self._advance()
            return

        # Parse variable sections and networks
        while self._current().type != TokenType.EOF:
            token = self._current()

            if token.type in (
                TokenType.END_FUNCTION_BLOCK,
                TokenType.END_FUNCTION,
                TokenType.END_TYPE,
                TokenType.END_ORGANIZATION_BLOCK,
                TokenType.END_DATA_BLOCK,
            ):
                self._advance()
                break

            elif token.type in (
                TokenType.VAR_INPUT,
                TokenType.VAR_OUTPUT,
                TokenType.VAR_IN_OUT,
                TokenType.VAR,
                TokenType.VAR_TEMP,
            ):
                section = self._parse_variable_section()
                block.variable_sections.append(section)

            elif token.type == TokenType.PRAGMA_START:
                # Could be network pragma or variable attributes
                self._parse_pragma_or_network(block)

            elif token.type == TokenType.NETWORK:
                network = self._parse_network()
                block.networks.append(network)

            else:
                self._advance()

            self._skip_newlines()

    def _parse_variable_section(self) -> VariableSection:
        """Parse a VAR_xxx ... END_VAR section.

        Returns
        -------
        VariableSection
            Parsed variable section.
        """
        section_token = self._advance()
        section_type = section_token.type.name  # VAR_INPUT, VAR_OUTPUT, etc.

        # Check for VAR CONSTANT
        self._skip_newlines()
        is_constant = False
        if section_type == "VAR" and self._current().type == TokenType.VAR_CONSTANT:
            self._advance()
            section_type = "VAR_CONSTANT"
            is_constant = True

        section = VariableSection(
            section_type=section_type,  # type: ignore[arg-type]
            is_constant=is_constant,
        )

        self._skip_newlines()

        # Parse variables until END_VAR
        pending_attributes = VariableAttributes()

        while self._current().type != TokenType.END_VAR:
            if self._current().type == TokenType.EOF:
                break

            # Variable attributes pragma
            if self._current().type == TokenType.PRAGMA_START:
                pending_attributes = self._parse_variable_attributes()
                self._skip_newlines()
                continue

            # Variable declaration (identifier or quoted string for reserved words)
            if self._current().type in (TokenType.IDENTIFIER, TokenType.STRING):
                var = self._parse_variable_declaration(pending_attributes)
                section.variables.append(var)
                pending_attributes = VariableAttributes()
                self._skip_newlines()
                continue

            # Skip any other token to avoid infinite loop
            self._advance()
            self._skip_newlines()

        if self._current().type == TokenType.END_VAR:
            self._advance()

        return section

    def _parse_variable_attributes(self) -> VariableAttributes:
        """Parse variable attributes from pragma.

        Returns
        -------
        VariableAttributes
            Parsed attributes.
        """
        attrs = VariableAttributes()

        if self._current().type != TokenType.PRAGMA_START:
            return attrs

        self._advance()  # Skip {
        self._skip_newlines()

        while self._current().type == TokenType.PRAGMA_CONTENT:
            content = self._current().value
            self._advance()
            self._skip_newlines()

            if ":=" in content:
                key, value = content.split(":=", 1)
                key = key.strip()
                value = value.strip().strip('"')

                if key == "S7_Access":
                    attrs.access = value
                elif key == "S7_Visibility":
                    attrs.visibility = value
                elif key == "S7_MLC":
                    attrs.mlc_id = value

        if self._current().type == TokenType.PRAGMA_END:
            self._advance()

        return attrs

    def _parse_variable_declaration(self, attributes: VariableAttributes) -> VariableDeclaration:
        """Parse a variable declaration.

        Parameters
        ----------
        attributes : VariableAttributes
            Pre-parsed attributes.

        Returns
        -------
        VariableDeclaration
            Parsed variable.
        """
        name = self._current().value
        # Strip quotes from quoted identifiers (e.g., "selection" for reserved words)
        if name.startswith('"') and name.endswith('"'):
            name = name[1:-1]
        self._advance()

        self._skip_newlines()
        self._expect(TokenType.COLON)
        self._skip_newlines()

        # Parse data type (may include _.TypeName or Array)
        data_type = self._parse_data_type()

        # Check for default value
        default_value = None
        self._skip_newlines()
        if self._current().type == TokenType.ASSIGN:
            self._advance()
            self._skip_newlines()
            default_value = self._parse_value()

        # Skip semicolon
        self._skip_newlines()
        if self._current().type == TokenType.SEMICOLON:
            self._advance()

        return VariableDeclaration(
            name=name,
            data_type=data_type,
            default_value=default_value,
            attributes=attributes,
        )

    def _parse_data_type(self) -> str:
        """Parse a data type specification.

        Returns
        -------
        str
            Data type string.
        """
        parts = []

        # Handle _.TypeName (library reference)
        if self._current().type == TokenType.IDENTIFIER and self._current().value == "_":
            parts.append("_")
            self._advance()
            if self._current().type == TokenType.DOT:
                parts.append(".")
                self._advance()

        # Main type name (e.g., Array, Bool, Real)
        if self._current().type == TokenType.IDENTIFIER:
            parts.append(self._current().value)
            self._advance()

        # Handle array indexing [...] and "of" clause
        # e.g., Array[0..99] of Real
        if self._current().type == TokenType.LBRACKET:
            parts.append("[")
            self._advance()
            while self._current().type not in (TokenType.RBRACKET, TokenType.EOF):
                parts.append(self._current().value)
                self._advance()
            if self._current().type == TokenType.RBRACKET:
                parts.append("]")
                self._advance()

            # Handle "of" keyword for array element type
            self._skip_newlines()
            if self._current().type == TokenType.IDENTIFIER and self._current().value.lower() == "of":
                parts.append(" of ")
                self._advance()
                self._skip_newlines()
                # Recursively parse element type
                element_type = self._parse_data_type()
                parts.append(element_type)

        return "".join(parts)

    def _parse_value(self) -> str:
        """Parse a value (default value or constant).

        Returns
        -------
        str
            Value as string.
        """
        parts = []

        # Collect tokens until semicolon or newline
        while self._current().type not in (
            TokenType.SEMICOLON,
            TokenType.NEWLINE,
            TokenType.EOF,
        ):
            parts.append(self._current().value)
            self._advance()

        return "".join(parts)

    def _parse_pragma_or_network(self, block: Block) -> None:
        """Parse a pragma that might be network attributes or block attributes.

        Parameters
        ----------
        block : Block
            Block to add network to.
        """
        # Parse pragma content
        attrs = NetworkAttributes()
        self._advance()  # Skip {
        self._skip_newlines()

        while self._current().type == TokenType.PRAGMA_CONTENT:
            content = self._current().value
            self._advance()
            self._skip_newlines()

            if ":=" in content:
                key, value = content.split(":=", 1)
                key = key.strip()
                value = value.strip().strip('"')

                # Network attributes
                if key == "S7_Language":
                    attrs.language = value  # type: ignore[assignment]
                elif key == "S7_NetworkTitle":
                    attrs.network_title_mlc = value
                elif key == "S7_NetworkComment":
                    attrs.network_comment_mlc = value
                # Block attributes that may appear here
                elif key == "S7_Optimized":
                    block.attributes.optimized = value.upper() == "TRUE"
                elif key == "S7_Safety":
                    block.attributes.is_safety = value.upper() == "TRUE"
                elif key == "S7_Author":
                    block.attributes.author = value
                elif key == "S7_Version":
                    block.attributes.version = value
                elif key == "S7_Family":
                    block.attributes.family = value
                elif key == "S7_EditorMode":
                    block.attributes.editor_mode = value
                elif key == "S7_PreferredLanguage":
                    block.attributes.preferred_language = value  # type: ignore[assignment]
                elif key == "S7_BlockTitle":
                    block.attributes.block_title_mlc = value
                elif key == "S7_BlockComment":
                    block.attributes.block_comment_mlc = value

        if self._current().type == TokenType.PRAGMA_END:
            self._advance()

        self._skip_newlines()

        # Check if followed by NETWORK
        if self._current().type == TokenType.NETWORK:
            network = self._parse_network(attrs)
            block.networks.append(network)

    def _parse_network(self, attrs: NetworkAttributes | None = None) -> Network:
        """Parse a NETWORK block.

        Parameters
        ----------
        attrs : NetworkAttributes | None
            Pre-parsed attributes.

        Returns
        -------
        Network
            Parsed network.
        """
        if attrs is None:
            attrs = NetworkAttributes()

        self._expect(TokenType.NETWORK)
        self._skip_newlines()

        network = Network(attributes=attrs)

        # Parse network content until END_NETWORK
        while self._current().type != TokenType.END_NETWORK:
            if self._current().type == TokenType.EOF:
                break

            # REGION blocks
            if self._current().type == TokenType.REGION:
                region = self._parse_region()
                network.regions.append(region)

            # RUNG elements (LADDER)
            elif self._current().type == TokenType.RUNG:
                rung = self._parse_rung()
                network.rungs_raw.append(rung)
                rung_elements = rung["elements"]
                assert isinstance(rung_elements, list)
                network.ladder_elements.extend(rung_elements)

            # A bare ``Label(NAME)`` that sits at network scope (before a RUNG).
            # TIA Portal emits jump targets this way (see ABS/SIGN END labels).
            # Capture it as its own raw rung so the ladder builder can turn it
            # into a LabelRung while keeping the existing content stream intact.
            elif (
                self._current().type == TokenType.IDENTIFIER
                and self._current().value == "Label"
                and self._peek().type == TokenType.LPAREN
            ):
                label_elem = self._parse_ladder_call()
                network.rungs_raw.append({"open_wire": "", "elements": [label_elem], "close_wire": None})
                network.ladder_elements.append(label_elem)

            # Other content
            else:
                # Emit a newline after comment tokens and semicolons so that:
                # 1. Comments end up on their own lines (control-flow preprocessor
                #    skips lines starting with "//" — merging into one line would
                #    swallow the subsequent executable code).
                # 2. Each SCL statement ends up on its own line (control-flow
                #    preprocessor splits on "\n"; without newlines after ";",
                #    all statements would be merged into one line and only the
                #    first assignment would be translated).
                if self._current().type in (TokenType.COMMENT, TokenType.BLOCK_COMMENT):
                    network.content += self._current().value + "\n"
                elif self._current().type == TokenType.SEMICOLON:
                    network.content += self._current().value + "\n"
                else:
                    network.content += self._current().value + " "
                self._advance()

            self._skip_newlines()

        if self._current().type == TokenType.END_NETWORK:
            self._advance()

        return network

    def _parse_region(self) -> Region:
        """Parse a REGION block.

        Returns
        -------
        Region
            Parsed region.
        """
        self._expect(TokenType.REGION)

        # Region name - can be a quoted string or a free-form sequence of tokens.
        # TIA Portal allows region names with hyphens, digits and other operator
        # characters (e.g. ``REGION Per-axis validation`` or ``REGION Set 7 phases``).
        # The lexer tokenises these into separate tokens (MINUS, NUMBER, ...), so we
        # must consume *everything* up to the end of the line rather than only
        # IDENTIFIER tokens — otherwise the tail leaks into the region content and is
        # later mistranslated as code.
        name_parts = []
        if self._current().type == TokenType.STRING:
            name_parts.append(self._current().value.strip('"'))
            self._advance()
        else:
            # Collect all tokens until the end of the line (or an inline comment).
            while self._current().type not in (
                TokenType.NEWLINE,
                TokenType.EOF,
                TokenType.COMMENT,
                TokenType.BLOCK_COMMENT,
            ):
                name_parts.append(self._current().value)
                self._advance()

        name = " ".join(part for part in name_parts if part).strip()
        self._skip_newlines()

        region = Region(name=name)
        content_parts = []
        token_parts: list[Token] = []

        # Parse content until END_REGION
        while self._current().type != TokenType.END_REGION:
            if self._current().type == TokenType.EOF:
                break

            # Nested REGION
            if self._current().type == TokenType.REGION:
                nested = self._parse_region()
                region.nested_regions.append(nested)
                # Also include nested region content in parent for code execution
                # This flattens the nested structure for transpilation
                if nested.content:
                    content_parts.append("\n")
                    content_parts.append(nested.content)
                    content_parts.append("\n")
                    token_parts.extend(nested.tokens)

            # MLC pragma
            elif self._current().type == TokenType.PRAGMA_START:
                mlc_id = self._parse_mlc_pragma()
                if mlc_id:
                    region.mlc_id = mlc_id

            # Comments and other content
            elif self._current().type == TokenType.COMMENT:
                content_parts.append(self._current().value)
                self._advance()

            # Block comments - preserve full content
            elif self._current().type == TokenType.BLOCK_COMMENT:
                content_parts.append(self._current().value)
                self._advance()

            elif self._current().type == TokenType.NEWLINE:
                content_parts.append("\n")
                self._advance()

            else:
                # Add space after token to preserve word boundaries
                content_parts.append(self._current().value)
                content_parts.append(" ")
                token_parts.append(self._current())
                self._advance()

        region.content = "".join(content_parts).strip()
        region.tokens = token_parts

        if self._current().type == TokenType.END_REGION:
            self._advance()
            # TIA Portal emits ``END_REGION <name>`` (the same free-form name as the
            # ``REGION <name>`` header, which may contain hyphens or digits).  Consume
            # every trailing token up to the end of the line so the name does not leak
            # into the parent's content.
            while self._current().type not in (
                TokenType.NEWLINE,
                TokenType.EOF,
                TokenType.COMMENT,
                TokenType.BLOCK_COMMENT,
            ):
                self._advance()

        return region

    def _parse_mlc_pragma(self) -> str:
        """Parse an MLC pragma.

        Returns
        -------
        str
            MLC ID if found.
        """
        self._advance()  # Skip {
        mlc_id = ""

        while self._current().type == TokenType.PRAGMA_CONTENT:
            content = self._current().value
            self._advance()

            if "S7_MLC" in content and ":=" in content:
                _, value = content.split(":=", 1)
                mlc_id = value.strip().strip('"')

            self._skip_newlines()

        if self._current().type == TokenType.PRAGMA_END:
            self._advance()

        return mlc_id

    def _read_wire(self) -> str:
        """Read a ``wire#<name>`` reference, returning ``wire#<name>`` or "".

        The lexer splits ``wire#powerrail`` into IDENTIFIER('wire'), HASH,
        IDENTIFIER('powerrail'); this consumes that sequence and rejoins it.
        """
        if not (
            self._current().type == TokenType.IDENTIFIER
            and self._current().value == "wire"
            and self._peek().type == TokenType.HASH
        ):
            return ""
        self._advance()  # wire
        self._advance()  # #
        name = ""
        if self._current().type == TokenType.IDENTIFIER:
            name = self._current().value
            self._advance()
        return f"wire#{name}"

    def _parse_ladder_call(self) -> str:
        """Parse a single ladder element token, e.g. ``Coil( #x )`` -> string.

        Assumes the current token is the element name (IDENTIFIER or STRING).
        Quotes are stripped from STRING names. Returns the element string with
        its parenthesised argument list collapsed (whitespace removed).
        """
        if self._current().type == TokenType.STRING:
            element = self._current().value.strip('"')
        else:
            element = self._current().value
        self._advance()

        if self._current().type == TokenType.LPAREN:
            element += "("
            self._advance()
            while self._current().type != TokenType.RPAREN:
                if self._current().type == TokenType.EOF:
                    break
                element += self._current().value
                self._advance()
            element += ")"
            if self._current().type == TokenType.RPAREN:
                self._advance()
        return element

    def _parse_rung(self) -> dict[str, object]:
        """Parse a LADDER RUNG.

        Returns
        -------
        dict
            ``{"open_wire": str, "elements": list[str], "close_wire": str | None}``.
            ``open_wire`` is the ``wire#…`` token following ``RUNG`` (e.g.
            ``wire#powerrail``); ``elements`` are the element strings (including
            any internal ``wire#…`` markers that appear between elements, e.g. the
            tap point of a parallel-OR branch); ``close_wire`` is the ``wire#…``
            token following ``END_RUNG`` if present (the branch's join point).
        """
        elements: list[str] = []
        self._advance()  # Skip RUNG

        # Capture the wire reference after RUNG (e.g., "RUNG wire#powerrail")
        open_wire = self._read_wire()
        self._skip_newlines()

        # Parse until END_RUNG
        while self._current().type != TokenType.END_RUNG:
            if self._current().type == TokenType.EOF:
                break

            # Skip inline pragmas like { S7_Templates := "SrcType := Int" }
            if self._current().type == TokenType.PRAGMA_START:
                self._skip_pragma()
                self._skip_newlines()
                continue

            # Internal wire markers (e.g. "wire#w1" between a contact and its
            # coil) tag the rail term that parallel-OR branches join onto.
            internal_wire = self._read_wire()
            if internal_wire:
                elements.append(internal_wire)
                self._skip_newlines()
                continue

            # Capture ladder elements like Contact(...), Coil(...), "FunctionName"(...)
            if self._current().type in (TokenType.IDENTIFIER, TokenType.STRING):
                elements.append(self._parse_ladder_call())
            else:
                self._advance()

            self._skip_newlines()

        close_wire: str | None = None
        if self._current().type == TokenType.END_RUNG:
            self._advance()
            # Capture the wire reference after END_RUNG (e.g., "END_RUNG wire#w2")
            wire = self._read_wire()
            close_wire = wire or None

        self._skip_newlines()
        return {"open_wire": open_wire, "elements": elements, "close_wire": close_wire}

    def _parse_udt(self, block: Block) -> None:
        """Parse a TYPE (UDT) definition.

        Parameters
        ----------
        block : Block
            Block to fill with UDT info.
        """
        # Get type name
        name = ""
        if self._current().type == TokenType.IDENTIFIER:
            name = self._current().value
            self._advance()

        self._skip_newlines()

        # Check for COLON and STRUCT
        if self._current().type == TokenType.COLON:
            self._advance()
            self._skip_newlines()

        if self._current().type == TokenType.STRUCT:
            self._advance()
            self._skip_newlines()

        block.name = name
        udt = UserDataType(name=name)

        # Parse struct fields
        pending_mlc = ""
        while self._current().type != TokenType.END_STRUCT:
            if self._current().type == TokenType.EOF:
                break

            # MLC pragma for field
            if self._current().type == TokenType.PRAGMA_START:
                pending_mlc = self._parse_mlc_pragma()
                self._skip_newlines()
                continue

            # Field declaration (identifier or quoted string for reserved words)
            if self._current().type in (TokenType.IDENTIFIER, TokenType.STRING):
                field_name = self._current().value
                # Strip quotes from quoted identifiers
                if field_name.startswith('"') and field_name.endswith('"'):
                    field_name = field_name[1:-1]
                self._advance()
                self._skip_newlines()
                self._expect(TokenType.COLON)
                self._skip_newlines()
                field_type = self._parse_data_type()
                self._skip_newlines()

                # Skip default value if present (e.g., := true)
                if self._current().type == TokenType.ASSIGN:
                    self._advance()  # skip :=
                    self._skip_newlines()
                    # Skip the default value expression until semicolon
                    while self._current().type not in (
                        TokenType.SEMICOLON,
                        TokenType.END_STRUCT,
                        TokenType.EOF,
                    ):
                        self._advance()
                        self._skip_newlines()

                if self._current().type == TokenType.SEMICOLON:
                    self._advance()

                field = StructField(
                    name=field_name,
                    data_type=field_type,
                    mlc_id=pending_mlc,
                )
                udt.fields.append(field)
                pending_mlc = ""
            else:
                # Skip unknown token to prevent infinite loop
                self._advance()

            self._skip_newlines()

        if self._current().type == TokenType.END_STRUCT:
            self._advance()

        self._skip_newlines()
        if self._current().type == TokenType.SEMICOLON:
            self._advance()

        self._skip_newlines()
        if self._current().type == TokenType.END_TYPE:
            self._advance()

        block.user_data_type = udt


def parse_scl_file(file_path: Path | str) -> Block:
    """Parse an SCL file into a Block.

    Parameters
    ----------
    file_path : Path | str
        Path to .s7dcl file.

    Returns
    -------
    Block
        Parsed block.

    Raises
    ------
    FileNotFoundError
        When file doesn't exist.
    ParseError
        When parsing fails.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"SCL file not found: {file_path}")

    source = file_path.read_text(encoding="utf-8-sig")
    tokens = tokenize_with_newlines(source)
    parser = SCLParser(tokens)
    block = parser.parse()
    block.source_file = str(file_path)

    # Try to load associated resource file
    res_path = file_path.with_suffix(".s7res")
    if res_path.exists():
        block.resource_file = parse_resource_file(res_path)

    return block


def parse_resource_file(file_path: Path) -> ResourceFile:
    """Parse an .s7res resource file.

    Parameters
    ----------
    file_path : Path
        Path to .s7res file.

    Returns
    -------
    ResourceFile
        Parsed resource file with MLC texts.
    """
    if not file_path.exists():
        return ResourceFile()

    content = file_path.read_text(encoding="utf-8-sig")

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return ResourceFile()

    if not data or "MultiLingualTexts" not in data:
        return ResourceFile()

    resource = ResourceFile()
    for entry in data["MultiLingualTexts"]:
        mlc_id = entry.get("id", "")
        text = entry.get("en-US", "")
        resource.texts[mlc_id] = MultiLingualText(
            id=mlc_id,
            text=text,
        )

    return resource


def parse_libinfo_file(file_path: Path) -> LibraryInfo:
    """Parse a .libinfo file.

    Parameters
    ----------
    file_path : Path
        Path to .libinfo file.

    Returns
    -------
    LibraryInfo
        Parsed library info.
    """
    if not file_path.exists():
        return LibraryInfo()

    content = file_path.read_text(encoding="utf-8-sig")

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return LibraryInfo()

    if not data:
        return LibraryInfo()

    lib_type = data.get("LibraryType", {})
    lib_version = data.get("LibraryVersion", {})

    return LibraryInfo(
        guid=lib_type.get("Guid", ""),
        version_number=lib_version.get("VersionNumber", ""),
        author=lib_version.get("Author", ""),
        is_default=lib_version.get("IsDefault", True),
    )


def parse_libint_file(file_path: Path) -> LibraryInterface:
    """Parse a .libint file.

    Parameters
    ----------
    file_path : Path
        Path to .libint file.

    Returns
    -------
    LibraryInterface
        Parsed library interface.
    """
    if not file_path.exists():
        return LibraryInterface()

    content = file_path.read_text(encoding="utf-8-sig")

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return LibraryInterface()

    if not data:
        return LibraryInterface()

    doc_hash = data.get("DocumentHash", [])
    lib_version = data.get("LibraryVersion", {})

    return LibraryInterface(
        document_hash=doc_hash,
        guid=lib_version.get("Guid", ""),
        dependencies=lib_version.get("DependsOn", []),
    )
