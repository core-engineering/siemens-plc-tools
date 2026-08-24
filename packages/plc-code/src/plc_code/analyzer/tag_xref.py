"""Cross-reference between the tag table and the code: which I/O is actually used.

An I/O list declares what the panel is wired to; the code decides what the PLC
does with it. The gap between the two is where commissioning surprises live: an
input nobody reads is a broken chain no test will trip, an output nobody writes
stays at its default forever. This module walks every block's access index and
sorts the declared tags into used / read-only / write-only / untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from plc_code.parser.models import Block

from .logic_dependency.access_index import access_index
from .logic_dependency.tag_parser import IOTag, TagCollection


@dataclass
class TagUsage:
    """Where one declared tag is read and written across the program.

    Attributes
    ----------
    tag : IOTag
        The declaration, with its address, type and direction.
    reads : list[tuple[str, int]]
        ``(block, line)`` for every read.
    writes : list[tuple[str, int]]
        ``(block, line)`` for every write.
    """

    tag: IOTag
    reads: list[tuple[str, int]] = field(default_factory=list)
    writes: list[tuple[str, int]] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        """``used``, ``read-only``, ``write-only`` or ``untouched``.

        The verdict is about *access*, not correctness by direction; the report
        layer decides which verdicts are findings for which tag direction (an
        input is expected read-only, an output write-only).
        """
        if self.reads and self.writes:
            return "used"
        if self.reads:
            return "read-only"
        if self.writes:
            return "write-only"
        return "untouched"


@dataclass
class XrefReport:
    """Every declared tag with its usage, plus the quoted names the code uses
    that no tag table declares (a typo or a stale export)."""

    usages: list[TagUsage] = field(default_factory=list)
    undeclared: dict[str, list[tuple[str, int]]] = field(default_factory=dict)

    @property
    def findings(self) -> list[TagUsage]:
        """The usages worth a look: an input never read, an output never written,
        anything untouched."""
        found = []
        for usage in self.usages:
            if usage.verdict == "untouched":
                found.append(usage)
            elif usage.tag.is_output and not usage.writes:
                found.append(usage)
            elif not usage.tag.is_output and not usage.reads:
                found.append(usage)
        return found


def cross_reference(blocks: list[Block], tags: TagCollection) -> XrefReport:
    """Match every declared tag against every access in ``blocks``."""
    declared = {tag.name: TagUsage(tag=tag) for tag in tags.tags}
    undeclared: dict[str, list[tuple[str, int]]] = {}
    for block in blocks:
        for access in access_index(block).accesses:
            name = _bare_tag_name(access.path)
            if name is None:
                continue
            site = (block.name, access.line)
            if name in declared:
                target = declared[name].writes if access.is_write else declared[name].reads
                target.append(site)
            elif _looks_like_io_tag(name):
                undeclared.setdefault(name, []).append(site)
    return XrefReport(usages=sorted(declared.values(), key=lambda u: u.tag.name), undeclared=undeclared)


def _bare_tag_name(path: str) -> str | None:
    """``"DO_PUMP"`` -> ``DO_PUMP``; a path with members or a local is not a tag."""
    if path.startswith('"') and path.endswith('"') and path.count('"') == 2:
        return path[1:-1]
    return None


def _looks_like_io_tag(name: str) -> bool:
    """The naming convention the projects use for wired I/O."""
    prefixes = ("DO_", "SDO_", "DI_", "SDI_", "AI_", "SAI_", "AO_", "SAO_")
    return name.startswith(prefixes)
