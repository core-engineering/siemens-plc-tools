"""Data models for parsed SCL and LADDER blocks.

This module defines the data structures used to represent parsed TIA Portal
V21 exports, including function blocks, functions, user data types, and their
associated metadata.
"""

from dataclasses import dataclass, field
from typing import Literal

# Block types
BlockType = Literal["FUNCTION_BLOCK", "FUNCTION", "TYPE", "ORGANIZATION_BLOCK", "DATA_BLOCK"]

# Variable section types
VarSection = Literal["VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR", "VAR_TEMP", "VAR_CONSTANT"]

# Programming languages
Language = Literal["SCL", "LAD", "FBD", "STL", "GRAPH"]


@dataclass
class BlockAttributes:
    """Attributes from the block header pragma.

    Attributes
    ----------
    author : str
        Block author (S7_Author).
    version : str
        Block version (S7_Version).
    family : str
        Library family (S7_Family).
    optimized : bool
        Whether block is optimized (S7_Optimized).
    editor_mode : str
        Editor mode (S7_EditorMode), typically "SCL".
    preferred_language : Language
        Preferred programming language (S7_PreferredLanguage).
    block_title_mlc : str
        MLC reference for block title (S7_BlockTitle).
    block_comment_mlc : str
        MLC reference for block comment (S7_BlockComment).
    """

    author: str = ""
    version: str = ""
    family: str = ""
    optimized: bool = True
    editor_mode: str = ""
    preferred_language: Language = "SCL"
    block_title_mlc: str = ""
    block_comment_mlc: str = ""


@dataclass
class VariableAttributes:
    """Attributes for a variable declaration.

    Attributes
    ----------
    access : str
        Access mode (S7_Access), e.g., "ReadOnly := External".
    visibility : str
        Visibility (S7_Visibility), e.g., "Hidden := External".
    mlc_id : str
        Multi-language comment reference (S7_MLC).
    """

    access: str = ""
    visibility: str = ""
    mlc_id: str = ""


@dataclass
class VariableDeclaration:
    """A variable declaration within a VAR section.

    Attributes
    ----------
    name : str
        Variable name.
    data_type : str
        Data type (e.g., "Bool", "Real", "TON_TIME", "_.TypeName").
    default_value : str | None
        Default value if specified.
    attributes : VariableAttributes
        Variable attributes from pragmas.
    comment : str
        Inline comment if present.
    """

    name: str
    data_type: str
    default_value: str | None = None
    attributes: VariableAttributes = field(default_factory=VariableAttributes)
    comment: str = ""


@dataclass
class VariableSection:
    """A section of variable declarations (VAR_INPUT, VAR_OUTPUT, etc.).

    Attributes
    ----------
    section_type : VarSection
        Type of variable section.
    variables : list[VariableDeclaration]
        List of variables in this section.
    is_constant : bool
        Whether this is a CONSTANT section.
    """

    section_type: VarSection
    variables: list[VariableDeclaration] = field(default_factory=list)
    is_constant: bool = False


@dataclass
class NetworkAttributes:
    """Attributes for a NETWORK block.

    Attributes
    ----------
    language : Language
        Programming language (S7_Language).
    network_title_mlc : str
        MLC reference for network title (S7_NetworkTitle).
    network_comment_mlc : str
        MLC reference for network comment (S7_NetworkComment).
    """

    language: Language = "SCL"
    network_title_mlc: str = ""
    network_comment_mlc: str = ""


@dataclass
class Region:
    """A REGION block within the code.

    Attributes
    ----------
    name : str
        Region name from REGION declaration.
    content : str
        Raw content within the region.
    nested_regions : list[Region]
        Nested REGION blocks.
    mlc_id : str
        MLC reference if present (S7_MLC pragma).
    """

    name: str
    content: str = ""
    nested_regions: list["Region"] = field(default_factory=list)
    mlc_id: str = ""


@dataclass
class Network:
    """A NETWORK block containing code.

    Attributes
    ----------
    attributes : NetworkAttributes
        Network attributes from pragma.
    regions : list[Region]
        REGION blocks within the network.
    content : str
        Raw content of the network (for LADDER: RUNG elements).
    ladder_elements : list[str]
        Parsed LADDER elements (Contact, Coil, etc.).
    """

    attributes: NetworkAttributes = field(default_factory=NetworkAttributes)
    regions: list[Region] = field(default_factory=list)
    content: str = ""
    ladder_elements: list[str] = field(default_factory=list)


@dataclass
class ChangeLogEntry:
    """An entry in the change log table.

    Attributes
    ----------
    version : str
        Version number (e.g., "v1.0.0").
    date : str
        Date string (e.g., "07/04/2025").
    author : str
        Expert in charge.
    changes : str
        Description of changes.
    """

    version: str
    date: str
    author: str
    changes: str


@dataclass
class HeaderInfo:
    """Parsed information from "Block info header" REGION.

    Attributes
    ----------
    title : str
        Block title.
    comment : str
        Block comment/function description.
    library : str
        Library/Family name.
    author : str
        Author name.
    copyright : str
        Copyright notice.
    changelog : list[ChangeLogEntry]
        Change log entries.
    """

    title: str = ""
    comment: str = ""
    library: str = ""
    author: str = ""
    copyright: str = ""
    changelog: list[ChangeLogEntry] = field(default_factory=list)


@dataclass
class MultiLingualText:
    """A multi-language text entry from .s7res file.

    Attributes
    ----------
    id : str
        MLC identifier (e.g., "MLC_3Vc").
    text : str
        Text content (en-US by default).
    language : str
        Language code (default: "en-US").
    """

    id: str
    text: str
    language: str = "en-US"


@dataclass
class ResourceFile:
    """Parsed .s7res resource file containing MLC texts.

    Attributes
    ----------
    texts : dict[str, MultiLingualText]
        Mapping from MLC ID to text content.
    """

    texts: dict[str, MultiLingualText] = field(default_factory=dict)

    def get_text(self, mlc_id: str) -> str:
        """Get text for an MLC ID.

        Parameters
        ----------
        mlc_id : str
            The MLC identifier.

        Returns
        -------
        str
            The text content, or empty string if not found.
        """
        if mlc_id in self.texts:
            return self.texts[mlc_id].text
        return ""


@dataclass
class StructField:
    """A field within a STRUCT type.

    Attributes
    ----------
    name : str
        Field name.
    data_type : str
        Data type.
    mlc_id : str
        MLC reference for description.
    comment : str
        Resolved comment from MLC.
    """

    name: str
    data_type: str
    mlc_id: str = ""
    comment: str = ""


@dataclass
class UserDataType:
    """A user-defined data type (TYPE ... END_TYPE).

    Attributes
    ----------
    name : str
        Type name.
    fields : list[StructField]
        Fields in the STRUCT.
    """

    name: str
    fields: list[StructField] = field(default_factory=list)


@dataclass
class Block:
    """A complete parsed SCL/LADDER block.

    Attributes
    ----------
    name : str
        Block name.
    block_type : BlockType
        Type of block (FUNCTION_BLOCK, FUNCTION, TYPE).
    attributes : BlockAttributes
        Block header attributes.
    return_type : str | None
        Return type for FUNCTIONs (e.g., "Void", "Real").
    base_type : str | None
        For DATA_BLOCKs: the UDT type name (e.g., "typeProcessData").
    variable_sections : list[VariableSection]
        Variable declarations grouped by section.
    networks : list[Network]
        NETWORK blocks containing code.
    header_info : HeaderInfo
        Parsed "Block info header" content.
    description : str
        Content from "Description" REGION.
    source_file : str
        Path to source .s7dcl file.
    resource_file : ResourceFile | None
        Associated .s7res file if present.
    user_data_type : UserDataType | None
        For TYPE blocks, the parsed UDT structure.
    """

    name: str
    block_type: BlockType
    attributes: BlockAttributes = field(default_factory=BlockAttributes)
    return_type: str | None = None
    base_type: str | None = None  # For DATA_BLOCKs: the UDT type name
    variable_sections: list[VariableSection] = field(default_factory=list)
    networks: list[Network] = field(default_factory=list)
    header_info: HeaderInfo = field(default_factory=HeaderInfo)
    description: str = ""
    source_file: str = ""
    resource_file: ResourceFile | None = None
    user_data_type: UserDataType | None = None

    def get_variables_by_section(self, section_type: VarSection) -> list[VariableDeclaration]:
        """Get all variables from a specific section type.

        Parameters
        ----------
        section_type : VarSection
            The section type to filter by.

        Returns
        -------
        list[VariableDeclaration]
            Variables in that section.
        """
        for section in self.variable_sections:
            if section.section_type == section_type:
                return section.variables
        return []

    @property
    def inputs(self) -> list[VariableDeclaration]:
        """Get VAR_INPUT variables."""
        return self.get_variables_by_section("VAR_INPUT")

    @property
    def outputs(self) -> list[VariableDeclaration]:
        """Get VAR_OUTPUT variables."""
        return self.get_variables_by_section("VAR_OUTPUT")

    @property
    def in_outs(self) -> list[VariableDeclaration]:
        """Get VAR_IN_OUT variables."""
        return self.get_variables_by_section("VAR_IN_OUT")

    @property
    def static_vars(self) -> list[VariableDeclaration]:
        """Get VAR (static) variables."""
        return self.get_variables_by_section("VAR")

    @property
    def temp_vars(self) -> list[VariableDeclaration]:
        """Get VAR_TEMP variables."""
        return self.get_variables_by_section("VAR_TEMP")

    @property
    def constants(self) -> list[VariableDeclaration]:
        """Get VAR CONSTANT variables."""
        return self.get_variables_by_section("VAR_CONSTANT")

    @property
    def is_ladder(self) -> bool:
        """Check if block uses LADDER language."""
        return self.attributes.preferred_language == "LAD"

    @property
    def is_scl(self) -> bool:
        """Check if block uses SCL language."""
        return self.attributes.preferred_language == "SCL" or self.attributes.editor_mode == "SCL"


@dataclass
class LibraryInfo:
    """Parsed .libinfo file content.

    Attributes
    ----------
    guid : str
        Library type GUID.
    version_number : str
        Version number string.
    author : str
        Author name.
    is_default : bool
        Whether this is the default version.
    """

    guid: str = ""
    version_number: str = ""
    author: str = ""
    is_default: bool = True


@dataclass
class LibraryInterface:
    """Parsed .libint file content.

    Attributes
    ----------
    document_hash : list[dict]
        Document hash information.
    guid : str
        Library version GUID.
    dependencies : list[dict]
        List of dependencies with TypeName and VersionNumber.
    """

    document_hash: list[dict[str, str]] = field(default_factory=list)
    guid: str = ""
    dependencies: list[dict[str, str]] = field(default_factory=list)
