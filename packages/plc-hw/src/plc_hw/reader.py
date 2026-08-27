"""Read a dump tree back into a snapshot, so diffs need no TIA."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from plc_hw.model import (
    AddressRange,
    DeviceItemNode,
    DeviceNode,
    ProjectSnapshot,
    SubnetInfo,
    UnreadableAttribute,
)
from plc_hw.writer import FORMAT_VERSION, MARKER


class DumpReadError(Exception):
    """The directory is not a readable plc-hw dump."""


def read_dump(root: Path) -> ProjectSnapshot:
    """Load the dump written under ``root``.

    Parameters
    ----------
    root : Path
        Dump root.

    Returns
    -------
    ProjectSnapshot
        The snapshot the tree encodes. Its ``devices`` come back sorted by
        their verbatim name, matching the order ``walk_project`` produces: the
        directory slug is a filename, not an ordering key, and two device names
        can slugify to slugs that sort differently from the names themselves
        (``slugify`` maps a space onto ``-`` but leaves ``!`` untouched, for
        instance).

    Raises
    ------
    DumpReadError
        If the root is missing, unmarked, or written by a newer format.
    """
    if not root.exists():
        raise DumpReadError(f"{root} does not exist")
    marker = root / MARKER
    if not marker.exists():
        raise DumpReadError(f"{root} is not a plc-hw dump (no {MARKER})")
    version = int(yaml.safe_load(marker.read_text(encoding="utf-8"))["format_version"])
    if version > FORMAT_VERSION:
        raise DumpReadError(
            f"{root} was written with format version {version}; this build reads up to {FORMAT_VERSION}"
        )

    project = _load(root / "_project.yaml")
    devices = sorted(
        (_read_device(directory) for directory in root.iterdir() if directory.is_dir()),
        key=lambda device: device.name,
    )
    return ProjectSnapshot(
        project_name=str(project["project_name"]),
        subnets=[SubnetInfo(**s) for s in project["subnets"]],
        devices=devices,
        safety_signatures=dict(project["safety_signatures"]),
        volatile_excluded=list(project["volatile_excluded"]),
    )


def _read_device(directory: Path) -> DeviceNode:
    """Rebuild one device, regrouping its module files under their racks.

    Each rack entry in ``_device.yaml`` carries a full item payload -- the same
    shape a module file uses, minus ``children`` -- plus an ``index`` key that
    is not a :class:`~plc_hw.model.DeviceItemNode` field and is discarded here
    rather than passed through.
    """
    meta = _load(directory / "_device.yaml")
    racks = [_read_item({k: v for k, v in rack.items() if k != "index"}) for rack in meta["racks"]]
    for path in sorted(p for p in directory.glob("*.yaml") if p.name != "_device.yaml"):
        prefix = path.name.split("-", 1)[0]
        try:
            rack_index = int(prefix)
        except ValueError as exc:
            raise DumpReadError(f"{path} does not start with a rack index") from exc
        if not 0 <= rack_index < len(racks):
            raise DumpReadError(
                f"{path} names rack index {rack_index}, but {directory} declares {len(racks)} rack(s)"
            )
        racks[rack_index].children.append(_read_item(_load(path)))
    return DeviceNode(
        name=str(meta["name"]),
        type_identifier=str(meta["type_identifier"]),
        items=racks,
        unreadable=[UnreadableAttribute(**u) for u in meta["unreadable"]],
    )


def _read_item(data: dict[str, Any]) -> DeviceItemNode:
    """Rebuild one device item and everything nested inside it.

    ``children`` is read with a default of an empty list rather than a direct
    lookup: a rack's own payload deliberately omits the key -- its modules live
    in separate files -- and that absence means "not recorded here", not "this
    rack has no modules".
    """
    return DeviceItemNode(
        name=str(data["name"]),
        path=str(data["path"]),
        position=data["position"],
        type_name=str(data["type_name"]),
        order_number=str(data["order_number"]),
        firmware=str(data["firmware"]),
        attributes=dict(data["attributes"]),
        addresses=[AddressRange(**a) for a in data["addresses"]],
        features={k: dict(v) for k, v in data["features"].items()},
        unreadable=[UnreadableAttribute(**u) for u in data["unreadable"]],
        children=[_read_item(c) for c in data.get("children", [])],
    )


def _load(path: Path) -> dict[str, Any]:
    """Parse one dump file.

    Raises
    ------
    DumpReadError
        If the file is missing, is not valid YAML, or does not parse to a
        mapping. A raw ``yaml.YAMLError`` never escapes this function: every
        malformed input on the read path must surface through the one error
        type ``read_dump`` documents.
    """
    if not path.exists():
        raise DumpReadError(f"{path} is missing from the dump")
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DumpReadError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise DumpReadError(f"{path} is not a mapping")
    return parsed


__all__ = ["DumpReadError", "read_dump"]
