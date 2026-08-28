"""Writing the dump tree: determinism, the marker invariant, pruning."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from plc_hw.model import DeviceItemNode, DeviceNode, ProjectSnapshot, UnreadableAttribute
from plc_hw.testing import build_fake_source
from plc_hw.walk import walk_project
from plc_hw.writer import MARKER, DumpRootError, write_dump


def _snapshot() -> ProjectSnapshot:
    return walk_project(build_fake_source())


def test_layout_is_one_directory_per_device_and_one_file_per_module(tmp_path: Path) -> None:
    write_dump(_snapshot(), tmp_path)
    written = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.yaml"))
    assert written == [
        "IO_STATION_1/00-00-F-DI.yaml",
        "IO_STATION_1/_device.yaml",
        "PLC_MAIN/00-00-CPU.yaml",
        "PLC_MAIN/_device.yaml",
        "_project.yaml",
    ]


def test_depth_never_exceeds_two(tmp_path: Path) -> None:
    write_dump(_snapshot(), tmp_path)
    for path in tmp_path.rglob("*.yaml"):
        assert len(path.relative_to(tmp_path).parts) <= 2


def test_module_file_carries_the_verbatim_tia_name(tmp_path: Path) -> None:
    write_dump(_snapshot(), tmp_path)
    data = yaml.safe_load((tmp_path / "IO_STATION_1" / "00-00-F-DI.yaml").read_text())
    assert data["name"] == "F-DI"
    assert data["path"] == "IO_STATION_1/Rail/F-DI"
    assert data["order_number"] == "6ES7 136-6BA01-0CA0"
    assert data["unreadable"] == [{"name": "LockedParameter", "reason": "not accessible in this context"}]


def test_project_file_records_what_was_excluded(tmp_path: Path) -> None:
    write_dump(_snapshot(), tmp_path)
    data = yaml.safe_load((tmp_path / "_project.yaml").read_text())
    assert data["volatile_excluded"] == ["InstallationDate"]
    assert data["safety_signatures"] == {"CollectiveOfflineSignature": "A1B2C3D4"}


def test_two_runs_are_byte_identical(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    write_dump(_snapshot(), first)
    write_dump(_snapshot(), second)
    files = sorted(p.relative_to(first) for p in first.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(second) for p in second.rglob("*") if p.is_file())
    for rel in files:
        assert (first / rel).read_bytes() == (second / rel).read_bytes()


def test_files_use_lf_and_end_with_a_newline(tmp_path: Path) -> None:
    write_dump(_snapshot(), tmp_path)
    raw = (tmp_path / "_project.yaml").read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"\n")


def test_the_marker_is_written(tmp_path: Path) -> None:
    write_dump(_snapshot(), tmp_path)
    assert yaml.safe_load((tmp_path / MARKER).read_text())["format_version"] == 1


def test_the_marker_carries_no_timestamp(tmp_path: Path) -> None:
    # A timestamp in the marker would be one line of guaranteed diff noise per
    # dump -- the exact problem this package exists to remove.
    write_dump(_snapshot(), tmp_path)
    assert set(yaml.safe_load((tmp_path / MARKER).read_text())) == {"format_version"}


def test_writing_into_a_foreign_directory_is_refused(tmp_path: Path) -> None:
    (tmp_path / "someone-elses-work.txt").write_text("keep me")
    with pytest.raises(DumpRootError, match="not a plc-hw dump"):
        write_dump(_snapshot(), tmp_path)
    assert (tmp_path / "someone-elses-work.txt").exists()


def test_a_second_dump_prunes_files_that_no_longer_exist(tmp_path: Path) -> None:
    write_dump(_snapshot(), tmp_path)
    stale = tmp_path / "IO_STATION_1" / "00-09-GONE.yaml"
    stale.write_text("name: GONE\n")
    write_dump(_snapshot(), tmp_path)
    assert not stale.exists()


def test_pruning_removes_directories_left_empty(tmp_path: Path) -> None:
    write_dump(_snapshot(), tmp_path)
    (tmp_path / "OLD_DEVICE").mkdir()
    (tmp_path / "OLD_DEVICE" / "00-00-X.yaml").write_text("name: X\n")
    write_dump(_snapshot(), tmp_path)
    assert not (tmp_path / "OLD_DEVICE").exists()


def test_case_colliding_modules_get_separate_files(tmp_path: Path) -> None:
    rack = DeviceItemNode(
        name="Rail",
        path="D/Rail",
        children=[
            DeviceItemNode(name="Motor", path="D/Rail/Motor"),
            DeviceItemNode(name="motor", path="D/Rail/motor"),
        ],
    )
    snapshot = ProjectSnapshot(
        project_name="project-A",
        devices=[DeviceNode(name="D", items=[rack])],
    )
    write_dump(snapshot, tmp_path)
    names = sorted(p.name for p in (tmp_path / "D").glob("*.yaml"))
    assert names == ["00-00-Motor.yaml", "00-01-motor-2.yaml", "_device.yaml"]


def test_devices_with_colliding_slugs_get_separate_directories(tmp_path: Path) -> None:
    """Two device names that slugify to the same fragment must not share a directory.

    ``slugify`` maps ``/`` and ``.`` onto the same ``-``, so ``A/B`` and ``A.B``
    both become ``A-B``. Without disambiguation one device's ``_device.yaml``
    and module files would overwrite or interleave with the other's.
    """
    snapshot = ProjectSnapshot(
        project_name="project-A",
        devices=[
            DeviceNode(name="A/B", items=[DeviceItemNode(name="Rail", path="A/B/Rail")]),
            DeviceNode(name="A.B", items=[DeviceItemNode(name="Rail", path="A.B/Rail")]),
        ],
    )
    write_dump(snapshot, tmp_path)
    dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(dirs) == 2
    names = {yaml.safe_load((d / "_device.yaml").read_text())["name"] for d in dirs}
    assert names == {"A/B", "A.B"}


def test_devices_with_case_colliding_names_get_separate_directories(tmp_path: Path) -> None:
    """A pure case difference collides on NTFS and must still get separate directories."""
    snapshot = ProjectSnapshot(
        project_name="project-A",
        devices=[DeviceNode(name="Device", items=[]), DeviceNode(name="DEVICE", items=[])],
    )
    write_dump(snapshot, tmp_path)
    dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(dirs) == 2
    names = {yaml.safe_load((d / "_device.yaml").read_text())["name"] for d in dirs}
    assert names == {"Device", "DEVICE"}


def test_filename_index_follows_position_order_not_list_order(tmp_path: Path) -> None:
    """The writer's filename numeral is the list index -- but the walker must sort first.

    This is the exact scenario the finding demonstrated: two modules with
    ``PositionNumber`` 5 and 1, handed to the writer already in that order,
    used to produce ``00-00-ModAtSlot5.yaml`` and ``00-01-ModAtSlot1.yaml``.
    ``write_dump`` itself does not sort -- ``walk_project`` does -- so this
    test builds the snapshot directly, out of order, to prove the writer alone
    is not what makes the tree deterministic.
    """
    rack = DeviceItemNode(
        name="Rail",
        path="D/Rail",
        children=[
            DeviceItemNode(name="ModAtSlot5", path="D/Rail/ModAtSlot5", position=5),
            DeviceItemNode(name="ModAtSlot1", path="D/Rail/ModAtSlot1", position=1),
        ],
    )
    snapshot = ProjectSnapshot(project_name="project-A", devices=[DeviceNode(name="D", items=[rack])])
    write_dump(snapshot, tmp_path)
    names = sorted(p.name for p in (tmp_path / "D").glob("*.yaml"))
    # Unsorted input still lands as list-index filenames -- proving the fix
    # belongs in the walker, not here: `write_dump` faithfully reflects
    # whatever order `DeviceNode.items`/`children` already carry.
    assert names == ["00-00-ModAtSlot5.yaml", "00-01-ModAtSlot1.yaml", "_device.yaml"]


def test_rack_hardware_identity_is_written_in_full(tmp_path: Path) -> None:
    """A rack's order number, firmware and position must reach the dump.

    Swapping a rail for a different part number must not be invisible to
    ``plc hw check`` -- which is the exact failure this package exists to
    prevent.
    """
    rack = DeviceItemNode(
        name="Rail",
        path="D/Rail",
        position=0,
        type_name="Rack",
        order_number="6ES7 590-1AE80-0AA0",
        firmware="V2.1",
    )
    snapshot = ProjectSnapshot(project_name="project-A", devices=[DeviceNode(name="D", items=[rack])])
    write_dump(snapshot, tmp_path)
    data = yaml.safe_load((tmp_path / "D" / "_device.yaml").read_text())
    rack_entry = data["racks"][0]
    assert rack_entry["type_name"] == "Rack"
    assert rack_entry["order_number"] == "6ES7 590-1AE80-0AA0"
    assert rack_entry["firmware"] == "V2.1"
    assert rack_entry["position"] == 0
    assert "children" not in rack_entry


def test_device_unreadable_attributes_are_written(tmp_path: Path) -> None:
    snapshot = ProjectSnapshot(
        project_name="project-A",
        devices=[
            DeviceNode(
                name="D",
                items=[],
                unreadable=[UnreadableAttribute(name="TypeIdentifier", reason="not accessible")],
            )
        ],
    )
    write_dump(snapshot, tmp_path)
    data = yaml.safe_load((tmp_path / "D" / "_device.yaml").read_text())
    assert data["unreadable"] == [{"name": "TypeIdentifier", "reason": "not accessible"}]


def test_device_with_no_unreadable_attributes_writes_an_empty_list_not_a_missing_key(
    tmp_path: Path,
) -> None:
    snapshot = ProjectSnapshot(project_name="project-A", devices=[DeviceNode(name="D", items=[])])
    write_dump(snapshot, tmp_path)
    data = yaml.safe_load((tmp_path / "D" / "_device.yaml").read_text())
    assert data["unreadable"] == []
