"""Tests for database storage module."""

from plc_iol.core.database import (
    CSV_FIELDS,
    DatabaseManager,
    export_schema,
)
from plc_iol.core.models import IODatabase, IOPoint


class TestDatabaseManager:
    """Tests for DatabaseManager class."""

    def test_init(self, temp_dir):
        manager = DatabaseManager(temp_dir / ".iol")
        assert manager.database_path == temp_dir / ".iol"
        assert manager.io_points_file == temp_dir / ".iol" / "io_points.csv"

    def test_from_config(self, sample_config):
        manager = DatabaseManager.from_config(sample_config)
        assert manager.database_path == sample_config.database_path

    def test_ensure_directory(self, temp_dir):
        manager = DatabaseManager(temp_dir / "new_db")
        assert not manager.database_path.exists()
        manager.ensure_directory()
        assert manager.database_path.exists()

    def test_exists(self, temp_dir):
        manager = DatabaseManager(temp_dir / ".iol")
        assert manager.exists() is False

        manager.ensure_directory()
        manager.io_points_file.write_text("")
        assert manager.exists() is True

    def test_save_and_load(self, temp_dir, sample_database):
        manager = DatabaseManager(temp_dir / ".iol")
        manager.save(sample_database)

        loaded = manager.load()
        assert len(loaded) == len(sample_database)
        assert "DI_STATION_PUMP_START" in loaded

    def test_load_nonexistent(self, temp_dir):
        manager = DatabaseManager(temp_dir / ".iol")
        db = manager.load()
        assert len(db) == 0

    def test_backup(self, temp_dir, sample_database):
        manager = DatabaseManager(temp_dir / ".iol")
        manager.save(sample_database)

        backup_path = manager.backup()
        assert backup_path is not None
        assert backup_path.exists()
        assert "backups" in str(backup_path)

    def test_backup_no_database(self, temp_dir):
        manager = DatabaseManager(temp_dir / ".iol")
        backup_path = manager.backup()
        assert backup_path is None

    def test_add_point(self, temp_dir, sample_point):
        manager = DatabaseManager(temp_dir / ".iol")
        result = manager.add_point(sample_point)
        assert result is True

        loaded = manager.load()
        assert sample_point.mnemonic in loaded

    def test_add_point_duplicate(self, temp_dir, sample_point):
        manager = DatabaseManager(temp_dir / ".iol")
        manager.add_point(sample_point)

        # Try to add duplicate
        result = manager.add_point(sample_point, overwrite=False)
        assert result is False

    def test_update_point(self, temp_dir, sample_point):
        manager = DatabaseManager(temp_dir / ".iol")
        manager.add_point(sample_point)

        updated = manager.update_point(
            sample_point.mnemonic,
            signal_name="UPDATED NAME",
        )
        assert updated is not None
        assert updated.signal_name == "UPDATED NAME"

        # Verify persistence
        loaded = manager.load()
        assert loaded.get(sample_point.mnemonic).signal_name == "UPDATED NAME"

    def test_delete_point(self, temp_dir, sample_point):
        manager = DatabaseManager(temp_dir / ".iol")
        manager.add_point(sample_point)

        result = manager.delete_point(sample_point.mnemonic)
        assert result is True

        loaded = manager.load()
        assert sample_point.mnemonic not in loaded

    def test_delete_nonexistent(self, temp_dir):
        manager = DatabaseManager(temp_dir / ".iol")
        result = manager.delete_point("NONEXISTENT")
        assert result is False

    def test_get_point(self, temp_dir, sample_point):
        manager = DatabaseManager(temp_dir / ".iol")
        manager.add_point(sample_point)

        point = manager.get_point(sample_point.mnemonic)
        assert point is not None
        assert point.signal_name == sample_point.signal_name

    def test_merge(self, temp_dir, sample_database):
        manager = DatabaseManager(temp_dir / ".iol")
        manager.save(sample_database)

        other = IODatabase()
        other.add(IOPoint(mnemonic="NEW_POINT", signal_name="New"))

        stats = manager.merge(other)
        assert stats["added"] == 1

        loaded = manager.load()
        assert "NEW_POINT" in loaded

    def test_clear(self, temp_dir, sample_database):
        manager = DatabaseManager(temp_dir / ".iol")
        manager.save(sample_database)

        manager.clear()
        loaded = manager.load()
        assert len(loaded) == 0

    def test_get_statistics(self, temp_dir, sample_database):
        manager = DatabaseManager(temp_dir / ".iol")
        manager.save(sample_database)

        stats = manager.get_statistics()
        assert stats["total"] == len(sample_database)
        assert stats["file_exists"] is True
        assert "database_path" in stats


class TestExportSchema:
    """Tests for schema export."""

    def test_export_schema(self, temp_dir):
        output_path = temp_dir / "schema.csv"
        export_schema(output_path)

        assert output_path.exists()
        content = output_path.read_text()
        assert "mnemonic" in content
        assert "signal_name" in content


class TestCSVFields:
    """Tests for CSV field definitions."""

    def test_csv_fields_complete(self):
        expected_fields = [
            "id",
            "mnemonic",
            "signal_name",
            "customer_tag",
            "functional_group",
            "io_category",
            "physical_type",
            "data_type",
            "hw_address",
            "plc_address",
            "is_safety",
            "circuit_ref",
            "control_unit",
            "control_light",
            "is_intrinsically_safe",
            "xml_source",
        ]
        assert CSV_FIELDS == expected_fields
