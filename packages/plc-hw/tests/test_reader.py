"""Reading a dump tree back into a snapshot."""

from __future__ import annotations

from pathlib import Path

import pytest

from plc_hw.model import (
    DeviceItemNode,
    DeviceNode,
    ProjectSnapshot,
    UnreadableAttribute,
)
from plc_hw.reader import DumpReadError, read_dump
from plc_hw.testing import FakeItem, FakeSource, build_fake_source
from plc_hw.walk import walk_project
from plc_hw.writer import MARKER, write_dump


def test_round_trip_preserves_the_snapshot(tmp_path: Path) -> None:
    original = walk_project(build_fake_source())
    write_dump(original, tmp_path)
    assert read_dump(tmp_path) == original


def test_round_trip_is_stable_across_a_rewrite(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    write_dump(walk_project(build_fake_source()), first)
    write_dump(read_dump(first), second)
    assert (first / "_project.yaml").read_bytes() == (second / "_project.yaml").read_bytes()


def test_a_missing_root_is_reported_clearly(tmp_path: Path) -> None:
    with pytest.raises(DumpReadError, match="does not exist"):
        read_dump(tmp_path / "nope")


def test_a_directory_without_the_marker_is_reported_clearly(tmp_path: Path) -> None:
    (tmp_path / "_project.yaml").write_text("project_name: x\n")
    with pytest.raises(DumpReadError, match="not a plc-hw dump"):
        read_dump(tmp_path)


def test_a_newer_format_version_is_refused(tmp_path: Path) -> None:
    write_dump(walk_project(build_fake_source()), tmp_path)
    (tmp_path / MARKER).write_text("format_version: 99\n")
    with pytest.raises(DumpReadError, match="format version 99"):
        read_dump(tmp_path)


def test_invalid_yaml_in_a_module_file_is_reported_clearly(tmp_path: Path) -> None:
    write_dump(walk_project(build_fake_source()), tmp_path)
    module = next((tmp_path / "IO_STATION_1").glob("00-00-*.yaml"))
    module.write_text("name: [unclosed\n")
    with pytest.raises(DumpReadError, match="not valid YAML"):
        read_dump(tmp_path)


def test_a_module_naming_a_nonexistent_rack_index_is_reported_clearly(tmp_path: Path) -> None:
    write_dump(walk_project(build_fake_source()), tmp_path)
    device_dir = tmp_path / "IO_STATION_1"
    good_module = next(device_dir.glob("00-00-*.yaml"))
    (device_dir / "99-00-bogus.yaml").write_text(good_module.read_text())
    with pytest.raises(DumpReadError, match="declares 1 rack"):
        read_dump(tmp_path)


def test_a_module_filename_without_a_rack_index_is_reported_clearly(tmp_path: Path) -> None:
    write_dump(walk_project(build_fake_source()), tmp_path)
    device_dir = tmp_path / "IO_STATION_1"
    good_module = next(device_dir.glob("00-00-*.yaml"))
    (device_dir / "xx-00-bogus.yaml").write_text(good_module.read_text())
    with pytest.raises(DumpReadError, match="does not start with a rack index"):
        read_dump(tmp_path)


def test_a_racks_full_payload_survives_the_round_trip(tmp_path: Path) -> None:
    """A rack is not just a name -- it carries a real Openness payload.

    Built directly, not through the shared fixture: ``build_fake_source``'s
    racks carry no attributes and nothing unreadable, so a reader that dropped
    the rack payload entirely would still pass the plain round-trip test.
    """
    module = DeviceItemNode(
        name="F-DI",
        path="STATION/Rail/F-DI",
        type_name="F-DI 8x24VDC HF",
        order_number="6ES7 136-6BA01-0CA0",
    )
    rack = DeviceItemNode(
        name="Rail",
        path="STATION/Rail",
        position=0,
        type_name="Rack",
        order_number="6ES7 590-1AE80-0AA0",
        firmware="V1.0",
        attributes={"SomeRackAttribute": "value"},
        unreadable=[UnreadableAttribute(name="LockedRackAttribute", reason="not accessible")],
        children=[module],
    )
    device = DeviceNode(name="STATION", type_identifier="OrderNumber:X", items=[rack])
    original = ProjectSnapshot(project_name="project-A", devices=[device])

    write_dump(original, tmp_path)
    restored = read_dump(tmp_path)

    assert restored == original
    assert restored.devices[0].items[0].order_number == "6ES7 590-1AE80-0AA0"


def test_a_devices_unreadable_attributes_survive_the_round_trip(tmp_path: Path) -> None:
    with_gap = DeviceNode(
        name="STATION",
        type_identifier="",
        unreadable=[UnreadableAttribute(name="TypeIdentifier", reason="not accessible in this context")],
    )
    without_gap = DeviceNode(name="PLC", type_identifier="OrderNumber:Y")
    original = ProjectSnapshot(project_name="project-A", devices=[without_gap, with_gap])

    write_dump(original, tmp_path)
    restored = read_dump(tmp_path)

    assert restored == original
    assert restored.devices[0].unreadable == []
    assert restored.devices[1].unreadable == [
        UnreadableAttribute(name="TypeIdentifier", reason="not accessible in this context")
    ]


def test_a_rack_with_no_modules_survives_as_a_rack_with_no_children(tmp_path: Path) -> None:
    empty_rack = DeviceItemNode(name="Rail_1", path="PLC/Rail_1")
    device = DeviceNode(name="PLC", items=[empty_rack])
    original = ProjectSnapshot(project_name="project-A", devices=[device])

    write_dump(original, tmp_path)
    restored = read_dump(tmp_path)

    assert restored == original
    assert restored.devices[0].items[0].children == []


def test_disambiguated_device_directories_keep_verbatim_names(tmp_path: Path) -> None:
    """Two devices whose names slugify identically must round-trip by verbatim name.

    ``slugify`` maps ``/`` and ``.`` onto the same ``-``, so ``Cell.A`` and
    ``Cell/A`` both become ``Cell-A`` on disk. The slug is a filename, never the
    source of truth: the reader must recover both names exactly.
    """
    first = DeviceNode(name="Cell.A", type_identifier="OrderNumber:1")
    second = DeviceNode(name="Cell/A", type_identifier="OrderNumber:2")
    original = ProjectSnapshot(project_name="project-A", devices=[first, second])

    write_dump(original, tmp_path)
    restored = read_dump(tmp_path)

    assert restored == original
    assert {d.name for d in restored.devices} == {"Cell.A", "Cell/A"}


def test_device_order_survives_regardless_of_how_names_slugify(tmp_path: Path) -> None:
    """``walk_project`` orders devices by name; the directory slug must not override that.

    ``slugify`` maps a space onto ``-`` but leaves ``!`` untouched, so
    ``"Cell X"`` and ``"Cell!X"`` sort one way by name (space sorts before
    ``!``) and the other way by their directory slugs (``!`` sorts before
    ``-``). A reader that orders devices by directory slug instead of by name
    would come back reversed relative to what ``walk_project`` produced.
    """
    source = FakeSource(project="project-A", devices=[FakeItem(name="Cell X"), FakeItem(name="Cell!X")])
    snapshot = walk_project(source)
    assert [d.name for d in snapshot.devices] == ["Cell X", "Cell!X"]

    write_dump(snapshot, tmp_path)
    restored = read_dump(tmp_path)

    assert restored == snapshot
    assert [d.name for d in restored.devices] == ["Cell X", "Cell!X"]
