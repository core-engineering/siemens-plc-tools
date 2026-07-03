"""Command-line interface for PLC simulation tools.

Provides commands for connecting to a PLC OPC UA server,
browsing variables, reading/writing values, and monitoring.

Example
-------
$ plc sim connect
$ plc sim browse
$ plc sim read "ns=3;s=MyDB.Var1"
$ plc sim write "ns=3;s=MyDB.Var2" true
$ plc sim monitor "ns=3;s=MyDB.Var1" "ns=3;s=MyDB.Var2"
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from plc_sim.core.config import SimConfig, load_sim_config
from plc_sim.core.models import NodeClass

console = Console()


def _get_config(endpoint: str | None = None) -> SimConfig:
    """Load config, optionally overriding endpoint."""
    try:
        config = load_sim_config()
    except (FileNotFoundError, KeyError):
        config = SimConfig()

    if endpoint:
        config.endpoint = endpoint

    return config


def _run(coro: object) -> object:
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)  # type: ignore[arg-type]


# =============================================================================
# CLI Group (Plugin for plc-tools)
# =============================================================================


@click.group(name="sim")
@click.pass_context
def sim_group(ctx: click.Context) -> None:
    """PLC simulation and OPC UA interaction tools.

    Connect to a PLC OPC UA server, browse variables, read/write values,
    and monitor live data.
    """
    ctx.ensure_object(dict)


# Alias for backwards compatibility
cli = sim_group


# =============================================================================
# Connect command
# =============================================================================


@sim_group.command()
@click.option("--endpoint", "-e", help="OPC UA endpoint URL (overrides plc.yaml)")
def connect(endpoint: str | None) -> None:
    """Connect to the PLC OPC UA server and show status."""
    from plc_sim.core.client import OpcUaClient

    config = _get_config(endpoint)
    console.print(f"[bold]Connecting to:[/bold] {config.endpoint}")
    console.print(f"[dim]Interface:[/dim] {config.interface}")
    console.print(f"[dim]Namespaces:[/dim] {', '.join(config.namespaces)}")
    console.print()

    async def _connect() -> None:
        client = OpcUaClient(config.opcua)
        info = await client.connect()

        if info.status == "connected":
            console.print(f"[green]Connected[/green] to {info.endpoint}")
            console.print(f"  Server: {info.server_name}")
            console.print(f"  Session: {info.session_id}")
            if info.namespaces:
                console.print(f"  Namespaces ({len(info.namespaces)}):")
                for i, ns in enumerate(info.namespaces):
                    console.print(f"    [{i}] {ns}")

            # Browse root nodes
            console.print()
            console.print("[bold]Interface root nodes:[/bold]")
            roots = await client.browse_node()
            for root in roots:
                icon = "📁" if root.node_class == NodeClass.OBJECT else "📊"
                console.print(
                    f"  {icon} {root.display_name}  "
                    f"[dim]{root.node_id}[/dim]  "
                    f"({root.children_count} children)"
                )
        else:
            console.print(f"[red]Connection failed:[/red] {info.error_message}")

        await client.disconnect()

    _run(_connect())


# =============================================================================
# Browse command
# =============================================================================


@sim_group.command()
@click.argument("node_id", required=False)
@click.option("--depth", "-d", type=int, default=2, help="Browse depth (default: 2)")
@click.option("--endpoint", "-e", help="OPC UA endpoint URL")
def browse(node_id: str | None, depth: int, endpoint: str | None) -> None:
    """Browse the OPC UA node tree.

    If NODE_ID is not specified, browses from the configured interface roots.

    Examples:
        plc sim browse                          # Browse roots
        plc sim browse "ns=3;s=MyDB"            # Browse specific node
        plc sim browse --depth 3                # Deeper browse
    """
    from plc_sim.core.client import OpcUaClient

    config = _get_config(endpoint)

    async def _browse() -> None:
        client = OpcUaClient(config.opcua)
        info = await client.connect()

        if info.status != "connected":
            console.print(f"[red]Connection failed:[/red] {info.error_message}")
            return

        try:
            tree = Tree(
                f"[bold]{config.interface}[/bold] @ {config.endpoint}",
                guide_style="dim",
            )
            roots = await client.browse_node(node_id)

            for root in roots:
                await _add_tree_node(client, tree, root, depth, current_depth=1)

            console.print(tree)
        finally:
            await client.disconnect()

    _run(_browse())


async def _add_tree_node(
    client: object,
    parent: Tree,
    node: object,
    max_depth: int,
    current_depth: int,
) -> None:
    """Recursively add nodes to a Rich tree."""
    from plc_sim.core.client import OpcUaClient
    from plc_sim.core.models import OpcUaNode

    assert isinstance(client, OpcUaClient)
    assert isinstance(node, OpcUaNode)

    # Format node label
    if node.node_class == NodeClass.VARIABLE:
        rw = "[green]RW[/green]" if node.is_writable else "[dim]R[/dim]"
        label = (
            f"[cyan]{node.display_name}[/cyan]  "
            f"[yellow]{node.data_type}[/yellow]  {rw}  "
            f"[dim]{node.node_id}[/dim]"
        )
    else:
        label = (
            f"[bold]{node.display_name}[/bold]  "
            f"[dim]{node.node_id}[/dim]  "
            f"({node.children_count} children)"
        )

    branch = parent.add(label)

    # Recurse into children
    if current_depth < max_depth and node.children_count > 0:
        try:
            children = await client.browse_node(node.node_id)
            for child in children:
                await _add_tree_node(client, branch, child, max_depth, current_depth + 1)
        except Exception as e:
            branch.add(f"[red]Error: {e}[/red]")


# =============================================================================
# Read command
# =============================================================================


@sim_group.command()
@click.argument("node_id")
@click.option("--endpoint", "-e", help="OPC UA endpoint URL")
def read(node_id: str, endpoint: str | None) -> None:
    """Read a variable value.

    Examples:
        plc sim read "ns=3;s=MyDB.Var1"
    """
    from plc_sim.core.client import OpcUaClient

    config = _get_config(endpoint)

    async def _read() -> None:
        client = OpcUaClient(config.opcua)
        info = await client.connect()

        if info.status != "connected":
            console.print(f"[red]Connection failed:[/red] {info.error_message}")
            return

        try:
            val = await client.read_value(node_id)
            console.print(f"[bold]{val.display_name or node_id}[/bold]")
            console.print(f"  Value:     [green]{val.value}[/green]")
            console.print(f"  Type:      {val.data_type}")
            console.print(f"  Quality:   {val.quality}")
            if val.source_timestamp:
                console.print(f"  Timestamp: {val.source_timestamp}")
        finally:
            await client.disconnect()

    _run(_read())


# =============================================================================
# Write command
# =============================================================================


@sim_group.command()
@click.argument("node_id")
@click.argument("value")
@click.option("--type", "-t", "data_type", help="Data type override (e.g., Boolean, Float)")
@click.option("--endpoint", "-e", help="OPC UA endpoint URL")
def write(node_id: str, value: str, data_type: str | None, endpoint: str | None) -> None:
    """Write a value to a variable.

    Examples:
        plc sim write "ns=3;s=MyDB.Var2" true
        plc sim write "ns=3;s=MyDB.Var3" 3.14 --type Float
    """
    from plc_sim.core.client import OpcUaClient

    config = _get_config(endpoint)

    async def _write() -> None:
        client = OpcUaClient(config.opcua)
        info = await client.connect()

        if info.status != "connected":
            console.print(f"[red]Connection failed:[/red] {info.error_message}")
            return

        try:
            success = await client.write_value(node_id, value, data_type)
            if success:
                # Read back to confirm
                val = await client.read_value(node_id)
                console.print(
                    f"[green]OK[/green] {val.display_name or node_id} = "
                    f"[bold]{val.value}[/bold] ({val.data_type})"
                )
        except Exception as e:
            console.print(f"[red]Write failed:[/red] {e}")
        finally:
            await client.disconnect()

    _run(_write())


# =============================================================================
# Monitor command
# =============================================================================


@sim_group.command()
@click.argument("node_ids", nargs=-1, required=True)
@click.option("--interval", "-i", type=int, default=1000, help="Poll interval in ms (default: 1000)")
@click.option("--endpoint", "-e", help="OPC UA endpoint URL")
def monitor(node_ids: tuple[str, ...], interval: int, endpoint: str | None) -> None:
    """Monitor variables with live updates.

    Press Ctrl+C to stop.

    Examples:
        plc sim monitor "ns=3;s=MyDB.Var1" "ns=3;s=MyDB.Var2"
    """
    from plc_sim.core.client import OpcUaClient

    config = _get_config(endpoint)
    nids = list(node_ids)

    async def _monitor() -> None:
        from rich.live import Live

        client = OpcUaClient(config.opcua)
        info = await client.connect()

        if info.status != "connected":
            console.print(f"[red]Connection failed:[/red] {info.error_message}")
            return

        console.print(
            f"[green]Monitoring {len(nids)} variable(s)[/green] " f"(interval: {interval}ms, Ctrl+C to stop)"
        )
        console.print()

        try:
            with Live(console=console, refresh_per_second=2) as live:
                while True:
                    table = Table(title="Live Values", show_lines=True)
                    table.add_column("Name", style="cyan")
                    table.add_column("Value", style="green bold")
                    table.add_column("Type", style="yellow")
                    table.add_column("Quality")
                    table.add_column("Timestamp", style="dim")

                    values = await client.read_values(nids)
                    for val in values:
                        quality_style = "green" if val.quality == "Good" else "red"
                        table.add_row(
                            val.display_name or val.node_id,
                            str(val.value),
                            val.data_type,
                            f"[{quality_style}]{val.quality}[/{quality_style}]",
                            val.source_timestamp[-12:] if val.source_timestamp else "",
                        )

                    live.update(table)
                    await asyncio.sleep(interval / 1000.0)
        except KeyboardInterrupt:
            console.print("\n[dim]Monitoring stopped.[/dim]")
        finally:
            await client.disconnect()

    _run(_monitor())


# =============================================================================
# Web command
# =============================================================================


@sim_group.command()
@click.option("--port", "-p", type=int, default=8080, help="Port to run server on")
@click.option("--host", "-h", default="0.0.0.0", help="Host to bind to")
@click.option("--endpoint", "-e", help="OPC UA endpoint URL")
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
def web(port: int, host: str, endpoint: str | None, path: Path | None) -> None:
    """Start the web interface for OPC UA simulation.

    Launches a FastAPI server with the interactive PLC simulation
    interface at /sim/ and API endpoints at /api/sim/.

    Examples:
        plc sim web                     # Start on port 8080
        plc sim web --port 3000         # Custom port
        plc sim web -e opc.tcp://10.0.0.1:4840  # Custom endpoint
    """
    try:
        import uvicorn
    except ImportError:
        console.print("[red]Error:[/red] uvicorn not installed.")
        console.print("Install with: uv add 'uvicorn[standard]' fastapi")
        raise SystemExit(1) from None

    config = _get_config(endpoint)

    # Try to also load the plc-code app for a combined server
    from plc_sim.web.services import get_sim_service

    service = get_sim_service()
    service.set_config(config)

    try:
        from plc_code.web import app, create_app

        # Mount plc-code app with sim routes
        create_app(
            source_path=path,
            project_name=None,
        )
        # Import and mount sim routes
        from plc_sim.web import sim_router
        from plc_sim.web.page import register_sim_page

        app.include_router(sim_router)
        register_sim_page(app)

        console.print("[bold]Starting PLC Analysis + Simulation Server[/bold]")
        console.print(f"  [green]Simulation:[/green]  http://{host}:{port}/sim/")
        console.print(f"  [green]Explorer:[/green]    http://{host}:{port}/explorer/")
        console.print(f"  [green]API:[/green]         http://{host}:{port}/api/sim/")

        uvicorn.run(app, host=host, port=port, log_level="info")

    except ImportError:
        # plc-code not installed — run standalone
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware

        from plc_sim.web import sim_router
        from plc_sim.web.page import register_sim_page

        app = FastAPI(
            title="PLC Simulation Server",
            description="OPC UA live interaction interface",
            version="0.3.0",
        )
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        app.include_router(sim_router)
        register_sim_page(app)

        console.print("[bold]Starting PLC Simulation Server (standalone)[/bold]")
        console.print(f"  [green]Simulation:[/green]  http://{host}:{port}/sim/")
        console.print(f"  [green]API:[/green]         http://{host}:{port}/api/sim/")

        uvicorn.run(app, host=host, port=port, log_level="info")


# =============================================================================
# Test command
# =============================================================================


@sim_group.command()
@click.argument("path", type=click.Path(path_type=Path), required=False)
@click.option("--verbose", "-v", is_flag=True, help="Show detailed step output")
@click.option("--filter", "-k", "filter_pattern", help="Filter scenarios by name")
@click.option("--junit-xml", "junit_xml", type=click.Path(path_type=Path), help="Write JUnit XML report")
@click.option(
    "--report",
    "report_dir",
    type=click.Path(path_type=Path),
    help="Generate markdown report in directory",
)
@click.option("--pdf", "generate_pdf", is_flag=True, help="Also generate PDF (requires pandoc + xelatex)")
@click.option("--refresh-cache", is_flag=True, help="Force tag cache rebuild")
@click.option(
    "--last-failed",
    "--lf",
    "last_failed",
    is_flag=True,
    help="Re-run only scenarios that did not pass in the previous run for the current baseline",
)
@click.option(
    "--reset-baseline",
    is_flag=True,
    help="Clear the persisted results cache before running (use after a TIA Portal re-download)",
)
@click.option("--endpoint", "-e", help="OPC UA endpoint URL")
def test(
    path: Path | None,
    verbose: bool,
    filter_pattern: str | None,
    junit_xml: Path | None,
    report_dir: Path | None,
    generate_pdf: bool,
    refresh_cache: bool,
    last_failed: bool,
    reset_baseline: bool,
    endpoint: str | None,
) -> None:
    """Run integration test scenarios against the live PLC.

    PATH is the directory containing YAML test scenarios.
    Defaults to the configured test_dir (integration-tests).

    Examples:
        plc sim test                          # Run all tests
        plc sim test -v                       # Verbose output
        plc sim test -k "lamp"                # Filter by name
        plc sim test --junit-xml results.xml  # CI/CD output
        plc sim test --report report/         # Generate markdown report
        plc sim test --report report/ --pdf   # Also generate PDF
        plc sim test --refresh-cache          # Force tag cache rebuild
        plc sim test --lf                     # Re-run failures from previous run
        plc sim test --reset-baseline         # Force a fresh baseline (after TIA reload)
        plc sim test path/to/tests            # Custom test directory
    """
    from plc_modbus import ModbusClient

    from plc_sim.core.client import OpcUaClient
    from plc_sim.testing.executors import execute_assert_flash, execute_assert_stable
    from plc_sim.testing.reporter import (
        ReportMetadata,
        generate_junit_xml,
        generate_markdown_report,
        print_suite_summary,
    )
    from plc_sim.testing.results_cache import (
        LastFailedError,
        compute_baseline_fingerprint,
        discover_baseline_sources,
        load_results_cache,
        merge_results,
        save_results_cache,
        select_scenarios_to_rerun,
    )
    from plc_sim.testing.runner import ScenarioRunner
    from plc_sim.testing.schema import discover_scenario_files, parse_scenario, parse_setup
    from plc_sim.testing.tag_resolver import TagResolver

    if last_failed and reset_baseline:
        console.print("[red]--last-failed and --reset-baseline are mutually exclusive[/red]")
        raise SystemExit(2)

    config = _get_config(endpoint)

    # Determine test directory
    if path is not None:
        test_dir = path.resolve()
    elif config.config_path:
        test_dir = config.config_path.parent / config.testing.test_dir
    else:
        test_dir = Path.cwd() / config.testing.test_dir

    # Determine cache directory
    if config.config_path:
        cache_dir = config.config_path.parent / config.testing.cache_dir
        project_root = config.config_path.parent
    else:
        cache_dir = Path.cwd() / config.testing.cache_dir
        project_root = Path.cwd()

    # Reset baseline (delete the persisted results cache, if any)
    results_cache_path = cache_dir / config.testing.results_cache_filename
    if reset_baseline and results_cache_path.exists():
        results_cache_path.unlink()
        console.print("[yellow]Baseline reset:[/yellow] previous results cache cleared")

    # Load global setup (setup.yaml)
    setup = parse_setup(test_dir)
    if setup:
        console.print(f"[bold]Setup:[/bold] {setup.description or 'setup.yaml'}")
        console.print(f"  {len(setup.values)} initial value(s), settle {setup.settle_time_s}s")
        console.print()

    # Discover scenario files
    scenario_files = discover_scenario_files(test_dir)
    if not scenario_files:
        console.print(f"[yellow]No test scenarios found in {test_dir}[/yellow]")
        console.print(f"Create test_*.yaml files in {test_dir}")
        raise SystemExit(1)

    console.print(f"[bold]Integration Tests[/bold] ({test_dir})")
    console.print(f"  Found {len(scenario_files)} scenario file(s)")
    console.print()

    # Parse scenarios
    scenarios = []
    for sf in scenario_files:
        try:
            scenario = parse_scenario(sf)
            scenarios.append(scenario)
        except Exception as e:
            console.print(f"[red]Error parsing {sf.name}:[/red] {e}")

    if not scenarios:
        console.print("[red]No valid scenarios to run[/red]")
        raise SystemExit(1)

    # Compute baseline fingerprint over the configured PLC source globs
    baseline_sources = discover_baseline_sources(
        config.testing.baseline_source_globs, project_root=project_root
    )
    baseline = compute_baseline_fingerprint(baseline_sources, root=project_root)
    console.print(
        f"[dim]Baseline fingerprint: {baseline.short()}... " f"({len(baseline_sources)} source file(s))[/dim]"
    )

    # Load results cache (may be None if absent or invalid)
    results_cache = load_results_cache(results_cache_path)

    # Apply --last-failed filter
    if last_failed:
        try:
            scenarios = select_scenarios_to_rerun(results_cache, scenarios, baseline)
        except LastFailedError as exc:
            console.print(f"[red]{exc}[/red]")
            raise SystemExit(2) from exc
        if not scenarios:
            console.print("[green]--last-failed:[/green] no scenarios to re-run (all passed)")
            return
        console.print(f"[bold]--last-failed:[/bold] re-running {len(scenarios)} scenario(s)")
        console.print()

    async def _run_tests() -> None:
        client = OpcUaClient(config.opcua)
        console.print(f"Connecting to {config.endpoint} ...")
        info = await client.connect()

        if info.status != "connected":
            console.print(f"[red]Connection failed:[/red] {info.error_message}")
            raise SystemExit(1)

        # Optional Modbus client (only if 'sim.modbus' is configured)
        modbus_client: ModbusClient | None = None
        if config.modbus is not None:
            modbus_client = ModbusClient(config.modbus)
            console.print(
                f"Connecting to Modbus TCP {config.modbus.host}:{config.modbus.port} "
                f"(unit {config.modbus.unit_id}) ..."
            )
            try:
                await modbus_client.connect()
            except Exception as e:
                console.print(f"[red]Modbus connection failed:[/red] {e}")
                await client.disconnect()
                raise SystemExit(1) from e

        try:
            # Build/load tag cache
            resolver = TagResolver(
                client,
                cache_dir=cache_dir,
                ttl_hours=config.testing.cache_ttl_hours,
                on_progress=lambda msg: console.print(f"  [dim]{msg}[/dim]"),
            )
            tag_count = await resolver.ensure_loaded(force_refresh=refresh_cache)
            console.print(f"  Tag cache: {tag_count} tags")
            console.print()

            # Run scenarios
            runner = ScenarioRunner(
                client=client,
                tag_resolver=resolver,
                console=console,
                verbose=verbose,
                setup=setup,
                write_settle_s=config.testing.write_settle_s,
                modbus_client=modbus_client,
            )
            # Register sim-specific step executors
            runner.register_step(
                "assert_stable",
                lambda idx, step, t0: execute_assert_stable(runner, idx, step, t0),
            )
            runner.register_step(
                "assert_flash",
                lambda idx, step, t0: execute_assert_flash(runner, idx, step, t0),
            )

            # Optional trace_* steps (plc-trace package). Soft dependency: plc-sim
            # has no hard import on plc-trace, so a plc-trace-less install just
            # leaves trace_start/trace_stop/trace_fetch as unknown step types.
            try:
                from plc_trace.config import load_trace_config
                from plc_trace.steps import register_trace_steps
            except ImportError:
                pass
            else:
                if config.config_path is not None:
                    trace_config, _trace_sim_raw = load_trace_config(config.config_path)
                    register_trace_steps(
                        runner,
                        trace_config,
                        output_dir=project_root / trace_config.output_dir,
                        # ScenarioRunner has no "current scenario" hook reachable from
                        # here without restructuring the runner (run_suite/run_scenario
                        # don't expose which scenario is executing to registered step
                        # executors), so trace_fetch always falls back to its
                        # timestamped filename in this wiring — see the
                        # TraceFetchStep docstring in plc_trace.steps.
                        scenario_name_provider=lambda: "",
                    )

            suite = await runner.run_suite(scenarios, filter_pattern)

            # Print summary
            print_suite_summary(console, suite)

            # Persist results cache (merge with any existing entries for the same baseline)
            updated_cache = merge_results(results_cache, suite, baseline)
            save_results_cache(updated_cache, results_cache_path)
            console.print(f"\n[dim]Results cache: {results_cache_path}[/dim]")

            # JUnit XML export
            if junit_xml:
                generate_junit_xml(suite, junit_xml)
                console.print(f"\n[dim]JUnit XML report: {junit_xml}[/dim]")

            # Markdown report
            if report_dir is not None:
                report_path = report_dir / "integration_test_report.md"
                meta = ReportMetadata(
                    title="Integration Test Report",
                    subtitle=config.project_name or "",
                    project_code=config.project_code or "",
                    endpoint=config.endpoint,
                    server_name=info.server_name or "",
                    tag_count=tag_count,
                )
                generate_markdown_report(suite, report_path, meta)
                console.print(f"\n[dim]Markdown report: {report_path}[/dim]")

                # PDF generation
                if generate_pdf:
                    import subprocess

                    report_dir_abs = report_dir.resolve()
                    pdf_path = report_dir_abs / "integration_test_report.pdf"
                    template = report_dir_abs / "Templates" / "template.tex"
                    md_path = report_dir_abs / "integration_test_report.md"
                    pandoc_cmd = [
                        "pandoc",
                        str(md_path),
                        "-o",
                        str(pdf_path),
                        "--pdf-engine=xelatex",
                        "--listings",
                    ]
                    if template.exists():
                        pandoc_cmd.extend(["--template", str(template)])

                    try:
                        subprocess.run(
                            pandoc_cmd,
                            cwd=str(report_dir_abs),
                            check=True,
                            capture_output=True,
                            text=True,
                        )
                        console.print(f"[dim]PDF report: {pdf_path}[/dim]")
                    except FileNotFoundError:
                        console.print(
                            "[yellow]pandoc not found — install pandoc and xelatex "
                            "for PDF generation[/yellow]"
                        )
                    except subprocess.CalledProcessError as e:
                        console.print(f"[red]PDF generation failed:[/red] {e.stderr[:500]}")

            # Exit code
            if not suite.overall_success:
                raise SystemExit(1)

        finally:
            await client.disconnect()
            if modbus_client is not None:
                await modbus_client.disconnect()

    _run(_run_tests())


# =============================================================================
# Results command — display the persisted test-results cache
# =============================================================================


@sim_group.command()
@click.option("--filter", "-k", "filter_pattern", help="Filter scenarios by name (substring match)")
@click.option("--failed-only", is_flag=True, help="Only show non-passing scenarios")
def results(filter_pattern: str | None, failed_only: bool) -> None:
    """Display the persisted test-results cache for the current baseline.

    Reads `.sim/test_results.json` (written by the most recent `plc sim test`
    run) and prints the table of scenario outcomes without running any test.

    Examples:
        plc sim results
        plc sim results -k controller
        plc sim results --failed-only
    """
    from plc_sim.testing.results_cache import load_results_cache

    config = _get_config()

    if config.config_path:
        cache_dir = config.config_path.parent / config.testing.cache_dir
    else:
        cache_dir = Path.cwd() / config.testing.cache_dir

    cache_path = cache_dir / config.testing.results_cache_filename
    cache = load_results_cache(cache_path)

    if cache is None:
        console.print(f"[yellow]No results cache found at {cache_path}[/yellow]")
        console.print("Run [bold]plc sim test[/bold] first to populate the cache.")
        raise SystemExit(1)

    # Filter
    entries = list(cache.results.values())
    if filter_pattern:
        entries = [e for e in entries if filter_pattern.lower() in e.name.lower()]
    if failed_only:
        entries = [e for e in entries if not e.is_pass]
    entries.sort(key=lambda e: e.name)

    # Header
    console.print()
    console.print(f"[bold]Baseline fingerprint:[/bold] {cache.baseline.short()}...")
    console.print(f"[dim]Source files: {len(cache.baseline.source_files)}[/dim]")
    console.print(f"[dim]Computed at:  {cache.baseline.computed_at}[/dim]")
    console.print()

    if not entries:
        console.print("[dim]No scenarios match the filter.[/dim]")
        return

    # Aggregate counts (over the full cache, not the filtered view)
    counts: dict[str, int] = {}
    for r in cache.results.values():
        counts[r.outcome] = counts.get(r.outcome, 0) + 1
    counts_str = "  ".join(f"{_outcome_color(k)}{v} {k}[/]" for k, v in sorted(counts.items()))
    console.print(f"[bold]Totals:[/bold]  {counts_str}  ({len(cache.results)} total)")
    console.print()

    # Table
    table = Table(show_header=True, header_style="bold", show_lines=False)
    table.add_column("Scenario", style="cyan", no_wrap=False)
    table.add_column("Outcome", justify="left")
    table.add_column("Duration", justify="right")
    table.add_column("Executed at", style="dim")
    table.add_column("Error", overflow="fold")

    for r in entries:
        outcome_cell = f"{_outcome_color(r.outcome)}{r.outcome}[/]"
        duration_cell = f"{r.duration_s:.2f}s"
        error_cell = ""
        if r.error_message:
            error_cell = r.error_message.replace("\n", " ")
            if len(error_cell) > 80:
                error_cell = error_cell[:77] + "..."
        table.add_row(r.name, outcome_cell, duration_cell, r.executed_at, error_cell)

    console.print(table)
    console.print()
    console.print(f"[dim]Displayed {len(entries)} of {len(cache.results)} cached scenario(s)[/dim]")


def _outcome_color(outcome: str) -> str:
    """Return a Rich color tag prefix for an outcome name."""
    return {
        "passed": "[green]",
        "warning": "[yellow]",
        "skipped": "[yellow]",
        "failed": "[red]",
        "error": "[red]",
    }.get(outcome, "[white]")
