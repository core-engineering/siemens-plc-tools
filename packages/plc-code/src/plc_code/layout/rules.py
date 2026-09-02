"""Standard-access (non-optimized) layout rules for S7-1200/1500 data blocks.

Rules (see the design spec):
1. cursor starts at byte 0 bit 0;
2. Bool takes the next bit, consecutive Bools share a byte;
3. a non-Bool member first closes an open bit byte;
4. 1-byte members are byte-aligned; everything else (>= 2 bytes, String,
   WString, Struct, UDT, Array) starts on an even byte;
5. arrays lay elements out contiguously by the element rule, then pad to even;
6. Struct and UDT lay out recursively from an even byte, then pad to even;
7. the total is rounded up to an even byte.

Arrays, inline Structs and UDTs are out of scope for this module: `_place` raises
`NotImplementedError` for them. A later pass completes those rules and rewrites
`_place` accordingly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from plc_code.layout.registry import TypeRegistry
from plc_code.layout.sizes import elementary_size
from plc_code.layout.typespec import TypeSpec, parse_type_spec


class FieldLike(Protocol):
    """What a declaration must expose: `VariableDeclaration` and `StructField` both do."""

    name: str
    data_type: str
    parent: str


@dataclass(frozen=True)
class Member:
    """One entry of a layout. Non-leaf entries (Struct, UDT, Array) carry their whole extent.

    Attributes
    ----------
    path : str
        Dotted path of the member (e.g., "motor.speed").
    data_type : str
        The declared data type text.
    byte_offset : int
        Byte offset from the start of the block.
    bit_offset : int
        Bit offset within `byte_offset` (0 for anything but a Bool leaf).
    size_bytes : int
        Size in bytes; 0 for a Bool leaf.
    size_bits : int
        Size in bits; 1 for a Bool leaf, otherwise `size_bytes * 8`.
    is_leaf : bool
        Whether this member is a scalar/string leaf rather than a Struct/UDT/Array container.
    """

    path: str
    data_type: str
    byte_offset: int
    bit_offset: int
    size_bytes: int
    size_bits: int
    is_leaf: bool


@dataclass
class Layout:
    """Members in declaration order plus the padded total size.

    Attributes
    ----------
    block : str
        Name of the block this layout was computed for.
    optimized : bool
        Whether the source block uses optimized (not standard) access.
    total_size : int
        Total size in bytes, rounded up to an even number.
    members : list[Member]
        All members, in declaration order.
    """

    block: str = ""
    optimized: bool = False
    total_size: int = 0
    members: list[Member] = field(default_factory=list)

    def leaf(self, path: str) -> Member:
        """Look up a leaf member by its dotted path.

        Parameters
        ----------
        path : str
            The dotted path of the leaf member (e.g., "motor.speed").

        Returns
        -------
        Member
            The matching leaf member.

        Raises
        ------
        KeyError
            If no leaf member has that path.
        """
        for member in self.members:
            if member.path == path and member.is_leaf:
                return member
        raise KeyError(path)


class _Cursor:
    """Mutable byte/bit write position used while laying out a flat member list."""

    def __init__(self) -> None:
        self.byte = 0
        self.bit = 0

    def close_bits(self) -> None:
        """Close an open bit byte (round up to the next byte boundary) if one is open."""
        if self.bit:
            self.byte += 1
            self.bit = 0

    def align_even(self) -> None:
        """Close any open bit byte, then round up to the next even byte."""
        self.close_bits()
        if self.byte % 2:
            self.byte += 1

    def take_bit(self) -> tuple[int, int]:
        """Take the next bit position, advancing the cursor by one bit.

        Returns
        -------
        tuple[int, int]
            The (byte, bit) position taken.
        """
        position = (self.byte, self.bit)
        self.bit += 1
        if self.bit == 8:
            self.byte, self.bit = self.byte + 1, 0
        return position

    def take_bytes(self, count: int, *, even: bool) -> int:
        """Take `count` bytes, aligning first per `even`.

        Parameters
        ----------
        count : int
            Number of bytes to take.
        even : bool
            If True, align to the next even byte first; otherwise only close
            any open bit byte.

        Returns
        -------
        int
            The starting byte offset taken.
        """
        if even:
            self.align_even()
        else:
            self.close_bits()
        start = self.byte
        self.byte += count
        return start


def layout_fields(fields: Sequence[FieldLike], registry: TypeRegistry) -> Layout:
    """Lay out top-level declarations; nested inline Structs are rebuilt from `parent` paths.

    Parameters
    ----------
    fields : Sequence[FieldLike]
        Flat declarations in source order (`VariableDeclaration` or `StructField`),
        with `parent` recording inline-Struct nesting.
    registry : TypeRegistry
        UDT definitions, consulted for non-elementary base types.

    Returns
    -------
    Layout
        The computed member layout with its padded total size.
    """
    layout = Layout()
    cursor = _Cursor()
    for node in _tree(fields):
        _place(node, "", cursor, registry, layout.members)
    cursor.align_even()
    layout.total_size = cursor.byte
    return layout


@dataclass
class _Node:
    """One entry of the tree rebuilt from flat `FieldLike` declarations."""

    name: str
    data_type: str
    children: list[_Node] = field(default_factory=list)


def _tree(fields: Sequence[FieldLike]) -> list[_Node]:
    """Rebuild nesting from `parent` paths; the flat list is parent-before-children."""
    roots: list[_Node] = []
    by_path: dict[str, _Node] = {}
    for f in fields:
        node = _Node(f.name, f.data_type)
        path = f"{f.parent}.{f.name}" if f.parent else f.name
        by_path[path] = node
        if f.parent:
            by_path[f.parent].children.append(node)
        else:
            roots.append(node)
    return roots


def _place(node: _Node, prefix: str, cursor: _Cursor, registry: TypeRegistry, out: list[Member]) -> None:
    """Place one node's leaf member(s) into `out`, advancing `cursor`.

    Only elementary scalars, String and WString are handled here; arrays, inline
    Structs and UDTs raise `NotImplementedError` (they land in a later pass).
    """
    path = f"{prefix}{node.name}"
    spec = parse_type_spec(node.data_type)
    if spec.is_array:
        raise NotImplementedError(f"{path}: array layout is not implemented yet")
    if spec.is_struct or (elementary_size(spec.base) is None and spec.string_length is None):
        raise NotImplementedError(f"{path}: Struct/UDT layout is not implemented yet")
    _place_scalar(path, spec, node.data_type, cursor, out)


def _place_scalar(path: str, spec: TypeSpec, data_type: str, cursor: _Cursor, out: list[Member]) -> None:
    """Place a single elementary, String or WString leaf and advance `cursor`."""
    if spec.string_length is not None:
        string_size = spec.string_length + 2 if spec.base == "String" else 2 * spec.string_length + 4
        start = cursor.take_bytes(string_size, even=True)
        out.append(Member(path, data_type, start, 0, string_size, string_size * 8, True))
        return
    elementary = elementary_size(spec.base)
    if elementary is None:
        raise ValueError(f"{path}: unknown type {spec.base!r}")
    if elementary.bits == 1:
        byte, bit = cursor.take_bit()
        out.append(Member(path, data_type, byte, bit, 0, 1, True))
        return
    start = cursor.take_bytes(elementary.bytes, even=elementary.bytes >= 2)
    out.append(Member(path, data_type, start, 0, elementary.bytes, elementary.bits, True))
