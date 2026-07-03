"""``plc trace`` CLI group."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime
from pathlib import Path
from typing import Any

import click
from plc_core.config.loader import find_config_file
from plc_core.opcua.client import OpcUaClient
from plc_core.opcua.config import OpcUaConfig
from plc_core.testing.tag_resolver import TagResolver
from rich.console import Console
from rich.table import Table

from plc_trace.client import TraceClient
from plc_trace.config import TraceConfig, load_trace_config
from plc_trace.scaffold import ScaffoldError, _write_scl, generate_trace_blocks
from plc_trace.steps import browse_trace_fields

console = Console()


def _run(coro: object) -> object:
    """Run an async coroutine synchronously (mirrors ``plc_sim.cli._run``)."""
    return asyncio.run(coro)  # type: ignore[arg-type]


def _load_context() -> tuple[TraceConfig, OpcUaConfig, Path, Path]:
    """Load trace + OPC UA config, cache dir, and output dir from plc.yaml.

    Mirrors ``plc_sim.cli._get_config`` / the connection setup in
    ``plc sim read``, minus the plc-sim dependency (module boundary: plc-trace
    only depends on plc-core[opcua] + plc-code).
    """
    config, sim_raw = load_trace_config()
    opcua_config = OpcUaConfig.from_dict(sim_raw)

    cfg_file = find_config_file()
    if cfg_file is None:
        raise FileNotFoundError("plc.yaml not found (searched upward from the current directory)")
    project_root = cfg_file.parent

    testing_raw = (sim_raw.get("testing") or {}) if isinstance(sim_raw, dict) else {}
    cache_dir = project_root / testing_raw.get("cache_dir", ".sim")
    output_dir = project_root / config.output_dir

    return config, opcua_config, cache_dir, output_dir


async def _connect_and_resolve(opcua_config: OpcUaConfig, cache_dir: Path) -> tuple[OpcUaClient, TagResolver]:
    """Connect an OpcUaClient and load the tag cache (reuses ``plc sim test``'s idiom)."""
    client = OpcUaClient(opcua_config)
    info = await client.connect()
    if info.status != "connected":
        await client.disconnect()
        raise RuntimeError(f"Connection failed: {info.error_message}")

    resolver = TagResolver(client, cache_dir=cache_dir)
    try:
        await resolver.ensure_loaded()
    except Exception:
        await client.disconnect()
        raise
    return client, resolver


def _run_cli(coro: Coroutine[Any, Any, None]) -> None:
    """Run a CLI async body, turning connection/protocol errors into SystemExit(1)."""
    try:
        _run(coro)
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1) from e


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


# =============================================================================
# Runtime commands: status / start / stop / fetch
# =============================================================================


@trace_group.command()
@click.option("--endpoint", "-e", help="OPC UA endpoint URL (overrides plc.yaml)")
def status(endpoint: str | None) -> None:
    """Show the current trace recorder status."""
    config, opcua_config, cache_dir, _output_dir = _load_context()
    if endpoint:
        opcua_config.endpoint = endpoint

    async def _status() -> None:
        client, resolver = await _connect_and_resolve(opcua_config, cache_dir)
        try:
            tc = TraceClient(client, lambda p: resolver.resolve(p).node_id, config)
            st = await tc.status()

            table = Table(title=f"Trace status ({config.db_path})")
            table.add_column("Field", style="cyan")
            table.add_column("Value", style="green")
            table.add_row("recording", str(st.recording))
            table.add_row("wrapped", str(st.wrapped))
            table.add_row("write_idx", str(st.write_idx))
            table.add_row("sample_count", str(st.sample_count))
            table.add_row("cycle_counter", str(st.cycle_counter))
            table.add_row("cycle_time_ms", str(st.cycle_time_ms))
            table.add_row("depth", str(st.depth))
            console.print(table)
        finally:
            await client.disconnect()

    _run_cli(_status())


@trace_group.command()
@click.option(
    "--mode",
    type=click.Choice(["ring", "oneshot"]),
    default="ring",
    show_default=True,
    help="Ring wraps at depth; oneshot stops at depth.",
)
@click.option("--decimation", type=int, default=1, show_default=True, help="Sample every k-th cycle.")
@click.option("--endpoint", "-e", help="OPC UA endpoint URL (overrides plc.yaml)")
def start(mode: str, decimation: int, endpoint: str | None) -> None:
    """Arm the trace recorder and wait for it to start sampling."""
    config, opcua_config, cache_dir, _output_dir = _load_context()
    if endpoint:
        opcua_config.endpoint = endpoint

    async def _start() -> None:
        client, resolver = await _connect_and_resolve(opcua_config, cache_dir)
        try:
            tc = TraceClient(client, lambda p: resolver.resolve(p).node_id, config)
            await tc.start(mode=mode, decimation=decimation)
            console.print(f"[green]Trace started[/green] (mode={mode}, decimation={decimation})")
        finally:
            await client.disconnect()

    _run_cli(_start())


@trace_group.command()
@click.option("--endpoint", "-e", help="OPC UA endpoint URL (overrides plc.yaml)")
def stop(endpoint: str | None) -> None:
    """Stop the trace recorder."""
    config, opcua_config, cache_dir, _output_dir = _load_context()
    if endpoint:
        opcua_config.endpoint = endpoint

    async def _stop() -> None:
        client, resolver = await _connect_and_resolve(opcua_config, cache_dir)
        try:
            tc = TraceClient(client, lambda p: resolver.resolve(p).node_id, config)
            st = await tc.stop()
            console.print(
                f"[green]Trace stopped[/green] " f"(sample_count={st.sample_count}, wrapped={st.wrapped})"
            )
        finally:
            await client.disconnect()

    _run_cli(_stop())


@trace_group.command()
@click.option(
    "--output",
    "-o",
    "output",
    type=click.Path(path_type=Path),
    default=None,
    help="Destination CSV path (defaults to <output_dir>/trace_<timestamp>.csv).",
)
@click.option("--endpoint", "-e", help="OPC UA endpoint URL (overrides plc.yaml)")
def fetch(output: Path | None, endpoint: str | None) -> None:
    """Fetch the recorded trace and save it as CSV (plus a JSON metadata sidecar)."""
    config, opcua_config, cache_dir, output_dir = _load_context()
    if endpoint:
        opcua_config.endpoint = endpoint

    async def _fetch() -> None:
        client, resolver = await _connect_and_resolve(opcua_config, cache_dir)
        try:
            fields = browse_trace_fields(resolver, config.db_path)
            tc = TraceClient(client, lambda p: resolver.resolve(p).node_id, config, fields=fields)
            recording = await tc.fetch()

            out_path = output
            if out_path is None:
                out_path = output_dir / f"trace_{datetime.now():%Y%m%d_%H%M%S}.csv"
            recording.save(out_path)

            console.print(
                f"[green]Trace saved:[/green] {out_path} " f"({len(recording.sample_cycles)} sample(s))"
            )
        finally:
            await client.disconnect()

    _run_cli(_fetch())
