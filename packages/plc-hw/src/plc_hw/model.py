"""Data model for a hardware snapshot.

Every type here is plain data. Nothing in this module knows about TIA, the CLR,
YAML or the filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NodeRef:
    """Handle to one TIA object, as seen across the source boundary.

    Attributes
    ----------
    key : str
        Identity of the object within one source session. The walker builds it
        from the hierarchical path, so it is stable across a record/replay pair.
    name : str
        The object's TIA name, verbatim.
    """

    key: str
    name: str


@dataclass(frozen=True)
class AttributeInfo:
    """One attribute a device item advertises.

    Attributes
    ----------
    name : str
        Attribute name as TIA reports it.
    read_only : bool
        Whether TIA reports the attribute as read-only. Recorded for information;
        this package never writes.
    """

    name: str
    read_only: bool = False


@dataclass(frozen=True)
class AddressRange:
    """One input or output address range.

    Attributes
    ----------
    start : int
        First byte of the range.
    length : int
        Range length in bytes.
    io_type : str
        ``Input``, ``Output`` or whatever TIA reports.
    """

    start: int
    length: int
    io_type: str


@dataclass(frozen=True)
class SubnetInfo:
    """One project subnet.

    Attributes
    ----------
    name : str
        Subnet name.
    type : str
        ``Ethernet``, ``Profibus``, ...
    number : int | None
        IO system number when the subnet carries one.
    """

    name: str
    type: str
    number: int | None = None


@dataclass(frozen=True)
class UnreadableAttribute:
    """An attribute that was advertised but could not be read.

    Recorded explicitly: an attribute silently dropped from a dump reads as
    "unchanged" on the next diff, when it actually means "not read".

    Attributes
    ----------
    name : str
        Attribute name.
    reason : str
        Why the read failed, as reported by the source.
    """

    name: str
    reason: str


@dataclass
class DeviceItemNode:
    """One device item: a rack, a module, a submodule, an interface or a port.

    Attributes
    ----------
    name : str
        TIA name, verbatim.
    path : str
        Hierarchical path, ``/``-joined, rooted at the device name.
    position : int | None
        Slot position, when the item has one.
    type_name : str
        Hoisted out of ``attributes`` so it is not duplicated in the output.
    order_number : str
        Hoisted from the ``TypeIdentifier`` attribute.
    firmware : str
        Hoisted from the ``FirmwareVersion`` attribute.
    attributes : dict[str, object]
        Every remaining readable attribute.
    addresses : list[AddressRange]
        Input/output address ranges.
    features : dict[str, dict[str, object]]
        Feature name to its captured values.
    unreadable : list[UnreadableAttribute]
        Attributes advertised but not readable.
    children : list[DeviceItemNode]
        Nested items.
    """

    name: str
    path: str
    position: int | None = None
    type_name: str = ""
    order_number: str = ""
    firmware: str = ""
    attributes: dict[str, object] = field(default_factory=dict)
    addresses: list[AddressRange] = field(default_factory=list)
    features: dict[str, dict[str, object]] = field(default_factory=dict)
    unreadable: list[UnreadableAttribute] = field(default_factory=list)
    children: list[DeviceItemNode] = field(default_factory=list)


@dataclass
class DeviceNode:
    """One device, with its racks as top-level items.

    Attributes
    ----------
    name : str
        TIA device name.
    type_identifier : str
        TIA type identifier for the device.
    items : list[DeviceItemNode]
        Racks. Their children are the modules.
    unreadable : list[UnreadableAttribute]
        Attributes advertised or requested on the device itself that could not
        be read.
    """

    name: str
    type_identifier: str = ""
    items: list[DeviceItemNode] = field(default_factory=list)
    unreadable: list[UnreadableAttribute] = field(default_factory=list)


@dataclass
class ProjectSnapshot:
    """Everything one dump captures.

    Attributes
    ----------
    project_name : str
        TIA project name.
    subnets : list[SubnetInfo]
        Project subnets and IO systems.
    devices : list[DeviceNode]
        Devices, sorted by name.
    safety_signatures : dict[str, str]
        Signature type to value.
    volatile_excluded : list[str]
        Attribute names deliberately dropped, so the dump describes itself.
    """

    project_name: str
    subnets: list[SubnetInfo] = field(default_factory=list)
    devices: list[DeviceNode] = field(default_factory=list)
    safety_signatures: dict[str, str] = field(default_factory=dict)
    volatile_excluded: list[str] = field(default_factory=list)
