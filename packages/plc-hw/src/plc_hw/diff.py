"""Compare two snapshots and say what moved.

Findings carry a rule code so the fine grain survives the three-level severity
scale. The exit code is driven by findings existing at all, not by their
severity: a WARNING here still fails ``plc hw check``.
"""

from __future__ import annotations

from dataclasses import asdict

from plc_core.reporting import Finding, Report, ReportSection, Severity

from plc_hw.model import DeviceItemNode, DeviceNode, ProjectSnapshot, SubnetInfo, UnreadableAttribute

#: Attribute and feature keys that carry a PROFIsafe address. A change here is
#: never a routine parameter edit.
_F_ADDRESS_MARKERS = ("FSourceAddress", "FDestinationAddress")

_TITLES = {
    "HW001": "Safety signature changed",
    "HW002": "PROFIsafe address changed",
    "HW003": "Device added",
    "HW004": "Device removed",
    "HW005": "Module added",
    "HW006": "Module removed",
    "HW007": "Module moved",
    "HW008": "Order number changed",
    "HW009": "Firmware changed",
    "HW010": "Attribute changed",
    "HW011": "Attribute became unreadable",
    "HW012": "Address range changed",
    "HW013": "Feature changed",
    "HW014": "Volatile exclusion list changed",
    "HW015": "Subnet changed",
    "HW016": "Project name changed",
    "HW017": "Type name changed",
}

_ERRORS = frozenset(
    {"HW001", "HW002", "HW003", "HW004", "HW005", "HW006", "HW007", "HW008", "HW009", "HW017"}
)


def diff_snapshots(old: ProjectSnapshot, new: ProjectSnapshot) -> list[Finding]:
    """Compare two snapshots.

    Parameters
    ----------
    old, new : ProjectSnapshot
        Baseline and candidate.

    Returns
    -------
    list[Finding]
        Findings in a deterministic order: rule code, then location.
    """
    findings: list[Finding] = []
    findings.extend(_diff_project(old, new))
    findings.extend(_diff_devices(old.devices, new.devices))
    return sorted(findings, key=lambda f: (f.rule_code, f.location, f.context))


def build_report(findings: list[Finding]) -> Report:
    """Group findings into a report, one section per rule code.

    Parameters
    ----------
    findings : list[Finding]
        Findings produced by :func:`diff_snapshots`.

    Returns
    -------
    Report
        One section per rule code present in ``findings``, sorted by code.
    """
    sections: list[ReportSection] = []
    for code in sorted({f.rule_code for f in findings}):
        sections.append(
            ReportSection(
                title=f"{code} — {_TITLES[code]}",
                findings=[f for f in findings if f.rule_code == code],
            )
        )
    return Report(
        title="Hardware configuration diff",
        description="Semantic comparison of two plc-hw dumps.",
        sections=sections,
    )


def _finding(code: str, location: str, message: str, context: str = "") -> Finding:
    """Build one finding with the severity its code implies.

    Parameters
    ----------
    code : str
        Rule code. Must be a key of ``_TITLES``.
    location : str
        Where the change was found.
    message : str
        Human-readable description of the change.
    context : str
        Additional context, e.g. the attribute or field name.

    Returns
    -------
    Finding
        The finding, with severity looked up from ``_ERRORS``.
    """
    return Finding(
        title=_TITLES[code],
        severity=Severity.ERROR if code in _ERRORS else Severity.WARNING,
        message=message,
        location=location,
        rule_code=code,
        context=context,
    )


def _diff_project(old: ProjectSnapshot, new: ProjectSnapshot) -> list[Finding]:
    """Compare the project-level facts.

    Parameters
    ----------
    old, new : ProjectSnapshot
        Baseline and candidate.

    Returns
    -------
    list[Finding]
        Findings for safety signatures, the volatile-exclusion list, subnets
        and the project name.
    """
    findings: list[Finding] = []
    for name in sorted(set(old.safety_signatures) | set(new.safety_signatures)):
        before = old.safety_signatures.get(name, "<absent>")
        after = new.safety_signatures.get(name, "<absent>")
        if before != after:
            findings.append(_finding("HW001", "_project", f"{name}: {before} -> {after}", name))
    if old.volatile_excluded != new.volatile_excluded:
        findings.append(
            _finding(
                "HW014",
                "_project",
                f"{old.volatile_excluded} -> {new.volatile_excluded}",
                "volatile_excluded",
            )
        )
    findings.extend(_diff_subnets(old.subnets, new.subnets))
    if old.project_name != new.project_name:
        findings.append(
            _finding(
                "HW016",
                "_project",
                f"{old.project_name} -> {new.project_name}",
                "project_name",
            )
        )
    return findings


def _diff_subnets(old: list[SubnetInfo], new: list[SubnetInfo]) -> list[Finding]:
    """Compare two subnet lists, keyed by name.

    Parameters
    ----------
    old, new : list[SubnetInfo]
        Baseline and candidate subnet lists.

    Returns
    -------
    list[Finding]
        HW015 findings for a subnet added, removed, or changed in ``type`` or
        ``number``.
    """
    before = {s.name: s for s in old}
    after = {s.name: s for s in new}
    findings: list[Finding] = []
    for name in sorted(set(after) - set(before)):
        findings.append(_finding("HW015", "_project", f"subnet {name} is new", name))
    for name in sorted(set(before) - set(after)):
        findings.append(_finding("HW015", "_project", f"subnet {name} is gone", name))
    for name in sorted(set(before) & set(after)):
        old_subnet, new_subnet = before[name], after[name]
        if old_subnet.type != new_subnet.type or old_subnet.number != new_subnet.number:
            findings.append(
                _finding(
                    "HW015",
                    "_project",
                    f"{old_subnet.type}/{old_subnet.number} -> {new_subnet.type}/{new_subnet.number}",
                    name,
                )
            )
    return findings


def _diff_devices(old: list[DeviceNode], new: list[DeviceNode]) -> list[Finding]:
    """Compare device lists and recurse into the ones present on both sides.

    Parameters
    ----------
    old, new : list[DeviceNode]
        Baseline and candidate device lists.

    Returns
    -------
    list[Finding]
        Findings for devices added, removed, or changed, plus everything
        found by recursing into their items.
    """
    before = {d.name: d for d in old}
    after = {d.name: d for d in new}
    findings: list[Finding] = []
    for name in sorted(set(after) - set(before)):
        findings.append(_finding("HW003", name, f"device {name} is new", name))
    for name in sorted(set(before) - set(after)):
        findings.append(_finding("HW004", name, f"device {name} is gone", name))
    for name in sorted(set(before) & set(after)):
        old_device, new_device = before[name], after[name]
        if old_device.type_identifier != new_device.type_identifier:
            findings.append(
                _finding(
                    "HW008",
                    name,
                    f"{old_device.type_identifier} -> {new_device.type_identifier}",
                    "type_identifier",
                )
            )
        findings.extend(_diff_unreadable(old_device.unreadable, new_device.unreadable, name))
        findings.extend(_diff_items(_flatten(old_device), _flatten(new_device)))
    return findings


def _flatten(device: DeviceNode) -> dict[str, DeviceItemNode]:
    """Index every device item by its hierarchical path.

    Parameters
    ----------
    device : DeviceNode
        Device whose item tree is flattened.

    Returns
    -------
    dict[str, DeviceItemNode]
        Every item in the device's tree, keyed by ``path``.
    """
    out: dict[str, DeviceItemNode] = {}

    def visit(items: list[DeviceItemNode]) -> None:
        for item in items:
            out[item.path] = item
            visit(item.children)

    visit(device.items)
    return out


def _diff_items(before: dict[str, DeviceItemNode], after: dict[str, DeviceItemNode]) -> list[Finding]:
    """Compare two flattened item maps.

    Parameters
    ----------
    before, after : dict[str, DeviceItemNode]
        Baseline and candidate items, keyed by path.

    Returns
    -------
    list[Finding]
        Findings for items added, removed, or present on both sides.
    """
    findings: list[Finding] = []
    for path in sorted(set(after) - set(before)):
        findings.append(_finding("HW005", path, f"module {path} is new", after[path].name))
    for path in sorted(set(before) - set(after)):
        findings.append(_finding("HW006", path, f"module {path} is gone", before[path].name))
    for path in sorted(set(before) & set(after)):
        findings.extend(_diff_item(before[path], after[path]))
    return findings


def _diff_item(old: DeviceItemNode, new: DeviceItemNode) -> list[Finding]:
    """Compare one device item present on both sides.

    Parameters
    ----------
    old, new : DeviceItemNode
        Baseline and candidate item.

    Returns
    -------
    list[Finding]
        Findings for every field of the item that differs.
    """
    findings: list[Finding] = []
    path = old.path
    if old.position != new.position:
        findings.append(_finding("HW007", path, f"position {old.position} -> {new.position}", "position"))
    if old.type_name != new.type_name:
        findings.append(_finding("HW017", path, f"{old.type_name} -> {new.type_name}", "type_name"))
    if old.order_number != new.order_number:
        findings.append(_finding("HW008", path, f"{old.order_number} -> {new.order_number}", "order_number"))
    if old.firmware != new.firmware:
        findings.append(_finding("HW009", path, f"{old.firmware} -> {new.firmware}", "firmware"))
    if old.addresses != new.addresses:
        findings.append(
            _finding(
                "HW012",
                path,
                f"{[asdict(a) for a in old.addresses]} -> {[asdict(a) for a in new.addresses]}",
                "addresses",
            )
        )
    findings.extend(_diff_mapping(path, old.attributes, new.attributes, "HW010"))
    findings.extend(_diff_features(path, old.features, new.features))
    findings.extend(_diff_unreadable(old.unreadable, new.unreadable, path))
    return findings


def _diff_mapping(
    path: str,
    old: dict[str, object],
    new: dict[str, object],
    code: str,
    prefix: str = "",
) -> list[Finding]:
    """Compare two flat value maps, promoting PROFIsafe addresses to HW002.

    Parameters
    ----------
    path : str
        Location to attach to any finding.
    old, new : dict[str, object]
        Baseline and candidate values, keyed by name.
    code : str
        Rule code to use for a change, unless it is a PROFIsafe address.
    prefix : str
        Prefix applied to the key when building the context and message, so a
        feature's keys can be distinguished from a plain attribute's.

    Returns
    -------
    list[Finding]
        One finding per key that changed, added, or was removed.
    """
    findings: list[Finding] = []
    for key in sorted(set(old) | set(new)):
        before = old.get(key, "<absent>")
        after = new.get(key, "<absent>")
        if before == after:
            continue
        actual = "HW002" if any(marker in key for marker in _F_ADDRESS_MARKERS) else code
        label = f"{prefix}{key}"
        findings.append(_finding(actual, path, f"{label}: {before!r} -> {after!r}", label))
    return findings


def _diff_features(
    path: str,
    old: dict[str, dict[str, object]],
    new: dict[str, dict[str, object]],
) -> list[Finding]:
    """Compare feature maps feature by feature.

    Parameters
    ----------
    path : str
        Location to attach to any finding.
    old, new : dict[str, dict[str, object]]
        Baseline and candidate feature maps.

    Returns
    -------
    list[Finding]
        Findings for every changed key of every feature.
    """
    findings: list[Finding] = []
    for feature in sorted(set(old) | set(new)):
        findings.extend(
            _diff_mapping(path, old.get(feature, {}), new.get(feature, {}), "HW013", f"{feature}.")
        )
    return findings


def _diff_unreadable(
    old: list[UnreadableAttribute],
    new: list[UnreadableAttribute],
    location: str,
) -> list[Finding]:
    """Report attributes that stopped being readable.

    An attribute that vanishes from a dump without a trace reads as
    "unchanged". It is not: it means "not read". This is the finding that
    keeps that honest. An attribute already unreadable on both sides is not
    news, so it produces nothing.

    Parameters
    ----------
    old, new : list[UnreadableAttribute]
        Baseline and candidate unreadable-attribute lists, for either a
        device or a device item.
    location : str
        Location to attach to any finding: the device name, or the item path.

    Returns
    -------
    list[Finding]
        One HW011 finding per attribute newly unreadable in ``new``.
    """
    before = {u.name for u in old}
    after = {u.name: u.reason for u in new}
    return [
        _finding("HW011", location, f"{name} could not be read: {after[name]}", name)
        for name in sorted(set(after) - before)
    ]


__all__ = ["build_report", "diff_snapshots"]
