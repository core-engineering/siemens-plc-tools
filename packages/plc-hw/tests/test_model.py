"""Data model and source-protocol conformance."""

from __future__ import annotations

from plc_hw.model import (
    AddressRange,
    AttributeInfo,
    DeviceItemNode,
    DeviceNode,
    NodeRef,
    ProjectSnapshot,
    SubnetInfo,
    UnreadableAttribute,
)
from plc_hw.source import HardwareSource
from plc_hw.testing import build_fake_source


def test_device_item_node_defaults_are_independent() -> None:
    first = DeviceItemNode(name="a", path="a", position=1)
    second = DeviceItemNode(name="b", path="b", position=2)
    first.attributes["x"] = 1
    assert second.attributes == {}


def test_snapshot_holds_every_captured_kind() -> None:
    item = DeviceItemNode(
        name="F-DI",
        path="IO_STATION_1/Rail/1",
        position=1,
        type_name="F-DI 8x24VDC HF",
        order_number="6ES7 136-6BA01-0CA0",
        firmware="V2.0",
        attributes={"SomeParameter": 150},
        addresses=[AddressRange(start=100, length=8, io_type="Input")],
        features={"ProfiSafe": {"FDestinationAddress": 65534}},
        unreadable=[UnreadableAttribute(name="Locked", reason="not accessible")],
    )
    snapshot = ProjectSnapshot(
        project_name="project-A",
        subnets=[SubnetInfo(name="PN_1", type="Ethernet", number=None)],
        devices=[DeviceNode(name="IO_STATION_1", type_identifier="System:Device.X", items=[item])],
        safety_signatures={"CollectiveOfflineSignature": "A1B2C3D4"},
        volatile_excluded=["InstallationDate"],
    )
    assert snapshot.devices[0].items[0].addresses[0].length == 8
    assert snapshot.safety_signatures["CollectiveOfflineSignature"] == "A1B2C3D4"


def test_fake_source_satisfies_the_protocol() -> None:
    source: HardwareSource = build_fake_source()
    assert source.project_name() == "project-A"
    devices = source.devices()
    assert [d.name for d in devices] == ["IO_STATION_1", "PLC_MAIN"]
    assert isinstance(devices[0], NodeRef)
    infos = source.attribute_infos(source.device_items(source.device_items(devices[0])[0])[0])
    assert all(isinstance(info, AttributeInfo) for info in infos)
