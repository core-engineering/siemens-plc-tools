"""Render-time IR for the Draw.io generator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Cartouche:
    """A3 cartouche metadata for a single sheet."""

    title: str
    drawing_number: str
    sheet_number: str
    drawn_by: str
    approved_by: str
    revision: str


@dataclass
class Block:
    """A placed shape on a sheet."""

    id: str
    shape: str  # shape name as registered in iec_stencil
    position: tuple[int, int]  # (x, y) in Draw.io coords
    size: tuple[int, int]  # (width, height)
    properties: dict[str, str] = field(default_factory=dict)


@dataclass
class Wire:
    """A connection between two block ports."""

    id: str
    source_id: str
    target_id: str
    label: str = ""
    source_port: str = "out"
    target_port: str = "in"


@dataclass
class Annotation:
    """A free-floating annotation (sticky note, marker)."""

    id: str
    kind: Literal["comment", "state_machine_container", "auto_acknowledge"]
    text: str
    position: tuple[int, int]


@dataclass
class Sheet:
    """A single rendered sheet ready for XML serialization."""

    sheet_number: str
    cartouche: Cartouche
    blocks: list[Block] = field(default_factory=list)
    wires: list[Wire] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)
