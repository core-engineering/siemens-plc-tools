"""XML exporter for Siemens S7-1500 PLC tag files."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from plc_iol.core.models import IODatabase, IOPoint

if TYPE_CHECKING:
    from plc_iol.core.config import ProjectConfig


@dataclass
class XMLExportResult:
    """Result of XML export operation."""

    success: bool
    files_created: list[Path]
    points_exported: int
    errors: list[str]


class XMLExporter:
    """
    Exports IO points to Siemens S7-1500 XML tag format.

    Creates XML files compatible with TIA Portal import.
    """

    # XML declaration and namespaces
    XML_DECLARATION = '<?xml version="1.0" encoding="utf-8"?>'
    ENGINEERING_VERSION = "V21"

    def __init__(self, config: ProjectConfig | None = None):
        """
        Initialize XML exporter.

        Args:
            config: Optional project configuration
        """
        self.config = config
        self.errors: list[str] = []

    def export_database(
        self,
        db: IODatabase,
        output_dir: Path,
        group_by: str = "functional_group",
    ) -> XMLExportResult:
        """
        Export database to XML files.

        Args:
            db: Database to export
            output_dir: Directory to write XML files
            group_by: How to group points into files
                      ("functional_group", "xml_source", or "single")

        Returns:
            XMLExportResult with export statistics
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        files_created = []
        points_exported = 0

        if group_by == "single":
            # Export all to a single file
            output_path = output_dir / "tags.xml"
            count = self._export_points(list(db), output_path, "Tags")
            if count > 0:
                files_created.append(output_path)
                points_exported += count
        else:
            # Group by attribute
            groups: dict[str, list[IOPoint]] = {}
            for point in db:
                key = getattr(point, group_by, None) or "Unknown"
                if key not in groups:
                    groups[key] = []
                groups[key].append(point)

            for group_name, points in groups.items():
                # Create filename from group name
                filename = self._make_filename(group_name)
                output_path = output_dir / filename
                count = self._export_points(points, output_path, group_name)
                if count > 0:
                    files_created.append(output_path)
                    points_exported += count

        return XMLExportResult(
            success=len(self.errors) == 0,
            files_created=files_created,
            points_exported=points_exported,
            errors=self.errors.copy(),
        )

    def export_to_config(self, db: IODatabase) -> XMLExportResult:
        """
        Export database using project configuration paths.

        Args:
            db: Database to export

        Returns:
            XMLExportResult with export statistics
        """
        if self.config is None:
            return XMLExportResult(
                success=False,
                files_created=[],
                points_exported=0,
                errors=["No project configuration provided"],
            )

        return self.export_database(
            db,
            self.config.tags_path,
            group_by="functional_group",
        )

    def _export_points(
        self,
        points: list[IOPoint],
        output_path: Path,
        table_name: str,
    ) -> int:
        """
        Export points to a single XML file.

        Args:
            points: List of points to export
            output_path: Path to write XML file
            table_name: Name for the tag table

        Returns:
            Number of points exported
        """
        if not points:
            return 0

        # Create root element
        root = ET.Element("Document")

        # Add engineering version
        engineering = ET.SubElement(root, "Engineering")
        engineering.set("version", self.ENGINEERING_VERSION)

        # Create tag table
        tag_table = ET.SubElement(root, "SW.Tags.PlcTagTable")
        tag_table.set("ID", "0")

        # Add table attributes
        attr_list = ET.SubElement(tag_table, "AttributeList")
        name_elem = ET.SubElement(attr_list, "Name")
        name_elem.text = table_name

        # Add object list with tags
        obj_list = ET.SubElement(tag_table, "ObjectList")

        tag_id = 1
        for point in sorted(points, key=lambda p: p.mnemonic):
            self._add_tag_element(obj_list, point, tag_id)
            tag_id += 3  # Each tag uses 3 IDs (tag, comment, comment item)

        # Write to file
        try:
            tree = ET.ElementTree(root)
            ET.indent(tree, space="  ")

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(self.XML_DECLARATION + "\n")
                tree.write(f, encoding="unicode", xml_declaration=False)

            return len(points)
        except Exception as e:
            self.errors.append(f"Failed to write {output_path}: {e}")
            return 0

    def _add_tag_element(
        self,
        parent: ET.Element,
        point: IOPoint,
        tag_id: int,
    ) -> None:
        """Add a single tag element to the parent."""
        # Create tag element
        tag = ET.SubElement(parent, "SW.Tags.PlcTag")
        tag.set("ID", str(tag_id))
        tag.set("CompositionName", "Tags")

        # Add attribute list
        attr_list = ET.SubElement(tag, "AttributeList")

        # Data type
        data_type = ET.SubElement(attr_list, "DataTypeName")
        data_type.text = point.data_type.value if point.data_type else "Bool"

        # External accessible
        ext_access = ET.SubElement(attr_list, "ExternalAccessible")
        ext_access.text = "false"

        # Logical address
        if point.plc_address:
            address = ET.SubElement(attr_list, "LogicalAddress")
            address.text = point.plc_address

        # Name (mnemonic)
        name = ET.SubElement(attr_list, "Name")
        name.text = point.mnemonic

        # Add comment if circuit_ref exists
        if point.circuit_ref:
            obj_list = ET.SubElement(tag, "ObjectList")
            ml_text = ET.SubElement(obj_list, "MultilingualText")
            ml_text.set("ID", str(tag_id + 1))
            ml_text.set("CompositionName", "Comment")

            ml_obj_list = ET.SubElement(ml_text, "ObjectList")
            ml_item = ET.SubElement(ml_obj_list, "MultilingualTextItem")
            ml_item.set("ID", str(tag_id + 2))
            ml_item.set("CompositionName", "Items")

            ml_attr_list = ET.SubElement(ml_item, "AttributeList")
            culture = ET.SubElement(ml_attr_list, "Culture")
            culture.text = "en-US"
            text = ET.SubElement(ml_attr_list, "Text")
            text.text = point.circuit_ref

    def _make_filename(self, name: str) -> str:
        """Create a valid filename from a group name."""
        # Remove invalid characters
        valid_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        filename = "".join(c if c in valid_chars else "_" for c in name)
        return f"{filename}.xml"


def export_xml_tags(
    db: IODatabase,
    output_path: Path | str,
    table_name: str = "Tags",
) -> Path:
    """
    Convenience function to export database to a single XML file.

    Args:
        db: Database to export
        output_path: Path for output XML file
        table_name: Name for the tag table

    Returns:
        Path to created file
    """
    output_path = Path(output_path)
    exporter = XMLExporter()
    exporter._export_points(list(db), output_path, table_name)
    return output_path
