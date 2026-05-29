"""Header and description extraction from SCL blocks.

This module provides extraction of structured documentation from the
"Block info header" and "Description" REGION blocks following the
Code2Docu convention.

For LADDER blocks, the header information is stored in .s7res resource files
as MultiLingualText entries.
"""

import re
from dataclasses import dataclass, field

from plc_code.parser.models import Block, ChangeLogEntry, HeaderInfo, Region, ResourceFile


@dataclass
class ExtractedHeader:
    """Complete extracted header information.

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
        Parsed change log entries.
    description : str
        Content from the Description REGION.
    raw_header : str
        Raw content of the Block info header REGION.
    """

    title: str = ""
    comment: str = ""
    library: str = ""
    author: str = ""
    copyright: str = ""
    changelog: list[ChangeLogEntry] = field(default_factory=list)
    description: str = ""
    raw_header: str = ""


class HeaderExtractor:
    """Extracts structured documentation from SCL block regions.

    This extractor parses the "Block info header" and "Description" REGION
    blocks following the Code2Docu plugin convention.

    For LADDER blocks, header info is extracted from .s7res resource files.

    Parameters
    ----------
    block : Block
        The parsed SCL block to extract from.
    resource : ResourceFile | None
        Optional resource file with multilingual texts (for LADDER blocks).

    Examples
    --------
    >>> extractor = HeaderExtractor(block)
    >>> header = extractor.extract()
    >>> print(header.title)
    "MyFunctionBlock"
    """

    # Pattern for key-value lines like "// Title:      Value here"
    # Also handles compound keys like "Comment/Function" and "Library/Family"
    KEY_VALUE_PATTERN = re.compile(r"//\s*([\w/]+):\s*(.*)")

    # Pattern for key-value in resource files (no // prefix)
    # e.g., " Title:            BlockName"
    # Captures value up to dashes (which are separator chars in some formats)
    KEY_VALUE_PATTERN_RESOURCE = re.compile(r"^\s*([\w/]+):\s*([^-]+)", re.MULTILINE)

    # Pattern for changelog table rows - supports both formats:
    # - With leading pipe: // | v1.0.0 | Date | Author | Changes |
    # - Without leading pipe: // v1.0.0 | Date | Author | Changes
    CHANGELOG_ROW_PATTERN_PIPE = re.compile(r"//\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)")
    CHANGELOG_ROW_PATTERN_NOPIPE = re.compile(r"//\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*(.+)")

    # Pattern for changelog in resource files (no // prefix)
    CHANGELOG_ROW_PATTERN_RESOURCE = re.compile(r"^\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*(.+)$")

    # Pattern for changelog header separator (lines with dashes and plus signs like //----+----)
    CHANGELOG_SEPARATOR = re.compile(r"//\s*[-+]+$")

    # Pattern for separator in resource files (no // prefix)
    CHANGELOG_SEPARATOR_RESOURCE = re.compile(r"^\s*[-+|]+\s*$")

    # Pattern for copyright line like "// Company / (c)Copyright 2025"
    COPYRIGHT_PATTERN = re.compile(r"//\s*(.+?)\s*/\s*\(?c\)?[Cc]opyright\s*(\d+)")

    # Pattern for copyright in resource files (no // prefix)
    COPYRIGHT_PATTERN_RESOURCE = re.compile(r"^\s*(.+?)\s*/\s*\(?c\)?[Cc]opyright\s*(\d+)")

    def __init__(self, block: Block, resource: ResourceFile | None = None) -> None:
        """Initialize the extractor with a block.

        Parameters
        ----------
        block : Block
            The parsed SCL block to extract from.
        resource : ResourceFile | None
            Optional resource file with multilingual texts.
        """
        self.block = block
        self.resource = resource

    def extract(self) -> ExtractedHeader:
        """Extract header and description information.

        First tries to extract from SCL REGION blocks. If no header info found,
        falls back to extracting from the resource file (for LADDER blocks).

        Returns
        -------
        ExtractedHeader
            The extracted header information.
        """
        result = ExtractedHeader()

        # Find the Block info header REGION
        header_region = self._find_region("Block info header")
        if header_region:
            result.raw_header = header_region.content
            self._parse_header_content(header_region.content, result)

        # Find the Description REGION
        desc_region = self._find_region("Description")
        if desc_region:
            result.description = self._clean_description(desc_region.content)

        # If no header info found in REGIONs, try resource file (for LADDER blocks)
        if not result.title and self.resource:
            self._extract_from_resource(result)

        return result

    def _extract_from_resource(self, result: ExtractedHeader) -> None:
        """Extract header info from resource file multilingual texts.

        For LADDER blocks, header info is stored in .s7res files as MLC entries.
        The pattern is:
        - A text entry with "Block info header" indicates the next entry has header content
        - A text entry with "Description" indicates the next entry has description content

        Parameters
        ----------
        result : ExtractedHeader
            The result object to populate.
        """
        if not self.resource or not self.resource.texts:
            return

        # Find the header content by looking for "Block info header" marker
        header_content = None
        description_content = None

        texts = list(self.resource.texts.values())
        for i, text in enumerate(texts):
            if text.text.lower() == "block info header" and i + 1 < len(texts):
                # Next entry should be the header content
                header_content = texts[i + 1].text
            elif text.text.lower() == "description" and i + 1 < len(texts):
                # Next entry should be the description content
                description_content = texts[i + 1].text

        if header_content:
            result.raw_header = header_content
            self._parse_resource_header_content(header_content, result)

        if description_content:
            result.description = description_content.strip()

    def _find_region(self, name: str) -> Region | None:
        """Find a REGION by name in the block's networks.

        Parameters
        ----------
        name : str
            The region name to search for.

        Returns
        -------
        Region | None
            The found region or None.
        """
        for network in self.block.networks:
            for region in network.regions:
                if region.name.lower() == name.lower():
                    return region
                # Also check nested regions
                found = self._find_nested_region(region, name)
                if found:
                    return found
        return None

    def _find_nested_region(self, region: Region, name: str) -> Region | None:
        """Recursively search for a region by name.

        Parameters
        ----------
        region : Region
            The parent region to search within.
        name : str
            The region name to search for.

        Returns
        -------
        Region | None
            The found region or None.
        """
        for nested in region.nested_regions:
            if nested.name.lower() == name.lower():
                return nested
            found = self._find_nested_region(nested, name)
            if found:
                return found
        return None

    def _parse_header_content(self, content: str, result: ExtractedHeader) -> None:
        """Parse the Block info header content.

        Parameters
        ----------
        content : str
            The raw header content.
        result : ExtractedHeader
            The result object to populate.
        """
        lines = content.split("\n")
        in_changelog = False
        changelog_entries: list[ChangeLogEntry] = []

        for line in lines:
            stripped = line.strip()

            # Check for changelog table
            if "Change log" in stripped or "Changelog" in stripped:
                in_changelog = True
                continue

            # Skip separator lines
            if self.CHANGELOG_SEPARATOR.match(stripped):
                continue

            # Parse changelog rows
            if in_changelog:
                # Try both patterns: with leading pipe and without
                match = self.CHANGELOG_ROW_PATTERN_PIPE.match(stripped)
                if not match:
                    match = self.CHANGELOG_ROW_PATTERN_NOPIPE.match(stripped)
                if match:
                    version, date, author, changes = match.groups()
                    version = version.strip()
                    date = date.strip()
                    author = author.strip()
                    changes = changes.strip()

                    # Skip header row
                    if version.lower() in ("version", "ver."):
                        continue

                    # Skip if all fields are separators or empty
                    if all(c in "-+ " for c in version):
                        continue

                    changelog_entries.append(
                        ChangeLogEntry(
                            version=version,
                            date=date,
                            author=author,
                            changes=changes,
                        )
                    )
                elif stripped and not stripped.startswith("//"):
                    # End of changelog section
                    in_changelog = False

            # Parse key-value pairs
            match = self.KEY_VALUE_PATTERN.match(stripped)
            if match:
                key = match.group(1).lower()
                value = match.group(2).strip()

                if key == "title":
                    result.title = value
                elif key in ("comment", "function", "comment/function"):
                    result.comment = value
                elif key in ("library", "family", "library/family"):
                    result.library = value
                elif key == "author":
                    result.author = value
                elif key == "copyright":
                    result.copyright = value

            # Try to extract copyright from line like "// Company / (c)Copyright 2025"
            if not result.copyright:
                copyright_match = self.COPYRIGHT_PATTERN.match(stripped)
                if copyright_match:
                    company = copyright_match.group(1).strip()
                    year = copyright_match.group(2)
                    result.copyright = f"(c) {year} {company}"

        result.changelog = changelog_entries

    def _parse_resource_header_content(self, content: str, result: ExtractedHeader) -> None:
        """Parse the Block info header content from resource file.

        Resource file content doesn't have // prefixes on lines.

        Parameters
        ----------
        content : str
            The raw header content from resource file.
        result : ExtractedHeader
            The result object to populate.
        """
        lines = content.split("\n")
        in_changelog = False
        changelog_entries: list[ChangeLogEntry] = []

        for line in lines:
            stripped = line.strip()

            # Check for changelog table
            if "Change log" in stripped or "Changelog" in stripped:
                in_changelog = True
                continue

            # Skip separator lines (lines with only dashes, pipes, plus signs)
            if self.CHANGELOG_SEPARATOR_RESOURCE.match(stripped):
                continue

            # Parse changelog rows
            if in_changelog:
                match = self.CHANGELOG_ROW_PATTERN_RESOURCE.match(stripped)
                if match:
                    version, date, author, changes = match.groups()
                    version = version.strip()
                    date = date.strip()
                    author = author.strip()
                    changes = changes.strip()

                    # Skip header row
                    if version.lower() in ("version", "ver."):
                        continue

                    # Skip if all fields are separators or empty
                    if all(c in "-+ " for c in version):
                        continue

                    changelog_entries.append(
                        ChangeLogEntry(
                            version=version,
                            date=date,
                            author=author,
                            changes=changes,
                        )
                    )

            # Parse key-value pairs (no // prefix in resource files)
            match = self.KEY_VALUE_PATTERN_RESOURCE.match(stripped)
            if match:
                key = match.group(1).lower()
                value = match.group(2).strip()

                if key == "title":
                    result.title = value
                elif key in ("comment", "function", "comment/function"):
                    result.comment = value
                elif key in ("library", "family", "library/family"):
                    result.library = value
                elif key == "author":
                    result.author = value
                elif key == "copyright":
                    result.copyright = value

            # Try to extract copyright from line like "Company / (c)Copyright 2025"
            if not result.copyright:
                copyright_match = self.COPYRIGHT_PATTERN_RESOURCE.match(stripped)
                if copyright_match:
                    company = copyright_match.group(1).strip()
                    year = copyright_match.group(2)
                    result.copyright = f"(c) {year} {company}"

        result.changelog = changelog_entries

    def _clean_description(self, content: str) -> str:
        """Clean the description content.

        Handles both single-line comments (//) and block comments (* *).
        For block comments, preserves internal whitespace and markdown formatting,
        but removes common leading whitespace (dedent).

        Parameters
        ----------
        content : str
            The raw description content.

        Returns
        -------
        str
            Cleaned description with comment markers removed.
        """
        # Check for block comment (* ... *)
        stripped_content = content.strip()
        if stripped_content.startswith("(*") and stripped_content.endswith("*)"):
            # Extract content between (* and *)
            inner = stripped_content[2:-2]

            # Custom dedent that handles TIA Portal formatting where first line
            # has no indent but subsequent lines are indented
            lines = inner.split("\n")
            if not lines:
                return ""

            # Find minimum indentation from non-empty lines (excluding first line)
            min_indent = float("inf")
            for line in lines[1:]:  # Skip first line
                if line.strip():  # Non-empty line
                    indent = len(line) - len(line.lstrip())
                    min_indent = min(min_indent, indent)

            if min_indent == float("inf"):
                min_indent = 0
            else:
                min_indent = int(min_indent)

            # Remove the common indentation from all lines
            result_lines = []
            for i, line in enumerate(lines):
                if i == 0:
                    # First line: just strip leading/trailing whitespace
                    result_lines.append(line.strip())
                elif line.strip():
                    # Non-empty lines: remove common indent
                    result_lines.append(line[min_indent:] if len(line) >= min_indent else line)
                else:
                    # Empty lines: preserve as empty
                    result_lines.append("")

            return "\n".join(result_lines).strip()

        # Handle line-by-line comments
        lines = []
        for line in content.split("\n"):
            stripped = line.strip()
            # Remove leading // comments but preserve the text
            if stripped.startswith("//"):
                text = stripped[2:].strip()
                lines.append(text)
            elif stripped:
                lines.append(stripped)

        return "\n".join(lines)


def extract_header(block: Block, resource: ResourceFile | None = None) -> ExtractedHeader:
    """Convenience function to extract header from a block.

    Parameters
    ----------
    block : Block
        The parsed SCL block.
    resource : ResourceFile | None
        Optional resource file with multilingual texts (for LADDER blocks).

    Returns
    -------
    ExtractedHeader
        The extracted header information.
    """
    extractor = HeaderExtractor(block, resource)
    return extractor.extract()


def extract_header_info(block: Block, resource: ResourceFile | None = None) -> HeaderInfo:
    """Extract header info in the parser's HeaderInfo format.

    Parameters
    ----------
    block : Block
        The parsed SCL block.
    resource : ResourceFile | None
        Optional resource file with multilingual texts (for LADDER blocks).

    Returns
    -------
    HeaderInfo
        The header information in the standard model format.
    """
    extracted = extract_header(block, resource)
    return HeaderInfo(
        title=extracted.title,
        comment=extracted.comment,
        library=extracted.library,
        author=extracted.author,
        copyright=extracted.copyright,
        changelog=extracted.changelog,
    )
