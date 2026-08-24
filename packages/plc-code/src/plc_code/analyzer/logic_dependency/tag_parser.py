"""Parser for PLC tag XML files.

This module parses TIA Portal PLC tag table XML files to extract
I/O tags with their addresses, data types, and comments.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

# Tag category definitions
TAG_PREFIXES = {
    "DO_": {"category": "DO", "direction": "output", "description": "Digital Output"},
    "SDO_": {"category": "SDO", "direction": "output", "description": "Safety Digital Output"},
    "DI_": {"category": "DI", "direction": "input", "description": "Digital Input"},
    "SDI_": {"category": "SDI", "direction": "input", "description": "Safety Digital Input"},
    "AI_": {"category": "AI", "direction": "input", "description": "Analog Input"},
    "SAI_": {"category": "SAI", "direction": "input", "description": "Safety Analog Input"},
    "AO_": {"category": "AO", "direction": "output", "description": "Analog Output"},
    "SAO_": {"category": "SAO", "direction": "output", "description": "Safety Analog Output"},
}


@dataclass
class IOTag:
    """Represents a physical I/O tag from the PLC tag table."""

    name: str
    address: str
    data_type: str
    comment: str
    category: str
    direction: str
    source_file: str = ""

    @property
    def is_output(self) -> bool:
        """Check if this is an output tag."""
        return self.direction == "output"

    @property
    def is_input(self) -> bool:
        """Check if this is an input tag."""
        return self.direction == "input"

    @property
    def is_digital(self) -> bool:
        """Check if this is a digital tag."""
        return self.category in ("DI", "SDI", "DO", "SDO")

    @property
    def is_analog(self) -> bool:
        """Check if this is an analog tag."""
        return self.category in ("AI", "SAI")

    @property
    def is_safety(self) -> bool:
        """Check if this is a safety-related tag."""
        return self.category.startswith("S")


@dataclass
class TagCollection:
    """Collection of I/O tags organized by category."""

    tags: list[IOTag] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._by_name: dict[str, IOTag] = {}
        self._by_category: dict[str, list[IOTag]] = {}
        for tag in self.tags:
            self._index_tag(tag)

    def _index_tag(self, tag: IOTag) -> None:
        """Add a tag to the internal indices."""
        self._by_name[tag.name] = tag
        if tag.category not in self._by_category:
            self._by_category[tag.category] = []
        self._by_category[tag.category].append(tag)

    def add(self, tag: IOTag) -> None:
        """Add a tag to the collection."""
        self.tags.append(tag)
        self._index_tag(tag)

    def get(self, name: str) -> IOTag | None:
        """Get a tag by name."""
        return self._by_name.get(name)

    def by_category(self, category: str) -> list[IOTag]:
        """Get all tags in a category."""
        return self._by_category.get(category, [])

    def outputs(self) -> list[IOTag]:
        """Get all output tags."""
        return [t for t in self.tags if t.is_output]

    def inputs(self) -> list[IOTag]:
        """Get all input tags."""
        return [t for t in self.tags if t.is_input]

    def all_tag_names(self) -> set[str]:
        """Get a set of all tag names."""
        return set(self._by_name.keys())

    def categories(self) -> dict[str, int]:
        """Get category counts."""
        return {cat: len(tags) for cat, tags in self._by_category.items()}


def _get_tag_category(name: str) -> tuple[str, str] | None:
    """Determine the category and direction of a tag by its name prefix.

    Returns tuple of (category, direction) or None if not an I/O tag.
    """
    for prefix, info in TAG_PREFIXES.items():
        if name.startswith(prefix):
            return info["category"], info["direction"]
    return None


def _extract_comment(tag_element: ET.Element) -> str:
    """Extract the English comment from a tag element."""
    # Look for MultilingualText with CompositionName="Comment"
    for ml_text in tag_element.iter("MultilingualText"):
        comp_name = ml_text.get("CompositionName", "")
        if comp_name == "Comment":
            # Find the English text item
            for item in ml_text.iter("MultilingualTextItem"):
                for attr in item.findall("AttributeList"):
                    culture_elem = attr.find("Culture")
                    text_elem = attr.find("Text")
                    if culture_elem is not None and text_elem is not None:
                        if culture_elem.text == "en-US":
                            return text_elem.text or ""
    return ""


def parse_tag_file(file_path: Path) -> list[IOTag]:
    """Parse a single PLC tag XML file and extract I/O tags.

    Parameters
    ----------
    file_path : Path
        Path to the XML tag file.

    Returns
    -------
    list[IOTag]
        List of parsed I/O tags.
    """
    tags: list[IOTag] = []

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
    except ET.ParseError as e:
        print(f"Warning: Failed to parse {file_path}: {e}")
        return tags

    # Find all PlcTag elements
    for tag_elem in root.iter("SW.Tags.PlcTag"):
        attr_list = tag_elem.find("AttributeList")
        if attr_list is None:
            continue

        name_elem = attr_list.find("Name")
        if name_elem is None or name_elem.text is None:
            continue

        name = name_elem.text

        # Check if this is an I/O tag we care about
        category_info = _get_tag_category(name)
        if category_info is None:
            continue

        category, direction = category_info

        # Extract other attributes
        address_elem = attr_list.find("LogicalAddress")
        address = address_elem.text if address_elem is not None and address_elem.text else ""

        dtype_elem = attr_list.find("DataTypeName")
        data_type = dtype_elem.text if dtype_elem is not None and dtype_elem.text else "Unknown"

        comment = _extract_comment(tag_elem)

        tags.append(
            IOTag(
                name=name,
                address=address,
                data_type=data_type,
                comment=comment,
                category=category,
                direction=direction,
                source_file=str(file_path.name),
            )
        )

    return tags


def parse_tag_directory(tag_dir: Path) -> TagCollection:
    """Parse all PLC tag XML files in a directory.

    Parameters
    ----------
    tag_dir : Path
        Path to the directory containing tag XML files.

    Returns
    -------
    TagCollection
        Collection of all parsed I/O tags.
    """
    collection = TagCollection()

    if not tag_dir.exists():
        print(f"Warning: Tag directory does not exist: {tag_dir}")
        return collection

    for xml_file in tag_dir.glob("*.xml"):
        tags = parse_tag_file(xml_file)
        for tag in tags:
            collection.add(tag)

    return collection


def find_tag_directory(project_path: Path) -> Path | None:
    """Find the PLC tags directory in a project.

    Searches for common patterns like 'PLC tags', 'Tags', etc.

    Parameters
    ----------
    project_path : Path
        Root path of the PLC project.

    Returns
    -------
    Path | None
        Path to the tag directory, or None if not found.
    """
    # Common patterns for tag directories
    patterns = [
        "PLC tags",
        "PLC Tags",
        "Tags",
        "tags",
        "**/PLC tags",
        "**/Tags",
    ]

    for pattern in patterns:
        if "*" in pattern:
            matches = list(project_path.glob(pattern))
            if matches:
                return matches[0]
        else:
            candidate = project_path / pattern
            if candidate.is_dir():
                return candidate

    return None
