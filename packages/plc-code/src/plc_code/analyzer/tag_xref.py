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
    parse_errors: list[str] = field(default_factory=list)
    #: Declared prefixes (``SDI_`` ...) none of whose tags is ever accessed: almost
    #: always a program part missing from the compared export, not N broken chains.
    silent_prefixes: list[str] = field(default_factory=list)

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
    parse_errors: list[str] = []
    for block in blocks:
        index = access_index(block)
        for problem in index.parse_errors:
            parse_errors.append(f"{block.name}: {problem}")
        for access in index.accesses:
            name = _tag_root(access.path)
            if name is None:
                continue
            site = (block.name, access.line)
            if name in declared:
                target = declared[name].writes if access.is_write else declared[name].reads
                target.append(site)
            elif _looks_like_io_tag(name):
                undeclared.setdefault(name, []).append(site)
    usages = sorted(declared.values(), key=lambda u: u.tag.name)
    silent = []
    by_prefix: dict[str, list[TagUsage]] = {}
    for usage in usages:
        for prefix in _IO_PREFIXES:
            if usage.tag.name.startswith(prefix):
                by_prefix.setdefault(prefix, []).append(usage)
                break
    for prefix, members in sorted(by_prefix.items()):
        if len(members) >= 3 and all(not m.reads and not m.writes for m in members):
            silent.append(prefix)
    return XrefReport(usages=usages, undeclared=undeclared, parse_errors=parse_errors, silent_prefixes=silent)


def _tag_root(path: str) -> str | None:
    """The quoted root a tag access starts with: ``"SW".%X0`` and ``"A"[1]`` count.

    A path rooted in a local (``#x``), an absolute address (``%I0.0``) or a
    global DB *member* chain also starts with a quoted root -- the tag table
    decides which quoted roots are tags; this only extracts the root name.
    """
    if not path.startswith('"'):
        return None
    closing = path.find('"', 1)
    if closing < 0:
        return None
    return path[1:closing]


#: The naming conventions the projects use for wired I/O. Must stay a superset of
#: ``tag_parser.TAG_PREFIXES`` (checked by a test), or a declared category could
#: never be reported at all.
_IO_PREFIXES = ("DO_", "SDO_", "DI_", "SDI_", "AI_", "SAI_", "AO_", "SAO_")


def _looks_like_io_tag(name: str) -> bool:
    return name.startswith(_IO_PREFIXES)
