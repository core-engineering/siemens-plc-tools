"""Auto-wiring: derive Wire objects from a dependency graph."""

from __future__ import annotations

from plc_code.drawio_generator.models import Block, Wire


def build_wires_for_sheet(
    *,
    blocks: list[Block],
    dependencies: dict[str, list[str]],
) -> list[Wire]:
    """Build a list of Wires from a dependency graph.

    Parameters
    ----------
    blocks : list of Block
        Blocks placed on the sheet, in order.
    dependencies : dict[target_id -> list[source_id]]
        Each entry says "target_id depends on these source_ids".

    Returns
    -------
    list of Wire
        One wire per (source, target) pair where both are on the sheet.
    """
    placed_ids = {b.id for b in blocks}
    wires: list[Wire] = []
    wire_counter = 0
    for target_id, sources in dependencies.items():
        if target_id not in placed_ids:
            continue
        for source_id in sources:
            if source_id not in placed_ids:
                continue
            wire_counter += 1
            wires.append(
                Wire(
                    id=f"w{wire_counter}",
                    source_id=source_id,
                    target_id=target_id,
                    label="",
                )
            )
    return wires
