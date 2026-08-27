"""Turn a HardwareSource into a ProjectSnapshot.

This is where the interesting decisions live -- recursion, hoisting, ordering and
above all what happens to an attribute that cannot be read -- which is exactly
why the source boundary sits below it: all of this is testable without TIA.
"""

from __future__ import annotations

from collections.abc import Sequence

from plc_hw.model import (
    DeviceItemNode,
    DeviceNode,
    NodeRef,
    ProjectSnapshot,
    UnreadableAttribute,
)
from plc_hw.normalize import DEFAULT_VOLATILE, format_value, strip_order_number_prefix
from plc_hw.source import HardwareSource

_POSITION = "PositionNumber"


def walk_project(
    source: HardwareSource,
    volatile: Sequence[str] = DEFAULT_VOLATILE,
) -> ProjectSnapshot:
    """Read a whole project through ``source``.

    Parameters
    ----------
    source : HardwareSource
        Any implementation of the read protocol.
    volatile : Sequence[str]
        Attribute names to drop. Recorded in the snapshot so the dump says what
        it left out.

    Returns
    -------
    ProjectSnapshot
        The captured configuration.
    """
    devices = [
        DeviceNode(
            name=ref.name,
            type_identifier=str(source.attributes(ref, ["TypeIdentifier"]).get("TypeIdentifier", "")),
            items=[_walk_item(source, child, ref.name, volatile) for child in source.device_items(ref)],
        )
        for ref in sorted(source.devices(), key=lambda r: r.name)
    ]
    return ProjectSnapshot(
        project_name=source.project_name(),
        subnets=sorted(source.subnets(), key=lambda s: s.name),
        devices=devices,
        safety_signatures=dict(sorted(source.safety_signatures().items())),
        volatile_excluded=sorted(volatile),
    )


def _walk_item(
    source: HardwareSource,
    ref: NodeRef,
    parent_path: str,
    volatile: Sequence[str],
) -> DeviceItemNode:
    """Read one device item and everything beneath it."""
    path = f"{parent_path}/{ref.name}"
    infos = source.attribute_infos(ref)
    wanted = [info.name for info in infos if info.name not in volatile]
    raw = source.attributes(ref, wanted)

    # Every advertised attribute that did not come back is recorded with its
    # reason. Dropping it silently would read as "unchanged" on the next diff,
    # when it actually means "not read".
    unreadable = [
        UnreadableAttribute(name=name, reason=source.attribute_error(ref, name))
        for name in wanted
        if name not in raw
    ]

    position = raw.pop(_POSITION, None)
    node = DeviceItemNode(
        name=ref.name,
        path=path,
        position=int(position) if isinstance(position, int | str) and str(position).isdigit() else None,
        type_name=str(raw.pop("TypeName", "")),
        order_number=strip_order_number_prefix(str(raw.pop("TypeIdentifier", ""))),
        firmware=str(raw.pop("FirmwareVersion", "")),
        attributes={name: format_value(raw[name]) for name in sorted(raw)},
        addresses=list(source.addresses(ref)),
        features={
            feature: {key: format_value(value) for key, value in sorted(values.items())}
            for feature, values in sorted(source.features(ref).items())
        },
        unreadable=sorted(unreadable, key=lambda u: u.name),
        children=[_walk_item(source, child, path, volatile) for child in source.device_items(ref)],
    )
    return node


__all__ = ["walk_project"]
