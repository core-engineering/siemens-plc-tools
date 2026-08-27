"""In-memory HardwareSource for tests.

Shipped with the package rather than kept under tests/: no tests directory here
carries an __init__.py, so a test module has no parent package to import from.

Two devices, one of them with two racks, one module carrying an unreadable
attribute. Names are neutral on purpose: this repository is public.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from plc_hw.model import AddressRange, AttributeInfo, NodeRef, SubnetInfo


@dataclass
class FakeItem:
    """One node in the fake tree.

    Attributes
    ----------
    name : str
        The item's name, verbatim.
    attributes : dict[str, object]
        Attributes readable on this item, keyed by name.
    errors : dict[str, str]
        Reason text for attributes that are advertised but not readable, keyed
        by attribute name.
    addresses : list[AddressRange]
        Input/output address ranges owned by this item.
    features : dict[str, dict[str, object]]
        Feature name to its captured values.
    children : list[FakeItem]
        Nested items.
    """

    name: str
    attributes: dict[str, object] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    addresses: list[AddressRange] = field(default_factory=list)
    features: dict[str, dict[str, object]] = field(default_factory=dict)
    children: list[FakeItem] = field(default_factory=list)


class FakeSource:
    """A HardwareSource backed by a literal tree.

    Parameters
    ----------
    project : str
        Project name returned by :meth:`project_name`.
    devices : list[FakeItem]
        Top-level items returned by :meth:`devices`.
    subnets : list[SubnetInfo] | None
        Subnets returned by :meth:`subnets`. Defaults to an empty list.
    signatures : dict[str, str] | None
        Safety signatures returned by :meth:`safety_signatures`. Defaults to an
        empty dict.
    """

    def __init__(
        self,
        project: str,
        devices: list[FakeItem],
        subnets: list[SubnetInfo] | None = None,
        signatures: dict[str, str] | None = None,
    ) -> None:
        self._project = project
        self._devices = devices
        self._subnets = subnets or []
        self._signatures = signatures or {}
        self._by_key: dict[str, FakeItem] = {}
        for device in devices:
            self._index(device, device.name)

    def _index(self, item: FakeItem, path: str) -> None:
        """Populate the key-to-item lookup for ``item`` and its descendants.

        Parameters
        ----------
        item : FakeItem
            Item to index.
        path : str
            Key to assign to ``item``. Descendants get ``path`` extended with
            their own name, ``/``-joined.
        """
        self._by_key[path] = item
        for child in item.children:
            self._index(child, f"{path}/{child.name}")

    def project_name(self) -> str:
        """Return the project name.

        Returns
        -------
        str
            The project name passed to the constructor.
        """
        return self._project

    def subnets(self) -> list[SubnetInfo]:
        """Return the project's subnets and IO systems.

        Returns
        -------
        list[SubnetInfo]
            A copy of the subnets passed to the constructor.
        """
        return list(self._subnets)

    def devices(self) -> list[NodeRef]:
        """Return the project's devices.

        Returns
        -------
        list[NodeRef]
            One reference per top-level item, in the order given.
        """
        return [NodeRef(key=d.name, name=d.name) for d in self._devices]

    def device_items(self, parent: NodeRef) -> list[NodeRef]:
        """Return the direct children of a device or device item.

        Parameters
        ----------
        parent : NodeRef
            Reference to the item whose children are requested.

        Returns
        -------
        list[NodeRef]
            One reference per direct child, in the order given.
        """
        item = self._by_key[parent.key]
        return [NodeRef(key=f"{parent.key}/{c.name}", name=c.name) for c in item.children]

    def attribute_infos(self, item: NodeRef) -> list[AttributeInfo]:
        """Return the attributes a device item advertises.

        Parameters
        ----------
        item : NodeRef
            Reference to the item.

        Returns
        -------
        list[AttributeInfo]
            One entry per readable or unreadable attribute name, sorted.
        """
        node = self._by_key[item.key]
        names = sorted(set(node.attributes) | set(node.errors))
        return [AttributeInfo(name=n, read_only=True) for n in names]

    def attributes(self, item: NodeRef, names: Sequence[str]) -> dict[str, object]:
        """Read the named attributes.

        Parameters
        ----------
        item : NodeRef
            Reference to the item.
        names : Sequence[str]
            Attribute names to read.

        Returns
        -------
        dict[str, object]
            Only the requested names that could actually be read.
        """
        node = self._by_key[item.key]
        return {n: node.attributes[n] for n in names if n in node.attributes}

    def attribute_error(self, item: NodeRef, name: str) -> str:
        """Return why ``name`` could not be read on ``item``.

        Parameters
        ----------
        item : NodeRef
            Reference to the item.
        name : str
            Attribute name.

        Returns
        -------
        str
            The recorded reason, or ``"unknown"`` when none was recorded.
        """
        return self._by_key[item.key].errors.get(name, "unknown")

    def addresses(self, item: NodeRef) -> list[AddressRange]:
        """Return the item's input/output address ranges.

        Parameters
        ----------
        item : NodeRef
            Reference to the item.

        Returns
        -------
        list[AddressRange]
            A copy of the item's address ranges.
        """
        return list(self._by_key[item.key].addresses)

    def features(self, item: NodeRef) -> dict[str, dict[str, object]]:
        """Return the item's captured features, keyed by feature name.

        Parameters
        ----------
        item : NodeRef
            Reference to the item.

        Returns
        -------
        dict[str, dict[str, object]]
            A copy of the item's features.
        """
        return dict(self._by_key[item.key].features)

    def safety_signatures(self) -> dict[str, str]:
        """Return the project's safety signatures, keyed by signature type.

        Returns
        -------
        dict[str, str]
            A copy of the signatures passed to the constructor.
        """
        return dict(self._signatures)


def build_fake_source() -> FakeSource:
    """Build the standard two-device fixture used across the suite.

    Returns
    -------
    FakeSource
        A source with two devices: ``IO_STATION_1`` (one rack, one module with
        a readable and an unreadable attribute) and ``PLC_MAIN`` (two racks,
        one carrying a CPU).
    """
    module = FakeItem(
        name="F-DI",
        attributes={
            "TypeName": "F-DI 8x24VDC HF",
            "TypeIdentifier": "OrderNumber:6ES7 136-6BA01-0CA0",
            "FirmwareVersion": "V2.0",
            "InstallationDate": "2026-06-09T11:46:15Z",
            "SomeParameter": 150,
        },
        errors={"LockedParameter": "not accessible in this context"},
        addresses=[AddressRange(start=100, length=8, io_type="Input")],
        features={"ProfiSafe": {"FDestinationAddress": 65534}},
    )
    station = FakeItem(name="IO_STATION_1", children=[FakeItem(name="Rail", children=[module])])
    cpu = FakeItem(
        name="CPU",
        attributes={"TypeName": "CPU", "FirmwareVersion": "V3.1", "SomeParameter": 1},
    )
    plc = FakeItem(
        name="PLC_MAIN",
        children=[FakeItem(name="Rail_0", children=[cpu]), FakeItem(name="Rail_1")],
    )
    return FakeSource(
        project="project-A",
        devices=[station, plc],
        subnets=[SubnetInfo(name="PN_1", type="Ethernet", number=100)],
        signatures={"CollectiveOfflineSignature": "A1B2C3D4"},
    )
