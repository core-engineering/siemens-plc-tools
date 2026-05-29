"""Core data models for IOL Management.

This module provides IOPoint and IODatabase classes for managing I/O lists.
Shared types (IOCategory, DataType, PLCAddress) are imported from plc_core.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

# Import shared types from plc_core
from plc_core.models import DataType, IOCategory, PLCAddress

if TYPE_CHECKING:
    pass


def generate_id() -> str:
    """Generate a unique 8-character ID."""
    return uuid.uuid4().hex[:8]


@dataclass
class IOPoint:
    """Represents a single I/O point in the system.

    Attributes
    ----------
    mnemonic : str
        PLC tag name (e.g., DI_LCP_PUMP_START).
    signal_name : str
        Human-readable description.
    id : str
        Unique identifier.
    customer_tag : str | None
        Customer's tag ID (e.g., 021-HS-6001).
    functional_group : str | None
        Functional group (COMMON, GROUP1, GROUP2, etc.).
    io_category : IOCategory | None
        I/O category (DI, DO, AI, AO, SDI, SDO).
    physical_type : str | None
        Physical device type.
    data_type : DataType
        PLC data type.
    hw_address : str | None
        IOL format address (E, A, PEW, PAW).
    plc_address : str | None
        S7 format address (%I, %Q, %IW, %QW).
    is_safety : bool
        Whether this is a safety I/O.
    circuit_ref : str | None
        Electrical diagram reference.
    control_unit : str | None
        Control panel unit assignment.
    control_light : str | None
        Control panel light assignment.
    is_intrinsically_safe : bool
        Whether this is intrinsically safe.
    xml_source : str | None
        Source XML filename.
    """

    mnemonic: str
    signal_name: str

    # Optional fields
    id: str = field(default_factory=generate_id)
    customer_tag: str | None = None
    functional_group: str | None = None
    io_category: IOCategory | None = None
    physical_type: str | None = None
    data_type: DataType = DataType.BOOL
    hw_address: str | None = None
    plc_address: str | None = None
    is_safety: bool = False
    circuit_ref: str | None = None
    control_unit: str | None = None
    control_light: str | None = None
    is_intrinsically_safe: bool = False
    xml_source: str | None = None

    def __post_init__(self) -> None:
        """Infer fields from mnemonic if not provided."""
        if self.io_category is None:
            # Try to infer from mnemonic prefix
            parts = self.mnemonic.split("_")
            if parts:
                self.io_category = IOCategory.from_mnemonic_prefix(parts[0])

        if self.io_category and self.is_safety is False:
            self.is_safety = self.io_category.is_safety

    @property
    def plc_address_parsed(self) -> PLCAddress | None:
        """Get parsed PLC address."""
        if self.plc_address:
            return PLCAddress.from_s7_format(self.plc_address)
        return None

    @property
    def hw_address_parsed(self) -> PLCAddress | None:
        """Get parsed hardware address (IOL format)."""
        if self.hw_address:
            return PLCAddress.from_iol_format(self.hw_address)
        return None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "mnemonic": self.mnemonic,
            "signal_name": self.signal_name,
            "customer_tag": self.customer_tag or "",
            "functional_group": self.functional_group or "",
            "io_category": self.io_category.value if self.io_category else "",
            "physical_type": self.physical_type or "",
            "data_type": self.data_type.value if self.data_type else "",
            "hw_address": self.hw_address or "",
            "plc_address": self.plc_address or "",
            "is_safety": str(self.is_safety).lower(),
            "circuit_ref": self.circuit_ref or "",
            "control_unit": self.control_unit or "",
            "control_light": self.control_light or "",
            "is_intrinsically_safe": str(self.is_intrinsically_safe).lower(),
            "xml_source": self.xml_source or "",
        }

    @classmethod
    def from_dict(cls, data: dict) -> IOPoint:
        """Create IOPoint from dictionary."""
        io_cat = None
        if data.get("io_category"):
            try:
                io_cat = IOCategory(data["io_category"])
            except ValueError:
                pass

        data_type = DataType.BOOL
        if data.get("data_type"):
            data_type = DataType.from_string(data["data_type"])

        return cls(
            id=data.get("id") or generate_id(),
            mnemonic=data["mnemonic"],
            signal_name=data.get("signal_name", ""),
            customer_tag=data.get("customer_tag") or None,
            functional_group=data.get("functional_group") or None,
            io_category=io_cat,
            physical_type=data.get("physical_type") or None,
            data_type=data_type,
            hw_address=data.get("hw_address") or None,
            plc_address=data.get("plc_address") or None,
            is_safety=str(data.get("is_safety", "false")).lower() == "true",
            circuit_ref=data.get("circuit_ref") or None,
            control_unit=data.get("control_unit") or None,
            control_light=data.get("control_light") or None,
            is_intrinsically_safe=str(data.get("is_intrinsically_safe", "false")).lower() == "true",
            xml_source=data.get("xml_source") or None,
        )


@dataclass
class IODatabase:
    """Container for a collection of IO points.

    Attributes
    ----------
    points : dict[str, IOPoint]
        Dictionary of IO points keyed by mnemonic.
    metadata : dict
        Additional metadata about the database.
    """

    points: dict[str, IOPoint] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def add(self, point: IOPoint, overwrite: bool = False) -> bool:
        """Add an IO point to the database.

        Parameters
        ----------
        point : IOPoint
            The IOPoint to add.
        overwrite : bool
            If True, overwrite existing point with same mnemonic.

        Returns
        -------
        bool
            True if point was added, False if it existed and overwrite=False.
        """
        if point.mnemonic in self.points and not overwrite:
            return False
        self.points[point.mnemonic] = point
        return True

    def get(self, mnemonic: str) -> IOPoint | None:
        """Get an IO point by mnemonic."""
        return self.points.get(mnemonic)

    def remove(self, mnemonic: str) -> bool:
        """Remove an IO point by mnemonic."""
        if mnemonic in self.points:
            del self.points[mnemonic]
            return True
        return False

    def update(self, mnemonic: str, **kwargs: object) -> IOPoint | None:
        """Update fields of an existing IO point."""
        point = self.points.get(mnemonic)
        if point is None:
            return None
        for key, value in kwargs.items():
            if hasattr(point, key):
                setattr(point, key, value)
        return point

    def filter(
        self,
        io_category: IOCategory | None = None,
        functional_group: str | None = None,
        is_safety: bool | None = None,
        xml_source: str | None = None,
    ) -> list[IOPoint]:
        """Filter points by criteria."""
        results = []
        for point in self.points.values():
            if io_category is not None and point.io_category != io_category:
                continue
            if functional_group is not None and point.functional_group != functional_group:
                continue
            if is_safety is not None and point.is_safety != is_safety:
                continue
            if xml_source is not None and point.xml_source != xml_source:
                continue
            results.append(point)
        return results

    def __len__(self) -> int:
        """Return number of points in database."""
        return len(self.points)

    def __iter__(self) -> Iterator[IOPoint]:
        """Iterate over all points."""
        return iter(self.points.values())

    def __contains__(self, mnemonic: str) -> bool:
        """Check if mnemonic exists in database."""
        return mnemonic in self.points

    def get_statistics(self) -> dict:
        """Get database statistics."""
        stats: dict = {
            "total": len(self.points),
            "by_category": {},
            "by_functional_group": {},
            "by_xml_source": {},
            "safety_points": 0,
        }

        for point in self.points.values():
            # By category (None means internal PLC tag without physical I/O)
            cat = point.io_category.value if point.io_category else "Internal"
            stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1

            # By functional group
            group = point.functional_group or "Unknown"
            stats["by_functional_group"][group] = stats["by_functional_group"].get(group, 0) + 1

            # By XML source
            source = point.xml_source or "Unknown"
            stats["by_xml_source"][source] = stats["by_xml_source"].get(source, 0) + 1

            # Safety count
            if point.is_safety:
                stats["safety_points"] += 1

        return stats

    def merge(self, other: IODatabase, overwrite: bool = False) -> dict:
        """Merge another database into this one.

        Parameters
        ----------
        other : IODatabase
            The database to merge from.
        overwrite : bool
            If True, overwrite existing points.

        Returns
        -------
        dict
            Statistics about the merge operation.
        """
        stats = {"added": 0, "skipped": 0, "overwritten": 0}
        for point in other:
            if point.mnemonic in self.points:
                if overwrite:
                    self.points[point.mnemonic] = point
                    stats["overwritten"] += 1
                else:
                    stats["skipped"] += 1
            else:
                self.points[point.mnemonic] = point
                stats["added"] += 1
        return stats
