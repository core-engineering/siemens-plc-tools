"""Tests for importer modules."""

import pytest

from plc_iol.core.models import DataType
from plc_iol.importers.xml_importer import XMLImporter, import_xml_tags


class TestXMLImporter:
    """Tests for XML importer."""

    def test_import_file(self, temp_dir, sample_xml_content):
        # Create XML file
        xml_path = temp_dir / "test_tags.xml"
        xml_path.write_text(sample_xml_content)

        importer = XMLImporter()
        db = importer.import_file(xml_path)

        assert len(db) == 2
        assert "DI_STATION_TEST_INPUT" in db
        assert "AI_DRIVE_PRESSURE" in db

    def test_import_file_with_functional_group(self, temp_dir, sample_xml_content):
        xml_path = temp_dir / "test_tags.xml"
        xml_path.write_text(sample_xml_content)

        importer = XMLImporter()
        db = importer.import_file(xml_path, functional_group="COMMON")

        point = db.get("DI_STATION_TEST_INPUT")
        assert point.functional_group == "COMMON"

    def test_import_file_parses_data_types(self, temp_dir, sample_xml_content):
        xml_path = temp_dir / "test_tags.xml"
        xml_path.write_text(sample_xml_content)

        importer = XMLImporter()
        db = importer.import_file(xml_path)

        di_point = db.get("DI_STATION_TEST_INPUT")
        assert di_point.data_type == DataType.BOOL

        ai_point = db.get("AI_DRIVE_PRESSURE")
        assert ai_point.data_type == DataType.INT

    def test_import_file_parses_address(self, temp_dir, sample_xml_content):
        xml_path = temp_dir / "test_tags.xml"
        xml_path.write_text(sample_xml_content)

        importer = XMLImporter()
        db = importer.import_file(xml_path)

        point = db.get("DI_STATION_TEST_INPUT")
        assert point.plc_address == "%I1.0"

    def test_import_file_parses_comment(self, temp_dir, sample_xml_content):
        xml_path = temp_dir / "test_tags.xml"
        xml_path.write_text(sample_xml_content)

        importer = XMLImporter()
        db = importer.import_file(xml_path)

        point = db.get("DI_STATION_TEST_INPUT")
        assert point.circuit_ref == "ZSC 1-1"

    def test_import_file_stores_xml_source(self, temp_dir, sample_xml_content):
        xml_path = temp_dir / "test_tags.xml"
        xml_path.write_text(sample_xml_content)

        importer = XMLImporter()
        db = importer.import_file(xml_path)

        point = db.get("DI_STATION_TEST_INPUT")
        assert point.xml_source == "test_tags.xml"

    def test_import_nonexistent_file(self, temp_dir):
        importer = XMLImporter()
        db = importer.import_file(temp_dir / "nonexistent.xml")

        assert len(db) == 0
        assert len(importer.errors) > 0

    def test_import_invalid_xml(self, temp_dir):
        xml_path = temp_dir / "invalid.xml"
        xml_path.write_text("<invalid>xml<content")

        importer = XMLImporter()
        db = importer.import_file(xml_path)

        assert len(db) == 0
        assert len(importer.errors) > 0

    def test_import_directory(self, temp_dir, sample_xml_content):
        # Create multiple XML files
        tags_dir = temp_dir / "tags"
        tags_dir.mkdir()

        (tags_dir / "file1.xml").write_text(sample_xml_content)
        (tags_dir / "file2.xml").write_text(
            sample_xml_content.replace("DI_STATION_TEST_INPUT", "DI_STATION_TEST_INPUT_2").replace(
                "AI_DRIVE_PRESSURE", "AI_DRIVE_PRESSURE_2"
            )
        )

        importer = XMLImporter()
        db = importer.import_directory(tags_dir)

        assert len(db) == 4  # 2 per file

    def test_import_from_config(self, sample_config, sample_xml_content):
        # Create XML files in config paths
        (sample_config.tags_path / "Station.xml").write_text(sample_xml_content)

        importer = XMLImporter(config=sample_config)
        result = importer.import_from_config()

        assert result.imported_count == 2
        assert "Station.xml" in result.source_files


class TestImportXMLTagsConvenience:
    """Tests for import_xml_tags convenience function."""

    def test_import_single_file(self, temp_dir, sample_xml_content):
        xml_path = temp_dir / "test.xml"
        xml_path.write_text(sample_xml_content)

        db = import_xml_tags(xml_path)
        assert len(db) == 2

    def test_import_directory(self, temp_dir, sample_xml_content):
        tags_dir = temp_dir / "tags"
        tags_dir.mkdir()
        (tags_dir / "test.xml").write_text(sample_xml_content)

        db = import_xml_tags(tags_dir)
        assert len(db) == 2

    def test_import_nonexistent_raises(self, temp_dir):
        with pytest.raises(FileNotFoundError):
            import_xml_tags(temp_dir / "nonexistent")
