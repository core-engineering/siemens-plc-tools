"""Database comparison and diff analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from plc_iol.core.models import IODatabase, IOPoint

if TYPE_CHECKING:
    from plc_iol.core.config import ProjectConfig


class DiffType(str, Enum):
    """Type of difference between points."""

    ADDED = "added"  # Point exists only in target
    REMOVED = "removed"  # Point exists only in source
    MODIFIED = "modified"  # Point exists in both but differs
    UNCHANGED = "unchanged"  # Point is identical in both


@dataclass
class FieldDiff:
    """Difference in a single field."""

    field_name: str
    source_value: str | None
    target_value: str | None


@dataclass
class PointDiff:
    """Difference record for a single point."""

    mnemonic: str
    diff_type: DiffType
    field_diffs: list[FieldDiff] = field(default_factory=list)
    source_point: IOPoint | None = None
    target_point: IOPoint | None = None

    @property
    def is_significant(self) -> bool:
        """Check if this diff represents a significant change."""
        return self.diff_type != DiffType.UNCHANGED


@dataclass
class ComparisonResult:
    """Result of comparing two databases."""

    source_name: str
    target_name: str
    diffs: list[PointDiff]
    source_count: int
    target_count: int

    @property
    def added_count(self) -> int:
        """Number of points added in target."""
        return sum(1 for d in self.diffs if d.diff_type == DiffType.ADDED)

    @property
    def removed_count(self) -> int:
        """Number of points removed from source."""
        return sum(1 for d in self.diffs if d.diff_type == DiffType.REMOVED)

    @property
    def modified_count(self) -> int:
        """Number of points modified."""
        return sum(1 for d in self.diffs if d.diff_type == DiffType.MODIFIED)

    @property
    def unchanged_count(self) -> int:
        """Number of unchanged points."""
        return sum(1 for d in self.diffs if d.diff_type == DiffType.UNCHANGED)

    @property
    def has_changes(self) -> bool:
        """Check if there are any differences."""
        return self.added_count > 0 or self.removed_count > 0 or self.modified_count > 0

    def get_added(self) -> list[PointDiff]:
        """Get all added points."""
        return [d for d in self.diffs if d.diff_type == DiffType.ADDED]

    def get_removed(self) -> list[PointDiff]:
        """Get all removed points."""
        return [d for d in self.diffs if d.diff_type == DiffType.REMOVED]

    def get_modified(self) -> list[PointDiff]:
        """Get all modified points."""
        return [d for d in self.diffs if d.diff_type == DiffType.MODIFIED]

    def summary(self) -> str:
        """Get a summary of the comparison."""
        lines = [
            f"Comparison: {self.source_name} → {self.target_name}",
            f"Source points: {self.source_count}",
            f"Target points: {self.target_count}",
            f"Added: {self.added_count}",
            f"Removed: {self.removed_count}",
            f"Modified: {self.modified_count}",
            f"Unchanged: {self.unchanged_count}",
        ]
        return "\n".join(lines)


class DatabaseComparator:
    """
    Compares two IO databases and identifies differences.

    Useful for:
    - Comparing TAGS (XML) vs IOL (Excel)
    - Comparing different versions of the same database
    - Identifying synchronization issues
    """

    # Fields to compare
    COMPARE_FIELDS = [
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
    ]

    def __init__(
        self,
        config: ProjectConfig | None = None,
        ignore_fields: list[str] | None = None,
        case_sensitive: bool = False,
    ):
        """
        Initialize comparator.

        Args:
            config: Optional project configuration
            ignore_fields: Fields to ignore during comparison
            case_sensitive: Whether to compare strings case-sensitively
        """
        self.config = config
        self.ignore_fields = set(ignore_fields) if ignore_fields else set()
        self.case_sensitive = case_sensitive

    def compare(
        self,
        source: IODatabase,
        target: IODatabase,
        source_name: str = "Source",
        target_name: str = "Target",
    ) -> ComparisonResult:
        """
        Compare two databases.

        Args:
            source: Source database (e.g., existing TAGS)
            target: Target database (e.g., new IOL import)
            source_name: Name for source in reports
            target_name: Name for target in reports

        Returns:
            ComparisonResult with all differences
        """
        diffs = []

        # Get all mnemonics
        source_mnemonics = set(source.points.keys())
        target_mnemonics = set(target.points.keys())

        # Points only in source (removed)
        for mnemonic in sorted(source_mnemonics - target_mnemonics):
            diffs.append(
                PointDiff(
                    mnemonic=mnemonic,
                    diff_type=DiffType.REMOVED,
                    source_point=source.get(mnemonic),
                )
            )

        # Points only in target (added)
        for mnemonic in sorted(target_mnemonics - source_mnemonics):
            diffs.append(
                PointDiff(
                    mnemonic=mnemonic,
                    diff_type=DiffType.ADDED,
                    target_point=target.get(mnemonic),
                )
            )

        # Points in both (compare)
        for mnemonic in sorted(source_mnemonics & target_mnemonics):
            source_point = source.get(mnemonic)
            target_point = target.get(mnemonic)
            field_diffs = self._compare_points(source_point, target_point)

            if field_diffs:
                diffs.append(
                    PointDiff(
                        mnemonic=mnemonic,
                        diff_type=DiffType.MODIFIED,
                        field_diffs=field_diffs,
                        source_point=source_point,
                        target_point=target_point,
                    )
                )
            else:
                diffs.append(
                    PointDiff(
                        mnemonic=mnemonic,
                        diff_type=DiffType.UNCHANGED,
                        source_point=source_point,
                        target_point=target_point,
                    )
                )

        return ComparisonResult(
            source_name=source_name,
            target_name=target_name,
            diffs=diffs,
            source_count=len(source),
            target_count=len(target),
        )

    def _compare_points(
        self,
        source: IOPoint | None,
        target: IOPoint | None,
    ) -> list[FieldDiff]:
        """Compare two points and return field differences."""
        if source is None or target is None:
            return []

        diffs = []
        for field_name in self.COMPARE_FIELDS:
            if field_name in self.ignore_fields:
                continue

            source_value = self._get_field_value(source, field_name)
            target_value = self._get_field_value(target, field_name)

            if not self._values_equal(source_value, target_value):
                diffs.append(
                    FieldDiff(
                        field_name=field_name,
                        source_value=source_value,
                        target_value=target_value,
                    )
                )

        return diffs

    def _get_field_value(self, point: IOPoint, field_name: str) -> str | None:
        """Get field value as string for comparison."""
        value = getattr(point, field_name, None)
        if value is None:
            return None
        if hasattr(value, "value"):  # Enum
            return str(value.value)
        return str(value)

    def _values_equal(self, a: str | None, b: str | None) -> bool:
        """Compare two values for equality."""
        # Treat None and empty string as equal
        a = a or ""
        b = b or ""

        if not self.case_sensitive:
            a = a.lower()
            b = b.lower()

        return a == b


def compare_databases(
    source: IODatabase,
    target: IODatabase,
    source_name: str = "Source",
    target_name: str = "Target",
    ignore_fields: list[str] | None = None,
) -> ComparisonResult:
    """
    Convenience function to compare two databases.

    Args:
        source: Source database
        target: Target database
        source_name: Name for source
        target_name: Name for target
        ignore_fields: Fields to ignore

    Returns:
        ComparisonResult with differences
    """
    comparator = DatabaseComparator(ignore_fields=ignore_fields)
    return comparator.compare(source, target, source_name, target_name)
