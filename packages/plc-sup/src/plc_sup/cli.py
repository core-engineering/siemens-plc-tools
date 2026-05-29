"""CLI commands for supervision pipeline testing.

Usage::

    plc sup test [OPTIONS]
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click
from plc_core.opcua.client import OpcUaClient
from plc_core.testing.reporter import (
    ReportMetadata,
    generate_junit_xml,
    generate_markdown_report,
    print_suite_summary,
)
from plc_core.testing.runner import ScenarioRunner
from plc_core.testing.schema import discover_scenario_files, parse_scenario, parse_setup
from plc_core.testing.tag_resolver import TagResolver
from rich.console import Console

# Importing steps triggers registration of sup-specific step parsers
import plc_sup.testing.steps  # noqa: F401
from plc_sup.core.config import load_sup_config
from plc_sup.testing.clients import ApiVerifier, DbVerifier, InfraClient, RedisVerifier
from plc_sup.testing.executors import (
    execute_infra,
    execute_verify_api,
    execute_verify_db,
    execute_verify_redis,
)

console = Console()


@click.group(name="sup")
@click.pass_context
def sup_group(ctx: click.Context) -> None:
    """Supervision pipeline testing tools."""
    ctx.ensure_object(dict)


# Alias for plugin discovery
cli = sup_group


@sup_group.command()
@click.option("--config", "-c", "config_path", type=click.Path(), default=None)
@click.option("--filter", "-k", "filter_pattern", type=str, default=None)
@click.option("--verbose", "-v", is_flag=True, default=False)
@click.option("--junit-xml", type=click.Path(), default=None)
@click.option("--report", type=click.Path(), default=None)
@click.option("--refresh-cache", is_flag=True, default=False)
def test(
    config_path: str | None,
    filter_pattern: str | None,
    verbose: bool,
    junit_xml: str | None,
    report: str | None,
    refresh_cache: bool,
) -> None:
    """Run supervision pipeline test scenarios."""

    async def _run() -> bool:
        # Load config
        try:
            config = load_sup_config(Path(config_path) if config_path else None)
        except (FileNotFoundError, KeyError) as e:
            console.print(f"[red]Configuration error:[/red] {e}")
            return False

        config_dir = config.config_path.parent if config.config_path else Path.cwd()
        test_dir = (config_dir / config.testing.test_dir).resolve()

        if not test_dir.is_dir():
            console.print(f"[red]Test directory not found:[/red] {test_dir}")
            return False

        # Discover scenarios
        scenario_files = discover_scenario_files(test_dir)
        if not scenario_files:
            console.print(f"[yellow]No test scenarios found in {test_dir}[/yellow]")
            return True

        scenarios = []
        for f in scenario_files:
            try:
                scenarios.append(parse_scenario(f))
            except Exception as e:
                console.print(f"[red]Error parsing {f.name}:[/red] {e}")

        if not scenarios:
            console.print("[red]No valid scenarios loaded[/red]")
            return False

        # Connect to OPC UA
        client = OpcUaClient(config.opcua)
        info = await client.connect()
        if info.status.value != "connected":
            console.print(f"[red]Failed to connect to OPC UA:[/red] {info.error_message}")
            return False

        console.print(f"[green]Connected to OPC UA:[/green] {config.opcua.endpoint}")

        # Build tag cache
        cache_dir = (config_dir / config.testing.cache_dir).resolve()
        resolver = TagResolver(
            client=client,
            cache_dir=cache_dir,
            ttl_hours=config.testing.cache_ttl_hours,
        )
        tag_count = await resolver.ensure_loaded(force_refresh=refresh_cache)
        console.print(f"[green]Tag cache:[/green] {tag_count} tags")

        # Connect verification clients
        redis_client = RedisVerifier(config.redis.url)
        db_client = DbVerifier(config.database.url)
        api_client = ApiVerifier(config.api.base_url)
        infra_client = InfraClient(
            config.infra.ssh_host,
            config.infra.ssh_user,
            ssh_auth_sock=config.infra.ssh_auth_sock,
            expected_containers=config.infra.expected_containers,
        )

        try:
            await redis_client.connect()
            console.print(f"[green]Connected to Redis:[/green] {config.redis.url}")
        except Exception as e:
            console.print(f"[red]Failed to connect to Redis:[/red] {e}")
            await client.disconnect()
            return False

        # Load setup
        setup = parse_setup(test_dir)

        # Create runner with sup-specific executors
        runner = ScenarioRunner(
            client=client,
            tag_resolver=resolver,
            console=console,
            verbose=verbose,
            setup=setup,
        )

        # Register sup-specific step executors with bound clients
        runner.register_step(
            "verify_redis",
            lambda idx, step, t0: execute_verify_redis(runner, idx, step, t0, redis_client=redis_client),
        )
        runner.register_step(
            "verify_db",
            lambda idx, step, t0: execute_verify_db(runner, idx, step, t0, db_client=db_client),
        )
        runner.register_step(
            "verify_api",
            lambda idx, step, t0: execute_verify_api(runner, idx, step, t0, api_client=api_client),
        )
        runner.register_step(
            "infra",
            lambda idx, step, t0: execute_infra(runner, idx, step, t0, infra_client=infra_client),
        )

        # Run
        console.print(f"\nRunning {len(scenarios)} scenario(s)...\n")
        suite = await runner.run_suite(scenarios, filter_pattern=filter_pattern)
        print_suite_summary(console, suite)

        # Reports
        if junit_xml:
            generate_junit_xml(suite, Path(junit_xml))
            console.print(f"\n[green]JUnit XML:[/green] {junit_xml}")

        if report:
            report_dir = Path(report)
            report_dir.mkdir(parents=True, exist_ok=True)
            md_path = report_dir / "supervision-test-report.md"
            metadata = ReportMetadata(
                title="Supervision Pipeline Test Report",
                subtitle=config.project_name or "Supervision Tests",
                project_code=config.project_code or "",
                endpoint=config.opcua.endpoint,
                tag_count=tag_count,
            )
            generate_markdown_report(suite, md_path, metadata)
            console.print(f"[green]Report:[/green] {md_path}")

        # Cleanup
        await redis_client.disconnect()
        await client.disconnect()

        return suite.overall_success

    success = asyncio.run(_run())
    if not success:
        sys.exit(1)
