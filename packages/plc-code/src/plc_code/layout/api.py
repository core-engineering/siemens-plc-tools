"""Entry point: layout of a parsed DATA_BLOCK."""

from __future__ import annotations

from plc_code.layout.registry import TypeRegistry, UnknownTypeError
from plc_code.layout.rules import Layout, layout_fields
from plc_code.parser.models import Block


class OptimizedBlockError(ValueError):
    """The block declares optimized access; its layout is not derivable from source.

    Parameters
    ----------
    block_name : str
        Name of the block that declares optimized access.
    """

    def __init__(self, block_name: str) -> None:
        super().__init__(
            f"{block_name!r} is an optimized block: offsets are not derivable from source "
            "(use force to get the standard layout anyway)"
        )


def compute_layout(block: Block, registry: TypeRegistry, *, force: bool = False) -> Layout:
    """Byte/bit offsets of every member of a standard-access DATA_BLOCK.

    A typed DB takes its members from the UDT in ``registry``; an inline DB from
    its ``VAR`` section. An instance DB names a function block, which the
    registry does not hold: ``UnknownTypeError`` says so.

    Parameters
    ----------
    block : Block
        A parsed ``DATA_BLOCK``.
    registry : TypeRegistry
        UDT definitions, consulted for the block's base type and its members.
    force : bool, optional
        Lay out an optimized block anyway, as if it declared standard access.

    Returns
    -------
    Layout
        The member layout, with ``block`` and ``optimized`` filled from `block`.

    Raises
    ------
    ValueError
        If `block` is not a ``DATA_BLOCK``.
    OptimizedBlockError
        If the block declares optimized access and `force` is False.
    UnknownTypeError
        If the block's base type is not a registered UDT (an instance DB).
    """
    if block.block_type != "DATA_BLOCK":
        raise ValueError(f"{block.name!r} is a {block.block_type}, not a DATA_BLOCK")
    if block.attributes.optimized and not force:
        raise OptimizedBlockError(block.name)
    if block.base_type:
        if block.base_type not in registry:
            raise UnknownTypeError(block.base_type)
        layout = layout_fields(registry.get(block.base_type).fields, registry)
    else:
        variables = [v for section in block.variable_sections for v in section.variables]
        layout = layout_fields(variables, registry)
    layout.block = block.name
    layout.optimized = block.attributes.optimized
    return layout
