"""Traversal: recursion, ordering, hoisting and unreadable capture."""

from __future__ import annotations

from plc_hw.model import AttributeInfo, NodeRef, SubnetInfo
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


def test_an_unreadable_device_type_identifier_is_recorded_not_silently_omitted() -> None:
    """A device is not exempt from the gap-recording discipline either.

    Reading the device's own ``TypeIdentifier`` used to bypass ``_walk_item``'s
    request/compare/record logic entirely, so a failed read fell back to ``""``
    with nothing anywhere in the snapshot saying the read was attempted and
    failed -- indistinguishable from a device that genuinely has none.
    """
    device = FakeItem(name="D", errors={"TypeIdentifier": "not accessible in this context"})
    snapshot = walk_project(FakeSource(project="p", devices=[device]))
    assert snapshot.devices[0].type_identifier == ""
    assert [u.name for u in snapshot.devices[0].unreadable] == ["TypeIdentifier"]
    assert snapshot.devices[0].unreadable[0].reason == "not accessible in this context"


def test_a_readable_device_type_identifier_leaves_unreadable_empty() -> None:
    """The new field must not fill with noise when the read actually succeeds."""
    device = FakeItem(name="D", attributes={"TypeIdentifier": "System:Device.X"})
    snapshot = walk_project(FakeSource(project="p", devices=[device]))
    assert snapshot.devices[0].type_identifier == "System:Device.X"
    assert snapshot.devices[0].unreadable == []


class _DuplicateAdvertisingSource(FakeSource):
    """A source whose ``attribute_infos`` advertises the same name twice.

    ``FakeSource.attribute_infos`` runs advertised names through ``set()``, so
    it cannot exercise the walker's own deduplication. This subclass overrides
    only that one method to prove ``_walk_item`` does not double-record a name
    the source itself advertised twice.
    """

    def attribute_infos(self, item: NodeRef) -> list[AttributeInfo]:
        return [AttributeInfo(name="Dup", read_only=True), AttributeInfo(name="Dup", read_only=True)]


def test_children_are_sorted_by_position_not_source_enumeration_order() -> None:
    """Spec S6.4: rack/module order must not depend on ``device_items()`` order.

    Handed to the walker in reverse-of-position order -- the exact scenario
    from the finding -- the walker must still emit them low-position-first, so
    the writer's filename index (the list index) lines up with a stable order
    rather than whatever Openness happened to enumerate.
    """
    slot5 = FakeItem(name="ModAtSlot5", attributes={"PositionNumber": 5})
    slot1 = FakeItem(name="ModAtSlot1", attributes={"PositionNumber": 1})
    source = FakeSource(project="p", devices=[FakeItem(name="D", children=[slot5, slot1])])
    snapshot = walk_project(source)
    assert [i.name for i in snapshot.devices[0].items] == ["ModAtSlot1", "ModAtSlot5"]


def test_children_with_no_position_sort_last_and_deterministically_by_name() -> None:
    """A missing ``position`` must sort last, not raise on a comparison against ``None``."""
    no_position_b = FakeItem(name="B")
    no_position_a = FakeItem(name="A")
    has_position = FakeItem(name="Z", attributes={"PositionNumber": 1})
    source = FakeSource(
        project="p", devices=[FakeItem(name="D", children=[no_position_b, no_position_a, has_position])]
    )
    snapshot = walk_project(source)
    assert [i.name for i in snapshot.devices[0].items] == ["Z", "A", "B"]


def test_grandchildren_are_sorted_too() -> None:
    """The same ordering discipline applies one level down, at ``children``."""
    module5 = FakeItem(name="ModAtSlot5", attributes={"PositionNumber": 5})
    module1 = FakeItem(name="ModAtSlot1", attributes={"PositionNumber": 1})
    rack = FakeItem(name="Rail", children=[module5, module1])
    source = FakeSource(project="p", devices=[FakeItem(name="D", children=[rack])])
    snapshot = walk_project(source)
    assert [c.name for c in snapshot.devices[0].items[0].children] == ["ModAtSlot1", "ModAtSlot5"]


def test_a_name_advertised_twice_is_recorded_as_unreadable_only_once() -> None:
    item = FakeItem(name="M", errors={"Dup": "boom"})
    source = _DuplicateAdvertisingSource(project="p", devices=[FakeItem(name="D", children=[item])])
    snapshot = walk_project(source)
    unreadable = snapshot.devices[0].items[0].unreadable
    assert [u.name for u in unreadable] == ["Dup"]
