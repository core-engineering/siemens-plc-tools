"""Write a snapshot as a deterministic YAML tree.

Two dumps of an unchanged project must be byte-identical: a dump that shifts on
its own turns every diff into noise and defeats the whole package.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from plc_hw.model import DeviceItemNode, DeviceNode, ProjectSnapshot
from plc_hw.normalize import disambiguate, slugify

#: Written at the dump root. Its presence is the only authority to delete.
MARKER = ".plc-hw-dump"

#: Bumped when the on-disk layout changes in a way readers must know about.
FORMAT_VERSION = 1

_YAML_KWARGS: dict[str, Any] = {
    "sort_keys": True,
    "default_flow_style": False,
    "allow_unicode": True,
    "width": 1 << 30,
}


class DumpRootError(Exception):
    """The target directory is not safe to write a dump into."""


def write_dump(snapshot: ProjectSnapshot, root: Path) -> list[Path]:
    """Write ``snapshot`` under ``root``, pruning anything left over.

    Parameters
    ----------
    snapshot : ProjectSnapshot
        The configuration to write.
    root : Path
        Dump root. Must be missing, empty, or already a plc-hw dump.

    Returns
    -------
    list[Path]
        Every file written, in write order.

    Raises
    ------
    DumpRootError
        If ``root`` holds content this package did not create. Pointing ``--out``
        at an arbitrary directory must never delete its contents.
    """
    _check_root(root)
    root.mkdir(parents=True, exist_ok=True)

    written = [_write(root / MARKER, {"format_version": FORMAT_VERSION})]
    written.append(
        _write(
            root / "_project.yaml",
            {
                "project_name": snapshot.project_name,
                "subnets": [asdict(s) for s in snapshot.subnets],
                "safety_signatures": snapshot.safety_signatures,
                "volatile_excluded": snapshot.volatile_excluded,
            },
        )
    )

    # Module slugs are disambiguated within a rack; device directories need the
    # same guarantee one level up, or two devices whose names slugify identically
    # (``A/B`` and ``A.B``, or a pure case difference on a case-folding
    # filesystem) would share one directory and overwrite each other's files.
    device_slugs = disambiguate([slugify(device.name) for device in snapshot.devices])
    for device, slug in zip(snapshot.devices, device_slugs, strict=True):
        written.extend(_write_device(root / slug, device))

    _prune(root, set(written))
    return written


def _check_root(root: Path) -> None:
    """Refuse a root this package did not create."""
    if not root.exists():
        return
    if not root.is_dir():
        raise DumpRootError(f"{root} is not a directory")
    if any(root.iterdir()) and not (root / MARKER).exists():
        raise DumpRootError(
            f"{root} is not a plc-hw dump (no {MARKER}) and is not empty; "
            "refusing to write, since a dump prunes files it did not create"
        )


def _write_device(directory: Path, device: DeviceNode) -> list[Path]:
    """Write one device directory: the device file plus one file per module.

    Parameters
    ----------
    directory : Path
        The device's already-disambiguated directory. Computed by the caller,
        not derived here, so this function never has to re-decide identity.
    device : DeviceNode
        The device to write.
    """
    directory.mkdir(parents=True, exist_ok=True)
    written = [
        _write(
            directory / "_device.yaml",
            {
                "name": device.name,
                "type_identifier": device.type_identifier,
                "racks": [
                    {"index": i, **_item_to_dict(rack, include_children=False)}
                    for i, rack in enumerate(device.items)
                ],
                "unreadable": [asdict(u) for u in device.unreadable],
            },
        )
    ]
    for rack_index, rack in enumerate(device.items):
        slugs = disambiguate([slugify(m.name) for m in rack.children])
        for position, (module, slug) in enumerate(zip(rack.children, slugs, strict=True)):
            name = f"{rack_index:02d}-{position:02d}-{slug}.yaml"
            written.append(_write(directory / name, _item_to_dict(module)))
    return written


def _item_to_dict(item: DeviceItemNode, include_children: bool = True) -> dict[str, Any]:
    """Render one device item, children nested rather than split into files.

    Parameters
    ----------
    item : DeviceItemNode
        The item to render.
    include_children : bool
        When false, the ``children`` key is omitted entirely -- never written
        as an empty list. A rack's modules live in their own files, and an
        empty list here would be indistinguishable from "this rack has no
        modules" instead of "no children recorded in this payload".
    """
    payload: dict[str, Any] = {
        "name": item.name,
        "path": item.path,
        "position": item.position,
        "type_name": item.type_name,
        "order_number": item.order_number,
        "firmware": item.firmware,
        "addresses": [asdict(a) for a in item.addresses],
        "attributes": item.attributes,
        "features": item.features,
        "unreadable": [asdict(u) for u in item.unreadable],
    }
    if include_children:
        payload["children"] = [_item_to_dict(child) for child in item.children]
    return payload


def _write(path: Path, payload: dict[str, Any]) -> Path:
    """Serialise one file with the fixed, deterministic YAML settings."""
    text = yaml.safe_dump(payload, **_YAML_KWARGS)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _prune(root: Path, keep: set[Path]) -> None:
    """Delete YAML this run did not write, then any directory left empty."""
    for path in sorted(root.rglob("*.yaml"), reverse=True):
        if path not in keep:
            path.unlink()
    for directory in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
