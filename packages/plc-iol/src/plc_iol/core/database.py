"""CSV-based database storage for IO points."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from plc_iol.core.models import IODatabase, IOPoint

if TYPE_CHECKING:
    from plc_iol.core.config import ProjectConfig


# CSV field names (column headers)
CSV_FIELDS = [
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


class DatabaseError(Exception):
    """Raised when database operations fail."""

    pass


class DatabaseManager:
    """
    Manages CSV-based storage for IO points.

    The database uses a simple CSV format that is version-control friendly.
    Each project has its own database stored in the configured database path.
    """

    def __init__(self, database_path: Path):
        """
        Initialize database manager.

        Args:
            database_path: Path to the database directory
        """
        self.database_path = Path(database_path)
        self.io_points_file = self.database_path / "io_points.csv"
        self.metadata_file = self.database_path / "metadata.yaml"

    @classmethod
    def from_config(cls, config: ProjectConfig) -> DatabaseManager:
        """Create DatabaseManager from project configuration."""
        return cls(config.database_path)

    def ensure_directory(self) -> None:
        """Ensure database directory exists."""
        self.database_path.mkdir(parents=True, exist_ok=True)

    def exists(self) -> bool:
        """Check if database file exists."""
        return self.io_points_file.exists()

    def load(self) -> IODatabase:
        """
        Load database from CSV file.

        Returns:
            IODatabase instance with all points

        Raises:
            DatabaseError: If file cannot be read
        """
        db = IODatabase()

        if not self.io_points_file.exists():
            return db

        try:
            with open(self.io_points_file, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        point = IOPoint.from_dict(row)
                        db.add(point, overwrite=True)
                    except Exception as e:
                        # Log error but continue loading
                        print(f"Warning: Could not load row {row.get('mnemonic', '?')}: {e}")
        except Exception as e:
            raise DatabaseError(f"Failed to load database: {e}") from e

        return db

    def save(self, db: IODatabase) -> None:
        """
        Save database to CSV file.

        Args:
            db: IODatabase to save

        Raises:
            DatabaseError: If file cannot be written
        """
        self.ensure_directory()

        try:
            with open(self.io_points_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                writer.writeheader()

                # Sort by mnemonic for consistent output
                for point in sorted(db.points.values(), key=lambda p: p.mnemonic):
                    writer.writerow(point.to_dict())
        except Exception as e:
            raise DatabaseError(f"Failed to save database: {e}") from e

    def backup(self) -> Path | None:
        """
        Create a backup of the current database.

        Returns:
            Path to backup file, or None if no database exists
        """
        if not self.io_points_file.exists():
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = self.database_path / "backups"
        backup_dir.mkdir(exist_ok=True)

        backup_path = backup_dir / f"io_points_{timestamp}.csv"
        backup_path.write_text(self.io_points_file.read_text())

        return backup_path

    def add_point(self, point: IOPoint, overwrite: bool = False) -> bool:
        """
        Add a single point to the database.

        Args:
            point: IOPoint to add
            overwrite: Whether to overwrite existing point

        Returns:
            True if added, False if already exists and overwrite=False
        """
        db = self.load()
        result = db.add(point, overwrite=overwrite)
        if result or overwrite:
            self.save(db)
        return result

    def update_point(self, mnemonic: str, **kwargs: Any) -> IOPoint | None:
        """
        Update fields of an existing point.

        Args:
            mnemonic: Mnemonic of point to update
            **kwargs: Fields to update

        Returns:
            Updated IOPoint or None if not found
        """
        db = self.load()
        point = db.update(mnemonic, **kwargs)
        if point:
            self.save(db)
        return point

    def delete_point(self, mnemonic: str) -> bool:
        """
        Delete a point from the database.

        Args:
            mnemonic: Mnemonic of point to delete

        Returns:
            True if deleted, False if not found
        """
        db = self.load()
        result = db.remove(mnemonic)
        if result:
            self.save(db)
        return result

    def get_point(self, mnemonic: str) -> IOPoint | None:
        """
        Get a single point by mnemonic.

        Args:
            mnemonic: Mnemonic to look up

        Returns:
            IOPoint or None if not found
        """
        db = self.load()
        return db.get(mnemonic)

    def merge(self, other_db: IODatabase, overwrite: bool = False) -> dict:
        """
        Merge another database into this one.

        Args:
            other_db: Database to merge from
            overwrite: Whether to overwrite existing points

        Returns:
            Statistics about the merge operation
        """
        db = self.load()
        stats = db.merge(other_db, overwrite=overwrite)
        self.save(db)
        return stats

    def clear(self) -> None:
        """Clear all points from the database."""
        self.save(IODatabase())

    def get_statistics(self) -> dict:
        """Get database statistics."""
        db = self.load()
        stats = db.get_statistics()
        stats["database_path"] = str(self.database_path)
        stats["file_exists"] = self.io_points_file.exists()
        return stats


def export_schema(output_path: Path) -> None:
    """
    Export the database schema as a CSV file.

    Args:
        output_path: Path to write schema file
    """
    schema_data = [
        ("id", "string", "Yes", "Unique identifier (8-char UUID)"),
        ("mnemonic", "string", "Yes", "PLC tag name (e.g., DI_LCP_PUMP_START)"),
        ("signal_name", "string", "Yes", "Human-readable description"),
        ("customer_tag", "string", "No", "Customer's tag ID (e.g., 021-HS-6001)"),
        ("functional_group", "enum", "No", "COMMON, GROUP1, GROUP2, etc."),
        ("io_category", "enum", "No", "DI, DO, AI, AO, SDI, SDO"),
        ("physical_type", "string", "No", "Push button, Switch, Transmitter, etc."),
        ("data_type", "string", "No", "Bool, Int, Real"),
        ("hw_address", "string", "No", "IOL format (E, A, PEW, PAW)"),
        ("plc_address", "string", "No", "S7 format (%I, %Q, %IW, %QW)"),
        ("is_safety", "boolean", "No", "Safety-related flag"),
        ("circuit_ref", "string", "No", "Electrical diagram reference"),
        ("control_unit", "string", "No", "Control panel unit assignment"),
        ("control_light", "string", "No", "Control panel light assignment"),
        ("is_intrinsically_safe", "boolean", "No", "Intrinsic safety flag"),
        ("xml_source", "string", "No", "Source XML filename"),
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["field", "type", "required", "description"])
        writer.writerows(schema_data)
