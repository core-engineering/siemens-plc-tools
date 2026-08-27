"""Semantic comparison of two snapshots."""

from __future__ import annotations

import copy

from plc_core.reporting import Severity

from plc_hw.diff import _TITLES, build_report, diff_snapshots
from plc_hw.model import DeviceItemNode, DeviceNode, ProjectSnapshot, SubnetInfo, UnreadableAttribute
from plc_hw.testing import build_fake_source
from plc_hw.walk import walk_project


def _base() -> ProjectSnapshot:
    return walk_project(build_fake_source())


def _module(snapshot: ProjectSnapshot) -> DeviceItemNode:
    return snapshot.devices[0].items[0].children[0]


def _codes(old: ProjectSnapshot, new: ProjectSnapshot) -> list[str]:
    return [f.rule_code for f in diff_snapshots(old, new)]


def test_identical_snapshots_produce_nothing() -> None:
    assert diff_snapshots(_base(), _base()) == []


def test_safety_signature_change_is_an_error() -> None:
    new = _base()
    new.safety_signatures["CollectiveOfflineSignature"] = "DEADBEEF"
    findings = diff_snapshots(_base(), new)
    assert [f.rule_code for f in findings] == ["HW001"]
    assert findings[0].severity is Severity.ERROR
    assert "A1B2C3D4" in findings[0].message and "DEADBEEF" in findings[0].message


def test_f_destination_address_change_is_an_error_not_a_plain_attribute_change() -> None:
    new = _base()
    _module(new).features["ProfiSafe"]["FDestinationAddress"] = 65000
    findings = diff_snapshots(_base(), new)
    assert [f.rule_code for f in findings] == ["HW002"]
    assert findings[0].severity is Severity.ERROR


def test_device_added_and_removed() -> None:
    new = _base()
    new.devices.append(DeviceNode(name="NEW_DEVICE"))
    assert _codes(_base(), new) == ["HW003"]
    assert _codes(new, _base()) == ["HW004"]


def test_module_added_and_removed() -> None:
    new = _base()
    new.devices[0].items[0].children.append(DeviceItemNode(name="EXTRA", path="IO_STATION_1/Rail/EXTRA"))
    assert _codes(_base(), new) == ["HW005"]
    assert _codes(new, _base()) == ["HW006"]


def test_module_moved_to_another_position() -> None:
    new = _base()
    _module(new).position = 7
    assert _codes(_base(), new) == ["HW007"]


def test_order_number_and_firmware_changes_are_errors() -> None:
    new = _base()
    _module(new).order_number = "6ES7 000-0AA00-0AA0"
    _module(new).firmware = "V2.1"
    findings = diff_snapshots(_base(), new)
    assert sorted(f.rule_code for f in findings) == ["HW008", "HW009"]
    assert all(f.severity is Severity.ERROR for f in findings)


def test_plain_attribute_change_is_a_warning() -> None:
    new = _base()
    _module(new).attributes["SomeParameter"] = 500
    findings = diff_snapshots(_base(), new)
    assert [f.rule_code for f in findings] == ["HW010"]
    assert findings[0].severity is Severity.WARNING
    assert findings[0].location == "IO_STATION_1/Rail/F-DI"


def test_attribute_added_and_removed_are_attribute_changes() -> None:
    new = _base()
    _module(new).attributes["Brand New"] = 1
    assert _codes(_base(), new) == ["HW010"]


def test_an_attribute_becoming_unreadable_is_reported_never_silent() -> None:
    old = _base()
    new = copy.deepcopy(old)
    _module(new).attributes.pop("SomeParameter")
    _module(new).unreadable.append(
        UnreadableAttribute(name="SomeParameter", reason="not accessible in this context")
    )
    codes = _codes(old, new)
    assert "HW011" in codes


def test_attribute_becoming_readable_again_produces_no_unreadable_finding() -> None:
    old = _base()
    new = copy.deepcopy(old)
    _module(new).unreadable = [u for u in _module(new).unreadable if u.name != "LockedParameter"]
    assert _codes(old, new) == []


def test_unreadable_reason_change_is_a_warning_on_item_and_device() -> None:
    item_new = _base()
    mod = _module(item_new)
    mod.unreadable = [
        UnreadableAttribute(name=u.name, reason="communication timeout") if u.name == "LockedParameter" else u
        for u in mod.unreadable
    ]
    findings = diff_snapshots(_base(), item_new)
    assert [f.rule_code for f in findings] == ["HW018"]
    assert findings[0].severity is Severity.WARNING
    assert findings[0].location == "IO_STATION_1/Rail/F-DI"
    assert "not accessible in this context" in findings[0].message
    assert "communication timeout" in findings[0].message

    device_new = _base()
    device_new.devices[0].unreadable = [
        UnreadableAttribute(name=u.name, reason="communication timeout") if u.name == "TypeIdentifier" else u
        for u in device_new.devices[0].unreadable
    ]
    device_findings = diff_snapshots(_base(), device_new)
    assert [f.rule_code for f in device_findings] == ["HW018"]
    assert device_findings[0].severity is Severity.WARNING
    assert device_findings[0].location == "IO_STATION_1"


def test_unreadable_attribute_with_same_reason_on_both_sides_is_silent() -> None:
    new = _base()
    mod = _module(new)
    # Fresh objects, equal by value but not by identity: proves the comparison
    # is on ``reason``, not on object identity.
    mod.unreadable = [UnreadableAttribute(name=u.name, reason=u.reason) for u in mod.unreadable]
    assert _codes(_base(), new) == []


def test_f_address_marker_mid_identifier_is_not_promoted() -> None:
    attr_new = _base()
    _module(attr_new).attributes["MyFSourceAddressBackup"] = 1
    assert _codes(_base(), attr_new) == ["HW010"]

    feature_new = _base()
    _module(feature_new).features["ProfiSafe"]["NotReallyFDestinationAddressXYZ"] = 1
    assert _codes(_base(), feature_new) == ["HW013"]


def test_real_openness_f_address_names_are_still_promoted() -> None:
    source_new = _base()
    _module(source_new).attributes["Failsafe_FSourceAddress"] = 1
    assert _codes(_base(), source_new) == ["HW002"]

    dest_new = _base()
    _module(dest_new).attributes["Failsafe_FDestinationAddress"] = 1
    assert _codes(_base(), dest_new) == ["HW002"]


def test_address_range_change_is_reported() -> None:
    new = _base()
    _module(new).addresses[0] = type(_module(new).addresses[0])(start=200, length=8, io_type="Input")
    assert _codes(_base(), new) == ["HW012"]


def test_feature_change_is_reported() -> None:
    new = _base()
    _module(new).features["ProfiSafe"]["SomeOtherKey"] = 3
    assert _codes(_base(), new) == ["HW013"]


def test_changing_the_volatile_list_shows_up() -> None:
    new = _base()
    new.volatile_excluded = ["InstallationDate", "SomeParameter"]
    assert _codes(_base(), new) == ["HW014"]


def test_findings_are_ordered_deterministically() -> None:
    new = _base()
    _module(new).attributes["SomeParameter"] = 500
    _module(new).firmware = "V9.9"
    new.safety_signatures["CollectiveOfflineSignature"] = "DEADBEEF"
    first = [f.rule_code for f in diff_snapshots(_base(), new)]
    second = [f.rule_code for f in diff_snapshots(_base(), new)]
    assert first == second == sorted(first)


def test_build_report_groups_and_counts() -> None:
    new = _base()
    _module(new).attributes["SomeParameter"] = 500
    new.safety_signatures["CollectiveOfflineSignature"] = "DEADBEEF"
    report = build_report(diff_snapshots(_base(), new))
    assert report.total_errors == 1
    assert report.total_warnings == 1
    assert not report.passed


def test_type_name_change_is_an_error() -> None:
    """type_name is hoisted by the walker but was never compared -- a fourth
    uncovered field found while auditing the model, fixed alongside the three
    corrections the brief called out explicitly."""
    new = _base()
    _module(new).type_name = "F-DI 16x24VDC HF"
    findings = diff_snapshots(_base(), new)
    assert [f.rule_code for f in findings] == ["HW017"]
    assert findings[0].severity is Severity.ERROR
    assert findings[0].location == "IO_STATION_1/Rail/F-DI"
    assert findings[0].context == "type_name"


def test_device_type_identifier_change_is_an_error_on_the_device() -> None:
    new = _base()
    new.devices[0].type_identifier = "OrderNumber:6ES7 000-0AA00-0AA0"
    findings = diff_snapshots(_base(), new)
    assert [f.rule_code for f in findings] == ["HW008"]
    assert findings[0].severity is Severity.ERROR
    assert findings[0].location == "IO_STATION_1"
    assert findings[0].context == "type_identifier"


def test_device_attribute_becoming_unreadable_is_reported_and_stable_case_is_silent() -> None:
    # The base fixture's IO_STATION_1 device already has "TypeIdentifier"
    # unreadable (it has no such attribute), so that name is a stable case,
    # not a new one -- used below to prove a pre-existing gap stays silent.
    old = _base()
    new = copy.deepcopy(old)
    new.devices[0].unreadable.append(
        UnreadableAttribute(name="AnotherAttribute", reason="not accessible in this context")
    )
    codes = _codes(old, new)
    assert codes == ["HW011"]

    # An attribute already unreadable on both sides produces nothing.
    assert _codes(old, copy.deepcopy(old)) == []


def test_subnet_added_removed_and_changed_are_each_reported() -> None:
    added = _base()
    added.subnets.append(SubnetInfo(name="PN_2", type="Ethernet", number=200))
    assert _codes(_base(), added) == ["HW015"]

    removed = _base()
    removed.subnets = []
    assert _codes(_base(), removed) == ["HW015"]

    changed = _base()
    changed.subnets[0] = SubnetInfo(name="PN_1", type="Ethernet", number=999)
    findings = diff_snapshots(_base(), changed)
    assert [f.rule_code for f in findings] == ["HW015"]
    assert findings[0].severity is Severity.WARNING


def test_project_name_change_is_reported() -> None:
    new = _base()
    new.project_name = "project-B"
    findings = diff_snapshots(_base(), new)
    assert [f.rule_code for f in findings] == ["HW016"]
    assert findings[0].severity is Severity.WARNING
    assert findings[0].location == "_project"
    assert findings[0].context == "project_name"


def test_every_rule_code_is_reachable() -> None:
    """No rule code sits in the table unable to fire."""
    seen: set[str] = set()

    base = _base()

    sig = _base()
    sig.safety_signatures["CollectiveOfflineSignature"] = "DEADBEEF"
    seen.update(_codes(base, sig))

    f_addr = _base()
    _module(f_addr).features["ProfiSafe"]["FDestinationAddress"] = 1
    seen.update(_codes(base, f_addr))

    dev_added = _base()
    dev_added.devices.append(DeviceNode(name="NEW_DEVICE"))
    seen.update(_codes(base, dev_added))
    seen.update(_codes(dev_added, base))

    mod_added = _base()
    mod_added.devices[0].items[0].children.append(
        DeviceItemNode(name="EXTRA", path="IO_STATION_1/Rail/EXTRA")
    )
    seen.update(_codes(base, mod_added))
    seen.update(_codes(mod_added, base))

    moved = _base()
    _module(moved).position = 7
    seen.update(_codes(base, moved))

    type_name = _base()
    _module(type_name).type_name = "Something Else"
    seen.update(_codes(base, type_name))

    order_fw = _base()
    _module(order_fw).order_number = "X"
    _module(order_fw).firmware = "X"
    seen.update(_codes(base, order_fw))

    attr = _base()
    _module(attr).attributes["SomeParameter"] = 999
    seen.update(_codes(base, attr))

    unreadable_item = copy.deepcopy(base)
    _module(unreadable_item).attributes.pop("SomeParameter")
    _module(unreadable_item).unreadable.append(UnreadableAttribute(name="SomeParameter", reason="x"))
    seen.update(_codes(base, unreadable_item))

    reason_change = _base()
    reason_mod = _module(reason_change)
    reason_mod.unreadable = [
        UnreadableAttribute(name=u.name, reason="communication timeout") for u in reason_mod.unreadable
    ]
    seen.update(_codes(base, reason_change))

    addr = _base()
    _module(addr).addresses[0] = type(_module(addr).addresses[0])(start=1, length=1, io_type="Input")
    seen.update(_codes(base, addr))

    feature = _base()
    _module(feature).features["ProfiSafe"]["SomeOtherKey"] = 1
    seen.update(_codes(base, feature))

    volatile = _base()
    volatile.volatile_excluded = ["Something"]
    seen.update(_codes(base, volatile))

    dev_type = _base()
    dev_type.devices[0].type_identifier = "X"
    seen.update(_codes(base, dev_type))

    dev_unreadable = copy.deepcopy(base)
    dev_unreadable.devices[0].unreadable.append(UnreadableAttribute(name="AnotherAttribute", reason="x"))
    seen.update(_codes(base, dev_unreadable))

    subnet = _base()
    subnet.subnets.append(SubnetInfo(name="PN_2", type="Ethernet"))
    seen.update(_codes(base, subnet))

    name = _base()
    name.project_name = "other"
    seen.update(_codes(base, name))

    assert seen == set(_TITLES)
