"""Interface extraction from SCL blocks.

This module provides extraction of the block interface (inputs, outputs,
in-outs, static variables, etc.) with resolved MLC comments from .s7res files.
"""

from dataclasses import dataclass, field

from plc_code.parser.models import (
    Block,
    ResourceFile,
    UserDataType,
    VariableDeclaration,
    VariableSection,
)


@dataclass
class InterfaceVariable:
    """A variable with resolved documentation.

    Attributes
    ----------
    name : str
        Variable name.
    data_type : str
        Data type string.
    default_value : str | None
        Default value if specified.
    description : str
        Resolved description from MLC.
    access : str
        Access modifier (e.g., "ReadOnly").
    visibility : str
        Visibility modifier (e.g., "Hidden").
    is_library_type : bool
        Whether the data type references a library type.
    """

    name: str
    data_type: str
    default_value: str | None = None
    description: str = ""
    access: str = ""
    visibility: str = ""
    is_library_type: bool = False


@dataclass
class InterfaceSection:
    """A section of the interface.

    Attributes
    ----------
    section_type : str
        Type of section (VAR_INPUT, VAR_OUTPUT, etc.).
    variables : list[InterfaceVariable]
        Variables in this section.
    is_constant : bool
        Whether this is a constant section.
    """

    section_type: str
    variables: list[InterfaceVariable] = field(default_factory=list)
    is_constant: bool = False


@dataclass
class UDTField:
    """A UDT field with resolved documentation.

    Attributes
    ----------
    name : str
        Field name.
    data_type : str
        Data type string.
    description : str
        Resolved description from MLC.
    """

    name: str
    data_type: str
    description: str = ""


@dataclass
class ExtractedInterface:
    """Complete extracted interface.

    Attributes
    ----------
    block_name : str
        Name of the block.
    block_type : str
        Type of block (FUNCTION_BLOCK, FUNCTION, TYPE).
    return_type : str | None
        Return type for functions.
    sections : list[InterfaceSection]
        All interface sections.
    udt_fields : list[UDTField]
        Fields for user data types.
    """

    block_name: str = ""
    block_type: str = ""
    return_type: str | None = None
    sections: list[InterfaceSection] = field(default_factory=list)
    udt_fields: list[UDTField] = field(default_factory=list)

    @property
    def inputs(self) -> list[InterfaceVariable]:
        """Get input variables."""
        for section in self.sections:
            if section.section_type == "VAR_INPUT":
                return section.variables
        return []

    @property
    def outputs(self) -> list[InterfaceVariable]:
        """Get output variables."""
        for section in self.sections:
            if section.section_type == "VAR_OUTPUT":
                return section.variables
        return []

    @property
    def in_outs(self) -> list[InterfaceVariable]:
        """Get in-out variables."""
        for section in self.sections:
            if section.section_type == "VAR_IN_OUT":
                return section.variables
        return []

    @property
    def static_vars(self) -> list[InterfaceVariable]:
        """Get static variables."""
        for section in self.sections:
            if section.section_type == "VAR":
                return section.variables
        return []

    @property
    def temp_vars(self) -> list[InterfaceVariable]:
        """Get temporary variables."""
        for section in self.sections:
            if section.section_type == "VAR_TEMP":
                return section.variables
        return []

    @property
    def constants(self) -> list[InterfaceVariable]:
        """Get constants."""
        for section in self.sections:
            if section.section_type == "VAR_CONSTANT":
                return section.variables
        return []


class InterfaceExtractor:
    """Extracts the block interface with resolved MLC comments.

    Parameters
    ----------
    block : Block
        The parsed SCL block.
    resource_file : ResourceFile | None
        Optional .s7res file for MLC resolution.

    Examples
    --------
    >>> extractor = InterfaceExtractor(block, resource_file)
    >>> interface = extractor.extract()
    >>> for var in interface.inputs:
    ...     print(f"{var.name}: {var.description}")
    """

    def __init__(self, block: Block, resource_file: ResourceFile | None = None) -> None:
        """Initialize the extractor.

        Parameters
        ----------
        block : Block
            The parsed SCL block.
        resource_file : ResourceFile | None
            Optional resource file for MLC resolution.
        """
        self.block = block
        self.resource_file = resource_file or block.resource_file

    def extract(self) -> ExtractedInterface:
        """Extract the complete interface.

        Returns
        -------
        ExtractedInterface
            The extracted interface with resolved comments.
        """
        result = ExtractedInterface(
            block_name=self.block.name,
            block_type=self.block.block_type,
            return_type=self.block.return_type,
        )

        # Extract variable sections
        for section in self.block.variable_sections:
            result.sections.append(self._extract_section(section))

        # Extract UDT fields if this is a TYPE block
        if self.block.user_data_type:
            result.udt_fields = self._extract_udt_fields(self.block.user_data_type)

        return result

    def _extract_section(self, section: VariableSection) -> InterfaceSection:
        """Extract a variable section.

        Parameters
        ----------
        section : VariableSection
            The section to extract.

        Returns
        -------
        InterfaceSection
            The extracted section.
        """
        result = InterfaceSection(
            section_type=section.section_type,
            is_constant=section.is_constant,
        )

        for var in section.variables:
            result.variables.append(self._extract_variable(var))

        return result

    def _extract_variable(self, var: VariableDeclaration) -> InterfaceVariable:
        """Extract a variable with resolved MLC comment.

        Parameters
        ----------
        var : VariableDeclaration
            The variable to extract.

        Returns
        -------
        InterfaceVariable
            The extracted variable.
        """
        # Resolve MLC comment
        description = var.comment
        if var.attributes.mlc_id and self.resource_file:
            mlc_text = self.resource_file.get_text(var.attributes.mlc_id)
            if mlc_text:
                description = mlc_text

        # Parse access modifier
        access = ""
        if var.attributes.access:
            access = self._parse_access(var.attributes.access)

        # Parse visibility
        visibility = ""
        if var.attributes.visibility:
            visibility = self._parse_visibility(var.attributes.visibility)

        # Check if library type
        is_library_type = var.data_type.startswith("_.")

        return InterfaceVariable(
            name=var.name,
            data_type=var.data_type,
            default_value=var.default_value,
            description=description,
            access=access,
            visibility=visibility,
            is_library_type=is_library_type,
        )

    def _extract_udt_fields(self, udt: UserDataType) -> list[UDTField]:
        """Extract UDT fields with resolved MLC comments.

        Parameters
        ----------
        udt : UserDataType
            The UDT to extract fields from.

        Returns
        -------
        list[UDTField]
            The extracted fields.
        """
        fields = []
        for udt_field in udt.fields:
            description = udt_field.comment
            if udt_field.mlc_id and self.resource_file:
                mlc_text = self.resource_file.get_text(udt_field.mlc_id)
                if mlc_text:
                    description = mlc_text

            fields.append(
                UDTField(
                    name=udt_field.name,
                    data_type=udt_field.data_type,
                    description=description,
                )
            )
        return fields

    def _parse_access(self, access_str: str) -> str:
        """Parse the access modifier string.

        Parameters
        ----------
        access_str : str
            Raw access string like "ReadOnly := External".

        Returns
        -------
        str
            Simplified access modifier.
        """
        if "ReadOnly" in access_str:
            return "ReadOnly"
        if "ReadWrite" in access_str:
            return "ReadWrite"
        if "WriteOnly" in access_str:
            return "WriteOnly"
        return access_str

    def _parse_visibility(self, visibility_str: str) -> str:
        """Parse the visibility modifier string.

        Parameters
        ----------
        visibility_str : str
            Raw visibility string like "Hidden := External".

        Returns
        -------
        str
            Simplified visibility modifier.
        """
        if "Hidden" in visibility_str:
            return "Hidden"
        if "Visible" in visibility_str:
            return "Visible"
        return visibility_str


def extract_interface(block: Block, resource_file: ResourceFile | None = None) -> ExtractedInterface:
    """Convenience function to extract interface from a block.

    Parameters
    ----------
    block : Block
        The parsed SCL block.
    resource_file : ResourceFile | None
        Optional resource file for MLC resolution.

    Returns
    -------
    ExtractedInterface
        The extracted interface.
    """
    extractor = InterfaceExtractor(block, resource_file)
    return extractor.extract()
