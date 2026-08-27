"""Traversal: recursion, ordering, hoisting and unreadable capture."""

from __future__ import annotations

from plc_hw.model import SubnetInfo
from plc_hw.testing import FakeItem, FakeSource, build_fake_source
from plc_hw.walk import walk_project


def test_devices_are_sorted_by_name() -> None:
    snapshot = walk_project(build_fake_source())
    assert [d.name for d in snapshot.devices] == ["IO_STATION_1", "PLC_MAIN"]


def test_paths_are_rooted_at_the_device_name() -> None:
    snapshot = walk_project(build_fake_source())
    module = snapshot.devices[0].items[0].children[0]
    assert module.path == "IO_STATION_1/Rail/F-DI"


def test_identity_attributes_are_hoisted_and_not_duplicated() -> None:
    snapshot = walk_project(build_fake_source())
    module = snapshot.devices[0].items[0].children[0]
    assert module.type_name == "F-DI 8x24VDC HF"
    assert module.order_number == "6ES7 136-6BA01-0CA0"
    assert module.firmware == "V2.0"
    assert "TypeName" not in module.attributes
    assert "TypeIdentifier" not in module.attributes
    assert "FirmwareVersion" not in module.attributes


def test_volatile_attributes_are_dropped_and_recorded() -> None:
    snapshot = walk_project(build_fake_source())
    module = snapshot.devices[0].items[0].children[0]
    assert "InstallationDate" not in module.attributes
    assert snapshot.volatile_excluded == ["InstallationDate"]


def test_volatile_list_is_configurable() -> None:
    snapshot = walk_project(build_fake_source(), volatile=("SomeParameter",))
    module = snapshot.devices[0].items[0].children[0]
    assert "SomeParameter" not in module.attributes
    assert "InstallationDate" in module.attributes
    assert snapshot.volatile_excluded == ["SomeParameter"]


def test_an_advertised_attribute_that_cannot_be_read_is_recorded_not_dropped() -> None:
    snapshot = walk_project(build_fake_source())
    module = snapshot.devices[0].items[0].children[0]
    assert [u.name for u in module.unreadable] == ["LockedParameter"]
    assert module.unreadable[0].reason == "not accessible in this context"


def test_addresses_features_and_signatures_survive() -> None:
    snapshot = walk_project(build_fake_source())
    module = snapshot.devices[0].items[0].children[0]
    assert module.addresses[0].start == 100
    assert module.features["ProfiSafe"]["FDestinationAddress"] == 65534
    assert snapshot.safety_signatures == {"CollectiveOfflineSignature": "A1B2C3D4"}
    assert snapshot.subnets == [SubnetInfo(name="PN_1", type="Ethernet", number=100)]


def test_a_rack_with_no_children_walks_clean() -> None:
    snapshot = walk_project(build_fake_source())
    empty_rack = snapshot.devices[1].items[1]
    assert empty_rack.name == "Rail_1"
    assert empty_rack.children == []


def test_a_device_with_no_racks_walks_clean() -> None:
    source = FakeSource(project="project-A", devices=[FakeItem(name="LONE")])
    snapshot = walk_project(source)
    assert snapshot.devices[0].items == []


def test_an_empty_project_walks_clean() -> None:
    snapshot = walk_project(FakeSource(project="project-A", devices=[]))
    assert snapshot.devices == []
    assert snapshot.project_name == "project-A"


def test_position_comes_from_the_position_attribute() -> None:
    item = FakeItem(name="M", attributes={"PositionNumber": 3})
    source = FakeSource(project="p", devices=[FakeItem(name="D", children=[item])])
    snapshot = walk_project(source)
    assert snapshot.devices[0].items[0].position == 3
    assert "PositionNumber" not in snapshot.devices[0].items[0].attributes


def test_multiple_unreadable_attributes_are_all_recorded() -> None:
    """A single failed read must not shadow the others advertised alongside it."""
    item = FakeItem(name="M", errors={"A": "reason-a", "B": "reason-b"})
    source = FakeSource(project="p", devices=[FakeItem(name="D", children=[item])])
    snapshot = walk_project(source)
    unreadable = snapshot.devices[0].items[0].unreadable
    assert [(u.name, u.reason) for u in unreadable] == [("A", "reason-a"), ("B", "reason-b")]


def test_an_unreadable_hoisted_attribute_is_recorded_not_silently_omitted() -> None:
    """Hoisting must not bypass the unreadable bookkeeping.

    ``TypeName`` is popped out of ``attributes`` into its own field further down
    in ``_walk_item``, after ``unreadable`` is computed. If that ordering (or the
    hoisting itself) ever caused a failed hoisted read to be skipped, the gap
    would vanish from the dump instead of surfacing.
    """
    item = FakeItem(name="M", errors={"TypeName": "not accessible in this context"})
    source = FakeSource(project="p", devices=[FakeItem(name="D", children=[item])])
    snapshot = walk_project(source)
    module = snapshot.devices[0].items[0]
    assert module.type_name == ""
    assert [u.name for u in module.unreadable] == ["TypeName"]
    assert module.unreadable[0].reason == "not accessible in this context"


def test_an_unreadable_position_is_recorded_and_position_falls_back_to_none() -> None:
    """A PositionNumber that fails to read must not read as "no position"."""
    item = FakeItem(name="M", errors={"PositionNumber": "not accessible in this context"})
    source = FakeSource(project="p", devices=[FakeItem(name="D", children=[item])])
    snapshot = walk_project(source)
    module = snapshot.devices[0].items[0]
    assert module.position is None
    assert [u.name for u in module.unreadable] == ["PositionNumber"]
