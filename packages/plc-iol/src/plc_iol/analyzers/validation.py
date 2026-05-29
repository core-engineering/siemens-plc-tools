"""Database validation and audit."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from plc_iol.core.models import IODatabase, IOPoint
from plc_iol.core.naming import NamingConvention

if TYPE_CHECKING:
    from plc_iol.core.config import ProjectConfig


class IssueSeverity(str, Enum):
    """Severity level for validation issues."""

    ERROR = "error"  # Must be fixed
    WARNING = "warning"  # Should be reviewed
    INFO = "info"  # Informational


class IssueType(str, Enum):
    """Type of validation issue."""

    DUPLICATE_MNEMONIC = "duplicate_mnemonic"
    DUPLICATE_ADDRESS = "duplicate_address"
    INVALID_MNEMONIC = "invalid_mnemonic"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    INVALID_ADDRESS_FORMAT = "invalid_address_format"
    INCONSISTENT_CATEGORY = "inconsistent_category"
    ORPHAN_POINT = "orphan_point"  # Point without functional group
    ADDRESS_CONFLICT = "address_conflict"
    INTERNAL_TAG = "internal_tag"  # Internal PLC tag (not physical I/O)
    TAGS_IOL_MISMATCH = "tags_iol_mismatch"  # Discrepancy between TAGS and IOL


# Known prefixes for internal PLC tags (not physical I/O)
INTERNAL_TAG_PREFIXES = [
    "VALUE_STATUS",
    "STATUS_",
    "INTERNAL_",
    "CALC_",
    "TEMP_",
    "FLAG_",
    "TIMER_",
    "COUNTER_",
]


def is_internal_tag(mnemonic: str) -> bool:
    """Check if a mnemonic represents an internal PLC tag (not physical I/O)."""
    upper = mnemonic.upper()
    for prefix in INTERNAL_TAG_PREFIXES:
        if upper.startswith(prefix):
            return True
    return False


def is_spare(mnemonic: str) -> bool:
    """Check if a mnemonic represents a spare I/O point."""
    return mnemonic.upper().endswith("_SPARE")


def get_io_category_from_mnemonic(mnemonic: str) -> str | None:
    """Extract I/O category prefix from mnemonic."""
    upper = mnemonic.upper()
    # Check longer prefixes first
    for prefix in ["SDI", "SDO", "SAI", "SAO", "DI", "DO", "AI", "AO"]:
        if upper.startswith(prefix + "_"):
            return prefix
    return None


@dataclass
class SpareStatistics:
    """Statistics about spare I/O points."""

    by_category: dict[str, int] = field(default_factory=dict)
    total_by_category: dict[str, int] = field(default_factory=dict)

    @property
    def total_spares(self) -> int:
        """Total number of spare points."""
        return sum(self.by_category.values())

    def get_percentage(self, category: str) -> float:
        """Get percentage of spares for a category."""
        total = self.total_by_category.get(category, 0)
        spares = self.by_category.get(category, 0)
        if total == 0:
            return 0.0
        return (spares / total) * 100

    def add_spare(self, category: str) -> None:
        """Add a spare point."""
        self.by_category[category] = self.by_category.get(category, 0) + 1

    def set_total(self, category: str, total: int) -> None:
        """Set total count for a category."""
        self.total_by_category[category] = total


@dataclass
class ValidationIssue:
    """A single validation issue."""

    issue_type: IssueType
    severity: IssueSeverity
    message: str
    mnemonic: str | None = None
    field_name: str | None = None
    suggestion: str | None = None

    def __str__(self) -> str:
        """Format issue as string."""
        prefix = f"[{self.severity.value.upper()}]"
        if self.mnemonic:
            return f"{prefix} {self.mnemonic}: {self.message}"
        return f"{prefix} {self.message}"


@dataclass
class ValidationResult:
    """Result of database validation."""

    issues: list[ValidationIssue] = field(default_factory=list)
    points_checked: int = 0
    internal_tags_count: int = 0
    spare_statistics: SpareStatistics = field(default_factory=SpareStatistics)

    @property
    def error_count(self) -> int:
        """Number of errors."""
        return sum(1 for i in self.issues if i.severity == IssueSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        """Number of warnings."""
        return sum(1 for i in self.issues if i.severity == IssueSeverity.WARNING)

    @property
    def info_count(self) -> int:
        """Number of info messages."""
        return sum(1 for i in self.issues if i.severity == IssueSeverity.INFO)

    @property
    def is_valid(self) -> bool:
        """Check if database passed validation (no errors)."""
        return self.error_count == 0

    def get_errors(self) -> list[ValidationIssue]:
        """Get all errors."""
        return [i for i in self.issues if i.severity == IssueSeverity.ERROR]

    def get_warnings(self) -> list[ValidationIssue]:
        """Get all warnings."""
        return [i for i in self.issues if i.severity == IssueSeverity.WARNING]

    def get_by_type(self, issue_type: IssueType) -> list[ValidationIssue]:
        """Get all issues of a specific type."""
        return [i for i in self.issues if i.issue_type == issue_type]

    def summary(self) -> str:
        """Get validation summary."""
        status = "PASSED" if self.is_valid else "FAILED"
        return (
            f"Validation {status}: "
            f"{self.points_checked} points checked, "
            f"{self.error_count} errors, "
            f"{self.warning_count} warnings"
        )


class DatabaseValidator:
    """
    Validates IO database for common issues.

    Checks:
    - Duplicate mnemonics
    - Duplicate addresses
    - Invalid mnemonic format
    - Missing required fields
    - Inconsistent I/O categories
    - Address format validation
    - Internal PLC tags detection
    - TAGS vs IOL consistency (optional)
    """

    def __init__(
        self,
        config: ProjectConfig | None = None,
        naming_convention: NamingConvention | None = None,
        tags_db: IODatabase | None = None,
        iol_db: IODatabase | None = None,
    ):
        """
        Initialize validator.

        Args:
            config: Optional project configuration
            naming_convention: Naming convention for validation
            tags_db: Optional TAGS database for consistency check
            iol_db: Optional IOL database for consistency check
        """
        self.config = config
        self.tags_db = tags_db
        self.iol_db = iol_db
        if naming_convention:
            self.naming = naming_convention
        elif config:
            self.naming = NamingConvention.from_config(config.naming)
        else:
            self.naming = NamingConvention()

    def validate(self, db: IODatabase) -> ValidationResult:
        """
        Validate database.

        Args:
            db: Database to validate

        Returns:
            ValidationResult with all issues found
        """
        result = ValidationResult(points_checked=len(db))

        # Check for duplicate addresses
        self._check_duplicate_addresses(db, result)

        # Validate each point
        for point in db:
            self._validate_point(point, result)

        # Check for orphan points
        self._check_orphan_points(db, result)

        # Check TAGS vs IOL consistency if both are provided
        if self.tags_db is not None and self.iol_db is not None:
            self._check_tags_iol_consistency(result)

        return result

    def _check_duplicate_addresses(
        self,
        db: IODatabase,
        result: ValidationResult,
    ) -> None:
        """Check for duplicate PLC addresses."""
        address_map: dict[str, list[str]] = {}

        for point in db:
            if point.plc_address:
                addr = point.plc_address.upper()
                if addr not in address_map:
                    address_map[addr] = []
                address_map[addr].append(point.mnemonic)

        for address, mnemonics in address_map.items():
            if len(mnemonics) > 1:
                result.issues.append(
                    ValidationIssue(
                        issue_type=IssueType.DUPLICATE_ADDRESS,
                        severity=IssueSeverity.ERROR,
                        message=f"Address {address} is used by multiple points: {', '.join(mnemonics)}",
                        field_name="plc_address",
                    )
                )

    def _validate_point(self, point: IOPoint, result: ValidationResult) -> None:
        """Validate a single point."""
        # Check if this is an internal PLC tag
        if is_internal_tag(point.mnemonic):
            result.internal_tags_count += 1
            result.issues.append(
                ValidationIssue(
                    issue_type=IssueType.INTERNAL_TAG,
                    severity=IssueSeverity.INFO,
                    message="Internal PLC tag (not physical I/O) - not in IOL",
                    mnemonic=point.mnemonic,
                )
            )
            # Skip further naming validation for internal tags
            return

        # Validate mnemonic format
        naming_result = self.naming.validate(point.mnemonic)
        for error in naming_result.errors:
            result.issues.append(
                ValidationIssue(
                    issue_type=IssueType.INVALID_MNEMONIC,
                    severity=IssueSeverity.ERROR,
                    message=error,
                    mnemonic=point.mnemonic,
                    field_name="mnemonic",
                )
            )
        for warning in naming_result.warnings:
            result.issues.append(
                ValidationIssue(
                    issue_type=IssueType.INVALID_MNEMONIC,
                    severity=IssueSeverity.WARNING,
                    message=warning,
                    mnemonic=point.mnemonic,
                    field_name="mnemonic",
                )
            )

        # Check required fields
        if not point.signal_name:
            result.issues.append(
                ValidationIssue(
                    issue_type=IssueType.MISSING_REQUIRED_FIELD,
                    severity=IssueSeverity.WARNING,
                    message="Missing signal name",
                    mnemonic=point.mnemonic,
                    field_name="signal_name",
                )
            )

        # Check I/O category consistency
        if naming_result.parsed and naming_result.parsed.io_category_enum:
            parsed_category = naming_result.parsed.io_category_enum
            if point.io_category and point.io_category != parsed_category:
                result.issues.append(
                    ValidationIssue(
                        issue_type=IssueType.INCONSISTENT_CATEGORY,
                        severity=IssueSeverity.WARNING,
                        message=(
                            f"Mnemonic prefix suggests {parsed_category.value} "
                            f"but io_category is {point.io_category.value}"
                        ),
                        mnemonic=point.mnemonic,
                        field_name="io_category",
                    )
                )

        # Validate address format
        if point.plc_address:
            from plc_iol.core.models import PLCAddress

            parsed = PLCAddress.from_s7_format(point.plc_address)
            if parsed is None:
                result.issues.append(
                    ValidationIssue(
                        issue_type=IssueType.INVALID_ADDRESS_FORMAT,
                        severity=IssueSeverity.WARNING,
                        message=f"Invalid PLC address format: {point.plc_address}",
                        mnemonic=point.mnemonic,
                        field_name="plc_address",
                    )
                )

    def _check_orphan_points(self, db: IODatabase, result: ValidationResult) -> None:
        """Check for points without functional group."""
        if self.config is None:
            return

        valid_groups = {g.id for g in self.config.functional_groups}
        if not valid_groups:
            return

        for point in db:
            # Skip internal tags
            if is_internal_tag(point.mnemonic):
                continue

            if not point.functional_group:
                result.issues.append(
                    ValidationIssue(
                        issue_type=IssueType.ORPHAN_POINT,
                        severity=IssueSeverity.INFO,
                        message="Point has no functional group assigned",
                        mnemonic=point.mnemonic,
                        field_name="functional_group",
                    )
                )
            elif point.functional_group not in valid_groups:
                result.issues.append(
                    ValidationIssue(
                        issue_type=IssueType.ORPHAN_POINT,
                        severity=IssueSeverity.WARNING,
                        message=f"Functional group '{point.functional_group}' not in configuration",
                        mnemonic=point.mnemonic,
                        field_name="functional_group",
                    )
                )

    def _check_tags_iol_consistency(self, result: ValidationResult) -> None:
        """Check consistency between TAGS and IOL databases."""
        if self.tags_db is None or self.iol_db is None:
            return

        tags_mnemonics = set(self.tags_db.points.keys())
        iol_mnemonics = set(self.iol_db.points.keys())

        # Filter out internal tags from TAGS
        tags_io_mnemonics = {m for m in tags_mnemonics if not is_internal_tag(m)}

        # Separate spares from regular IOL points
        iol_spares = {m for m in iol_mnemonics if is_spare(m)}
        iol_regular = iol_mnemonics - iol_spares

        # Count spares by category and calculate totals
        category_totals: dict[str, int] = {}
        for mnemonic in iol_mnemonics:
            cat = get_io_category_from_mnemonic(mnemonic)
            if cat:
                category_totals[cat] = category_totals.get(cat, 0) + 1

        for mnemonic in iol_spares:
            cat = get_io_category_from_mnemonic(mnemonic)
            if cat:
                result.spare_statistics.add_spare(cat)

        # Set totals for percentage calculation
        for cat, total in category_totals.items():
            result.spare_statistics.set_total(cat, total)

        # Points in TAGS but not in IOL (excluding spares from comparison)
        only_in_tags = tags_io_mnemonics - iol_regular - iol_spares
        for mnemonic in sorted(only_in_tags):
            result.issues.append(
                ValidationIssue(
                    issue_type=IssueType.TAGS_IOL_MISMATCH,
                    severity=IssueSeverity.WARNING,
                    message="Point exists in TAGS but not in IOL",
                    mnemonic=mnemonic,
                )
            )

        # Points in IOL but not in TAGS (excluding spares - they are expected to not be in TAGS)
        only_in_iol = iol_regular - tags_mnemonics
        for mnemonic in sorted(only_in_iol):
            result.issues.append(
                ValidationIssue(
                    issue_type=IssueType.TAGS_IOL_MISMATCH,
                    severity=IssueSeverity.WARNING,
                    message="Point exists in IOL but not in TAGS",
                    mnemonic=mnemonic,
                )
            )


def validate_database(
    db: IODatabase,
    config: ProjectConfig | None = None,
    tags_db: IODatabase | None = None,
    iol_db: IODatabase | None = None,
) -> ValidationResult:
    """
    Convenience function to validate a database.

    Args:
        db: Database to validate
        config: Optional project configuration
        tags_db: Optional TAGS database for consistency check
        iol_db: Optional IOL database for consistency check

    Returns:
        ValidationResult with issues
    """
    validator = DatabaseValidator(
        config=config,
        tags_db=tags_db,
        iol_db=iol_db,
    )
    return validator.validate(db)
