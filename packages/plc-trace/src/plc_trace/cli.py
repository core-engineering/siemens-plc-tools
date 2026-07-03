"""``plc trace`` CLI group."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from plc_trace.scaffold import ScaffoldError, _write_scl, generate_trace_blocks

console = Console()


@click.group(name="trace")
def trace_group() -> None:
    """Cycle-granular on-PLC trace recorder: scaffold, control, fetch."""


@trace_group.command()
@click.option(
    "--udt",
    "udt_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the source UDT .s7dcl file (flat scalar fields only).",
)
@click.option("--depth", required=True, type=int, help="Ring depth (samples held per field).")
@click.option("--name", default="TraceData", help="Trace instance name.")
@click.option(
    "--out",
    "out_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Output directory (defaults to the UDT's own directory).",
)
@click.option("--force", is_flag=True, help="Overwrite existing target files.")
def scaffold(udt_path: Path, depth: int, name: str, out_dir: Path | None, force: bool) -> None:
    """Generate the trace UDT, instance DB, and recorder FC for a source UDT."""
    out = out_dir if out_dir is not None else udt_path.parent
    targets = {
        "type": out / f"type{name}.s7dcl",
        "db": out / f"{name}.s7dcl",
        "fc": out / f"{name}Recorder.s7dcl",
    }

    existing = [str(p) for p in targets.values() if p.exists()]
    if existing and not force:
        console.print(f"[red]Error:[/red] target file(s) already exist: {', '.join(existing)}")
        console.print("Use --force to overwrite.")
        raise SystemExit(1)

    try:
        blocks = generate_trace_blocks(udt_path, depth=depth, name=name)
    except ScaffoldError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1) from exc

    out.mkdir(parents=True, exist_ok=True)
    for key, path in targets.items():
        _write_scl(path, blocks[key])
        console.print(f"[green]Created:[/green] {path}")
