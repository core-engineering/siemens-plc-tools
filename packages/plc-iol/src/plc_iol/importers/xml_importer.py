"""XML importer for Siemens S7-1500 PLC tag files."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from plc_iol.core.models import DataType, IODatabase, IOPoint

if TYPE_CHECKING:
    from plc_iol.core.config import ProjectConfig


@dataclass
class XMLImportResult:
    """Result of XML import operation."""

    success: bool
    database: IODatabase
    imported_count: int
    skipped_count: int
    errors: list[str]
    source_files: list[str]


class XMLImporter:
    """
    Imports PLC tags from Siemens S7-1500 XML export files.

    The XML format follows the TIA Portal export structure:
    - Document root
        - SW.Tags.PlcTagTable (one per file)
            - SW.Tags.PlcTag (one per tag)
                - AttributeList: Name, DataTypeName, LogicalAddress
                - ObjectList/MultilingualText/Comment: Circuit reference
    """

    def __init__(self, config: ProjectConfig | None = None):
        """
        Initialize XML importer.

        Args:
            config: Optional project configuration
        """
        self.config = config
        self.errors: list[str] = []

    def import_file(
        self,
        file_path: Path,
        functional_group: str | None = None,
    ) -> IODatabase:
        """
        Import tags from a single XML file.

        Args:
            file_path: Path to XML file
            functional_group: Optional functional group to assign to all tags

        Returns:
            IODatabase with imported points
        """
        db = IODatabase()
        file_path = Path(file_path)

        if not file_path.exists():
            self.errors.append(f"File not found: {file_path}")
            return db

        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
        except ET.ParseError as e:
            self.errors.append(f"XML parse error in {file_path}: {e}")
            return db

        # Find all PlcTag elements
        for tag_elem in root.iter("SW.Tags.PlcTag"):
            point = self._parse_tag_element(tag_elem, file_path.name, functional_group)
            if point:
                db.add(point, overwrite=True)

        return db

    def import_directory(
        self,
        directory: Path,
        pattern: str = "*.xml",
    ) -> IODatabase:
        """
        Import all XML files from a directory.

        Args:
            directory: Path to directory containing XML files
            pattern: Glob pattern for XML files

        Returns:
            IODatabase with all imported points
        """
        db = IODatabase()
        directory = Path(directory)

        if not directory.exists():
            self.errors.append(f"Directory not found: {directory}")
            return db

        xml_files = list(directory.glob(pattern))
        if not xml_files:
            self.errors.append(f"No XML files found in {directory}")
            return db

        for xml_file in xml_files:
            # Determine functional group from filename or config
            functional_group = self._get_functional_group_for_file(xml_file)
            file_db = self.import_file(xml_file, functional_group)
            db.merge(file_db, overwrite=True)

        return db

    def import_from_config(self) -> XMLImportResult:
        """
        Import all XML files defined in project configuration.

        Returns:
            XMLImportResult with import statistics
        """
        if self.config is None:
            return XMLImportResult(
                success=False,
                database=IODatabase(),
                imported_count=0,
                skipped_count=0,
                errors=["No project configuration provided"],
                source_files=[],
            )

        db = IODatabase()
        source_files = []
        imported_count = 0
        skipped_count = 0

        for group in self.config.functional_groups:
            for xml_filename in group.xml_files:
                xml_path = self.config.tags_path / xml_filename
                if not xml_path.exists():
                    self.errors.append(f"XML file not found: {xml_path}")
                    skipped_count += 1
                    continue

                file_db = self.import_file(xml_path, group.id)
                imported_count += len(file_db)
                source_files.append(xml_filename)
                db.merge(file_db, overwrite=True)

        return XMLImportResult(
            success=len(self.errors) == 0,
            database=db,
            imported_count=imported_count,
            skipped_count=skipped_count,
            errors=self.errors.copy(),
            source_files=source_files,
        )

    def _parse_tag_element(
        self,
        tag_elem: ET.Element,
        source_file: str,
        functional_group: str | None = None,
    ) -> IOPoint | None:
        """
        Parse a single SW.Tags.PlcTag element.

        Args:
            tag_elem: XML element for the tag
            source_file: Name of the source file
            functional_group: Optional functional group

        Returns:
            IOPoint or None if parsing fails
        """
        # Get attribute list
        attr_list = tag_elem.find("AttributeList")
        if attr_list is None:
            return None

        # Extract required fields
        name_elem = attr_list.find("Name")
        if name_elem is None or not name_elem.text:
            return None
        mnemonic = name_elem.text.strip()

        # Extract optional fields
        data_type_elem = attr_list.find("DataTypeName")
        data_type = DataType.BOOL
        if data_type_elem is not None and data_type_elem.text:
            data_type = DataType.from_string(data_type_elem.text)

        address_elem = attr_list.find("LogicalAddress")
        plc_address = None
        if address_elem is not None and address_elem.text:
            plc_address = address_elem.text.strip()

        # Extract comment (circuit reference)
        circuit_ref = self._extract_comment(tag_elem)

        # Create IOPoint
        return IOPoint(
            mnemonic=mnemonic,
            signal_name=self._generate_signal_name(mnemonic),
            data_type=data_type,
            plc_address=plc_address,
            circuit_ref=circuit_ref,
            functional_group=functional_group,
            xml_source=source_file,
        )

    def _extract_comment(self, tag_elem: ET.Element) -> str | None:
        """Extract comment text from tag element."""
        # Navigate: ObjectList > MultilingualText > ObjectList > MultilingualTextItem > AttributeList > Text
        obj_list = tag_elem.find("ObjectList")
        if obj_list is None:
            return None

        ml_text = obj_list.find("MultilingualText")
        if ml_text is None:
            return None

        ml_obj_list = ml_text.find("ObjectList")
        if ml_obj_list is None:
            return None

        for item in ml_obj_list.findall("MultilingualTextItem"):
            attr_list = item.find("AttributeList")
            if attr_list is not None:
                text_elem = attr_list.find("Text")
                if text_elem is not None and text_elem.text:
                    return text_elem.text.strip()

        return None

    def _generate_signal_name(self, mnemonic: str) -> str:
        """
        Generate a human-readable signal name from mnemonic.

        Converts: DI_LCP_PUMP_START -> PUMP START
        """
        parts = mnemonic.split("_")
        # Skip IO category and location
        if len(parts) > 2:
            signal_parts = parts[2:]
        elif len(parts) > 1:
            signal_parts = parts[1:]
        else:
            signal_parts = parts

        return " ".join(signal_parts)

    def _get_functional_group_for_file(self, file_path: Path) -> str | None:
        """Determine functional group for a file based on configuration."""
        if self.config is None:
            return None

        filename = file_path.name
        for group in self.config.functional_groups:
            if filename in group.xml_files:
                return group.id

        return None


def import_xml_tags(
    path: Path | str,
    functional_group: str | None = None,
    config: ProjectConfig | None = None,
) -> IODatabase:
    """
    Convenience function to import XML tags.

    Args:
        path: Path to XML file or directory
        functional_group: Optional functional group to assign
        config: Optional project configuration

    Returns:
        IODatabase with imported points
    """
    importer = XMLImporter(config=config)
    path = Path(path)

    if path.is_file():
        return importer.import_file(path, functional_group)
    elif path.is_dir():
        return importer.import_directory(path)
    else:
        raise FileNotFoundError(f"Path not found: {path}")
