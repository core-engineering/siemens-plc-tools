"""Capture a real source once, replay it forever.

This is what gives the pure modules realistic test data without TIA, and it is
what lets the package be developed from a machine that has no TIA at all.

Anonymisation is on by default: this repository is public, and a raw recording
carries device names, plant tags and the project name.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from plc_hw.model import AddressRange, AttributeInfo, NodeRef, SubnetInfo
from plc_hw.source import HardwareSource

#: Attribute names whose string values are kept verbatim. Everything else that is a
#: string is pseudonymised.
#:
#: An allow-list, not a deny-list: this repository is public, and a deny-list protects
#: only the fields someone thought of, leaving every field added later exposed by default.
PRESERVED_VALUE_ATTRIBUTES = ("TypeName", "TypeIdentifier", "FirmwareVersion")

#: Fixture channels deliberately left verbatim: vendor vocabulary that the walker and
#: differ key their behaviour on. Pseudonymising these would leave a fixture that
#: replays into a structure no consumer can interpret.
#:
#: Named explicitly so that adding a channel is a decision someone makes, not a default
#: something inherits.
PRESERVED_STRUCTURAL_CHANNELS = (
    "attribute names",
    "feature names and inner keys",
    "address io_type",
    "subnet type",
    "safety signature keys and values",
)


class RecordingSource:
    """Wrap a HardwareSource and accumulate everything it was asked.

    Parameters
    ----------
    inner : HardwareSource
        The source to record. Every call is forwarded to it and its result kept.
    """

    def __init__(self, inner: HardwareSource) -> None:
        self._inner = inner
        self._f: dict[str, Any] = {
            "project_name": "",
            "subnets": [],
            "devices": [],
            "device_items": {},
            "attribute_infos": {},
            "attributes": {},
            "attribute_error": {},
            "addresses": {},
            "features": {},
            "safety_signatures": {},
        }

    def fixture(self) -> dict[str, Any]:
        """Return the accumulated fixture.

        Returns
        -------
        dict[str, Any]
            Everything recorded so far, keyed by :class:`~plc_hw.source.HardwareSource`
            member name.
        """
        return self._f

    def project_name(self) -> str:
        """Record and return the inner source's project name."""
        self._f["project_name"] = self._inner.project_name()
        return str(self._f["project_name"])

    def subnets(self) -> list[SubnetInfo]:
        """Record and return the inner source's subnets."""
        result = self._inner.subnets()
        self._f["subnets"] = [asdict(s) for s in result]
        return result

    def devices(self) -> list[NodeRef]:
        """Record and return the inner source's devices."""
        result = self._inner.devices()
        self._f["devices"] = [asdict(r) for r in result]
        return result

    def device_items(self, parent: NodeRef) -> list[NodeRef]:
        """Record and return ``parent``'s direct children."""
        result = self._inner.device_items(parent)
        self._f["device_items"][parent.key] = [asdict(r) for r in result]
        return result

    def attribute_infos(self, item: NodeRef) -> list[AttributeInfo]:
        """Record and return ``item``'s advertised attributes."""
        result = self._inner.attribute_infos(item)
        self._f["attribute_infos"][item.key] = [asdict(i) for i in result]
        return result

    def attributes(self, item: NodeRef, names: Sequence[str]) -> dict[str, object]:
        """Record and return the named attributes that could be read on ``item``."""
        result = self._inner.attributes(item, names)
        self._f["attributes"].setdefault(item.key, {}).update(result)
        return result

    def attribute_error(self, item: NodeRef, name: str) -> str:
        """Record and return why ``name`` could not be read on ``item``."""
        result = self._inner.attribute_error(item, name)
        self._f["attribute_error"].setdefault(item.key, {})[name] = result
        return result

    def addresses(self, item: NodeRef) -> list[AddressRange]:
        """Record and return ``item``'s address ranges."""
        result = self._inner.addresses(item)
        self._f["addresses"][item.key] = [asdict(a) for a in result]
        return result

    def features(self, item: NodeRef) -> dict[str, dict[str, object]]:
        """Record and return ``item``'s features."""
        result = self._inner.features(item)
        self._f["features"][item.key] = result
        return result

    def safety_signatures(self) -> dict[str, str]:
        """Record and return the project's safety signatures."""
        result = self._inner.safety_signatures()
        self._f["safety_signatures"] = result
        return result


class ReplaySource:
    """A HardwareSource served entirely from a recorded fixture.

    Parameters
    ----------
    fixture : dict[str, Any]
        A fixture produced by :meth:`RecordingSource.fixture`, :func:`load_fixture`
        or :func:`anonymise`.
    """

    def __init__(self, fixture: dict[str, Any]) -> None:
        self._f = fixture

    def project_name(self) -> str:
        """Return the recorded project name."""
        return str(self._f["project_name"])

    def subnets(self) -> list[SubnetInfo]:
        """Return the recorded subnets."""
        return [SubnetInfo(**s) for s in self._f["subnets"]]

    def devices(self) -> list[NodeRef]:
        """Return the recorded devices."""
        return [NodeRef(**r) for r in self._f["devices"]]

    def device_items(self, parent: NodeRef) -> list[NodeRef]:
        """Return ``parent``'s recorded direct children."""
        return [NodeRef(**r) for r in self._f["device_items"].get(parent.key, [])]

    def attribute_infos(self, item: NodeRef) -> list[AttributeInfo]:
        """Return ``item``'s recorded advertised attributes."""
        return [AttributeInfo(**i) for i in self._f["attribute_infos"].get(item.key, [])]

    def attributes(self, item: NodeRef, names: Sequence[str]) -> dict[str, object]:
        """Return the named attributes that were recorded as readable on ``item``."""
        stored = self._f["attributes"].get(item.key, {})
        return {n: stored[n] for n in names if n in stored}

    def attribute_error(self, item: NodeRef, name: str) -> str:
        """Return the recorded reason ``name`` could not be read on ``item``."""
        return str(self._f["attribute_error"].get(item.key, {}).get(name, "unknown"))

    def addresses(self, item: NodeRef) -> list[AddressRange]:
        """Return ``item``'s recorded address ranges."""
        return [AddressRange(**a) for a in self._f["addresses"].get(item.key, [])]

    def features(self, item: NodeRef) -> dict[str, dict[str, object]]:
        """Return ``item``'s recorded features."""
        return dict(self._f["features"].get(item.key, {}))

    def safety_signatures(self) -> dict[str, str]:
        """Return the recorded safety signatures."""
        return dict(self._f["safety_signatures"])


def _rename_key(key: str, names: dict[str, str]) -> str:
    """Rewrite a ``/``-joined path, renaming every segment found in ``names``."""
    return "/".join(names.get(part, part) for part in key.split("/"))


def _pseudonymise(values: set[str], prefix: str) -> dict[str, str]:
    """Assign one stable pseudonym per distinct value.

    Values are numbered by their position in sorted order, never by dict or set
    iteration order, so the same fixture always yields the same numbering run to
    run regardless of hash randomisation.

    Parameters
    ----------
    values : set[str]
        Distinct strings to pseudonymise.
    prefix : str
        Pseudonym family: ``"text"``, ``"reason"`` or ``"subnet"``.

    Returns
    -------
    dict[str, str]
        Original value to pseudonym, e.g. ``{"hello": "text-01"}``.
    """
    return {value: f"{prefix}-{i:02d}" for i, value in enumerate(sorted(values), start=1)}


def anonymise(fixture: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Rename every identifying string out of a fixture.

    This is an allow-list over string values, not a deny-list: everywhere a string
    can carry a customer or site identity, it is replaced by a stable pseudonym
    unless it is named in :data:`PRESERVED_VALUE_ATTRIBUTES`, is a device or item
    name's structural counterpart (a type name, order number or firmware
    version), or falls into one of the channels named in
    :data:`PRESERVED_STRUCTURAL_CHANNELS`.

    Renamed: the project name; every device and item name (and the path keys
    built from them); every attribute value that is a string, unless its
    attribute name is preserved; every feature's inner string values; every
    ``attribute_error`` reason; every subnet ``name``.

    Preserved by value-allow-list: ``TypeName``, ``TypeIdentifier`` and
    ``FirmwareVersion`` attribute values.

    Preserved structural channels (see :data:`PRESERVED_STRUCTURAL_CHANNELS`),
    each kept verbatim by decision, not by omission:

    - **Attribute names**, and the string keys of the ``attributes`` and
      ``attribute_infos`` dicts. These come from the Openness device type model,
      not from anything a customer authors, and the walker keys its entire
      behaviour on them -- ``TypeName``, ``PositionNumber``, the volatile filter,
      the hoisted identity fields. Pseudonymising them would leave a fixture the
      walker cannot interpret, not a scrubbed one.
    - **Feature names and their inner keys** (``ProfiSafe``, ``NetworkInterface``,
      ``FDestinationAddress``, ...). These come from the vendor's GSDML file, and
      ``walk_project`` and callers select behaviour by feature name.
    - **``AddressRange.io_type``**. ``Input``/``Output`` (or whatever else TIA
      reports -- see :class:`~plc_hw.model.AddressRange`) is vocabulary the differ
      compares directly, not customer text.
    - **``SubnetInfo.type``**. ``Ethernet``/``Profibus`` is Siemens vocabulary.
    - **``safety_signatures`` keys and values**. Signature *type* names are fixed
      TIA vocabulary; the values are hex digests that carry no names, and the
      differ's tests depend on seeing them unchanged.

    This is a judgment call about what counts as vendor vocabulary rather than
    customer data, not a certainty: it holds for every case this package has
    encountered so far (Siemens Openness attribute and feature names, GSDML
    vocabulary), but a future source that stuffs a free-text comment into, say, a
    feature's inner key rather than its value would slip through it. Anyone
    adding a new structural channel should extend
    :data:`PRESERVED_STRUCTURAL_CHANNELS` and this docstring explicitly, rather
    than relying on it having been safe so far.

    Also preserved: every non-string attribute and feature *value* (ints, floats,
    bools, ``None``); subnet ``number``; ``addresses`` (``start``/``length``,
    structural integers, plus the ``io_type`` channel above).

    Parameters
    ----------
    fixture : dict[str, Any]
        A recording, as produced by :meth:`RecordingSource.fixture` or
        :func:`load_fixture`.

    Returns
    -------
    tuple[dict[str, Any], dict[str, str]]
        The scrubbed fixture and the flat mapping of every original string to
        its pseudonym -- names, texts, reasons and subnets alike -- so a human
        can audit exactly what was replaced. The scrubbed fixture shares no
        mutable structure with ``fixture``.
    """
    device_names = sorted({r["name"] for r in fixture["devices"]})
    item_names = sorted(
        {r["name"] for refs in fixture["device_items"].values() for r in refs} - set(device_names)
    )
    names: dict[str, str] = {name: f"device-{i:02d}" for i, name in enumerate(device_names, start=1)}
    names.update({name: f"item-{i:02d}" for i, name in enumerate(item_names, start=1)})

    def rename_key(key: str) -> str:
        return _rename_key(key, names)

    text_values = {
        value
        for values in fixture["attributes"].values()
        for name, value in values.items()
        if name not in PRESERVED_VALUE_ATTRIBUTES and isinstance(value, str)
    }
    text_values |= {
        value
        for features in fixture["features"].values()
        for inner in features.values()
        for value in inner.values()
        if isinstance(value, str)
    }
    text_map = _pseudonymise(text_values, "text")

    reason_values = {reason for reasons in fixture["attribute_error"].values() for reason in reasons.values()}
    reason_map = _pseudonymise(reason_values, "reason")

    subnet_values = {subnet["name"] for subnet in fixture["subnets"]}
    subnet_map = _pseudonymise(subnet_values, "subnet")

    mapping: dict[str, str] = dict(names)
    mapping.setdefault(str(fixture["project_name"]), "project-A")
    mapping.update(text_map)
    mapping.update(reason_map)
    mapping.update(subnet_map)

    out: dict[str, Any] = {
        "project_name": "project-A",
        "subnets": [
            {"name": subnet_map[s["name"]], "type": s["type"], "number": s["number"]}
            for s in fixture["subnets"]
        ],
        "devices": [{"key": rename_key(r["key"]), "name": names[r["name"]]} for r in fixture["devices"]],
        "safety_signatures": dict(fixture["safety_signatures"]),
    }
    out["device_items"] = {
        rename_key(key): [{"key": rename_key(r["key"]), "name": names[r["name"]]} for r in refs]
        for key, refs in fixture["device_items"].items()
    }
    out["attribute_infos"] = {
        rename_key(key): [dict(info) for info in infos] for key, infos in fixture["attribute_infos"].items()
    }
    out["addresses"] = {
        rename_key(key): [dict(address) for address in addresses]
        for key, addresses in fixture["addresses"].items()
    }
    out["attribute_error"] = {
        rename_key(key): {name: reason_map[reason] for name, reason in reasons.items()}
        for key, reasons in fixture["attribute_error"].items()
    }
    out["features"] = {
        rename_key(key): {
            feature: {
                name: (text_map[value] if isinstance(value, str) else value) for name, value in inner.items()
            }
            for feature, inner in features.items()
        }
        for key, features in fixture["features"].items()
    }
    out["attributes"] = {
        rename_key(key): {
            name: (
                value if name in PRESERVED_VALUE_ATTRIBUTES or not isinstance(value, str) else text_map[value]
            )
            for name, value in values.items()
        }
        for key, values in fixture["attributes"].items()
    }
    return out, mapping


def save_fixture(fixture: dict[str, Any], path: Path) -> None:
    """Write a fixture as sorted, stable JSON.

    Parameters
    ----------
    fixture : dict[str, Any]
        The fixture to write.
    path : Path
        Destination file. Parent directories are created as needed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(fixture, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def load_fixture(path: Path) -> dict[str, Any]:
    """Read a fixture written by :func:`save_fixture`.

    Parameters
    ----------
    path : Path
        File to read.

    Returns
    -------
    dict[str, Any]
        The parsed fixture.
    """
    parsed: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return parsed


__all__ = [
    "PRESERVED_STRUCTURAL_CHANNELS",
    "PRESERVED_VALUE_ATTRIBUTES",
    "RecordingSource",
    "ReplaySource",
    "anonymise",
    "load_fixture",
    "save_fixture",
]
