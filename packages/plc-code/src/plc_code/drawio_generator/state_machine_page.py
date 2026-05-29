"""Build state-machine definition pages (front matter)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from plc_code.docmap.schema import Document
from plc_code.drawio_generator.models import (
    Block,
    Cartouche,
    Sheet,
    Wire,
)


class _StateLike(Protocol):
    name: str
    entry: str
    do: str
    exit: str


class _TransitionLike(Protocol):
    from_state: str
    to_state: str
    condition: str


_BUBBLE_W, _BUBBLE_H = 180, 80
_BUBBLE_X = 400
_BUBBLE_Y0 = 200
_BUBBLE_DY = 140
_CONTAINER_X, _CONTAINER_Y = 100, 100
_CONTAINER_W, _CONTAINER_H = 1200, 900


def build_state_machine_sheet(
    *,
    page_num: int,
    title: str,
    document: Document,
    states: Sequence[_StateLike],
    transitions: Sequence[_TransitionLike],
) -> Sheet:
    """Build a Sheet rendering an SM diagram for a pattern definition page.

    Parameters
    ----------
    page_num : int
        Sheet number (zero-padded to 3 digits in the output).
    title : str
        Human-readable FB type name, e.g. ``"MotorStarter"``.
    document : Document
        Project-level metadata (drawing number, revision, signatories).
    states : list[_StateLike]
        Ordered list of state objects.  Each must expose ``name``,
        ``entry``, ``do``, and ``exit`` string attributes.
    transitions : list[_TransitionLike]
        List of transition objects.  Each must expose ``from_state``,
        ``to_state``, and ``condition`` string attributes.

    Returns
    -------
    Sheet
        A fully populated IR sheet ready for XML serialisation.
    """
    cartouche = Cartouche(
        title=f"Block: {title}",
        drawing_number=document.drawing_number,
        sheet_number=f"{page_num:03d}",
        drawn_by=document.drawn_by,
        approved_by=document.approved_by,
        revision=document.revision,
    )
    blocks: list[Block] = [
        Block(
            id=f"smc_{title.lower()}",
            shape="state_machine_container",
            position=(_CONTAINER_X, _CONTAINER_Y),
            size=(_CONTAINER_W, _CONTAINER_H),
            properties={"label": title},
        )
    ]
    state_id_by_name: dict[str, str] = {}
    for i, state in enumerate(states):
        sid = f"st_{i}_{state.name.lower()}"
        state_id_by_name[state.name] = sid
        blocks.append(
            Block(
                id=sid,
                shape="state_bubble",
                position=(_BUBBLE_X, _BUBBLE_Y0 + i * _BUBBLE_DY),
                size=(_BUBBLE_W, _BUBBLE_H),
                properties={
                    "name": state.name,
                    "entry": state.entry,
                    "do": state.do,
                    "exit": state.exit,
                },
            )
        )
    wires: list[Wire] = [
        Wire(
            id=f"tr_{i}",
            source_id=state_id_by_name[t.from_state],
            target_id=state_id_by_name[t.to_state],
            label=t.condition,
        )
        for i, t in enumerate(transitions)
    ]
    return Sheet(
        sheet_number=f"{page_num:03d}",
        cartouche=cartouche,
        blocks=blocks,
        wires=wires,
        annotations=[],
    )
