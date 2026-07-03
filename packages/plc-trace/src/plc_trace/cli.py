"""``plc trace`` CLI group."""

from __future__ import annotations

import click


@click.group(name="trace")
def trace_group() -> None:
    """Cycle-granular on-PLC trace recorder: scaffold, control, fetch."""
