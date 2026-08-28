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

#: A device's own attribute set, read through the same gap-recording discipline
#: as an item's -- a device is not exempt from the "every gap gets a reason"
#: rule just because DeviceNode used to have nowhere to put one.
_DEVICE_ATTRIBUTES = ("TypeIdentifier",)


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
    devices = [_walk_device(source, ref, volatile) for ref in sorted(source.devices(), key=lambda r: r.name)]
    return ProjectSnapshot(
        project_name=source.project_name(),
        subnets=sorted(source.subnets(), key=lambda s: s.name),
        devices=devices,
        safety_signatures=dict(sorted(source.safety_signatures().items())),
        volatile_excluded=sorted(volatile),
    )


def _walk_device(source: HardwareSource, ref: NodeRef, volatile: Sequence[str]) -> DeviceNode:
    """Read one device: its own attributes, then everything plugged into it."""
    requested = [name for name in _DEVICE_ATTRIBUTES if name not in volatile]
    raw = source.attributes(ref, requested)

    # Same discipline as an item: what was requested and did not come back is
    # recorded with its reason, never silently dropped.
    unreadable = [
        UnreadableAttribute(name=name, reason=source.attribute_error(ref, name))
        for name in requested
        if name not in raw
    ]
    items = [_walk_item(source, child, ref.name, volatile) for child in source.device_items(ref)]
    return DeviceNode(
        name=ref.name,
        type_identifier=str(format_value(raw.get("TypeIdentifier", ""))),
        items=sorted(items, key=_item_sort_key),
        unreadable=sorted(unreadable, key=lambda u: u.name),
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
    # Deduplicated, order-preserving: a name advertised twice must be recorded
    # at most once if it fails to read, never doubled.
    wanted = list(dict.fromkeys(info.name for info in infos if info.name not in volatile))
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
    children = [_walk_item(source, child, path, volatile) for child in source.device_items(ref)]
    node = DeviceItemNode(
        name=ref.name,
        path=path,
        position=int(position) if isinstance(position, int | str) and str(position).isdigit() else None,
        type_name=str(format_value(raw.pop("TypeName", ""))),
        order_number=strip_order_number_prefix(str(format_value(raw.pop("TypeIdentifier", "")))),
        firmware=str(format_value(raw.pop("FirmwareVersion", ""))),
        attributes={name: format_value(raw[name]) for name in sorted(raw)},
        addresses=list(source.addresses(ref)),
        features={
            feature: {key: format_value(value) for key, value in sorted(values.items())}
            for feature, values in sorted(source.features(ref).items())
        },
        unreadable=sorted(unreadable, key=lambda u: u.name),
        children=sorted(children, key=_item_sort_key),
    )
    return node


def _item_sort_key(item: DeviceItemNode) -> tuple[bool, int, str]:
    """Order racks and modules per spec S6.4: by ``(position, name)``.

    A missing ``position`` sorts last, deterministically, rather than raising
    on a comparison against ``None`` -- ``HardwareSource.device_items()``
    gives no ordering guarantee, so the on-disk order (and the writer's
    filename index, which is the list index) must not depend on whatever
    order Openness happens to enumerate children in.
    """
    return (item.position is None, item.position or 0, item.name)


__all__ = ["walk_project"]
