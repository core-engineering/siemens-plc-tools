"""Command-line interface for PLC IOL tools.

This module provides the CLI commands for the plc iol subgroup.

Example
-------
$ plc iol status
$ plc iol import tags --path ./tags
$ plc iol validate
"""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from plc_iol.core.config import (
    ConfigError,
    ProjectConfig,
    create_default_config,
    load_config,
)
from plc_iol.core.database import DatabaseManager
from plc_iol.core.models import IODatabase

console = Console()


def get_config(config_path: str | None = None) -> ProjectConfig:
    """Load configuration, handling errors gracefully."""
    try:
        return load_config(config_path)
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1) from e


# =============================================================================
# IOL CLI Group (Plugin for plc-tools)
# =============================================================================


@click.group(name="iol")
@click.pass_context
def iol_group(ctx: click.Context) -> None:
    """IOL management tools.

    Provides commands for managing PLC TAGS and IOL documents.
    """
    ctx.ensure_object(dict)


# Alias for backwards compatibility
cli = iol_group


# =============================================================================
# Init command
# =============================================================================


@iol_group.command()
@click.option(
    "--name",
    "-n",
    help="Project name",
)
@click.option(
    "--code",
    "-c",
    help="Project code",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Overwrite existing configuration",
)
def init(name: str | None, code: str | None, force: bool) -> None:
    """Initialize IOL configuration in current directory."""
    project_root = Path.cwd()
    config_path = project_root / "iol.yaml"

    if config_path.exists() and not force:
        console.print("[yellow]Warning:[/yellow] iol.yaml already exists. Use --force to overwrite.")
        raise SystemExit(1)

    created_path = create_default_config(project_root, name=name, code=code)
    console.print(f"[green]Created:[/green] {created_path}")
    console.print("\nEdit iol.yaml to configure your project:")
    console.print("  - Define functional groups")
    console.print("  - Set paths to TAGS and IOL files")
    console.print("  - Configure naming conventions")


# =============================================================================
# Status command
# =============================================================================


@iol_group.command()
@click.option("--config", "-c", "config_path", help="Path to iol.yaml")
def status(config_path: str | None) -> None:
    """Show project status and statistics."""
    config = get_config(config_path)

    console.print(f"\n[bold]Project:[/bold] {config.name}")
    if config.code:
        console.print(f"[bold]Code:[/bold] {config.code}")
    console.print(f"[bold]Root:[/bold] {config.project_root}")

    # Check paths
    console.print("\n[bold]Paths:[/bold]")
    paths_info = [
        ("Tags", config.paths.tags, config.tags_path),
        ("IOL", config.paths.iol, config.iol_path),
        ("Database", config.paths.database, config.database_path),
    ]
    for name, rel_path, abs_path in paths_info:
        exists = "✓" if abs_path.exists() else "✗"
        color = "green" if abs_path.exists() else "red"
        console.print(f"  {name}: [{color}]{exists}[/{color}] {rel_path}")

    # Functional groups
    if config.functional_groups:
        console.print(f"\n[bold]Functional Groups:[/bold] {len(config.functional_groups)}")
        for group in config.functional_groups:
            console.print(f"  - {group.id}: {len(group.xml_files)} XML files")

    # Database stats
    db_manager = DatabaseManager.from_config(config)
    if db_manager.exists():
        stats = db_manager.get_statistics()
        console.print(f"\n[bold]Database:[/bold] {stats['total']} points")
        if stats["by_category"]:
            console.print("  By category:")
            for cat, count in sorted(stats["by_category"].items()):
                console.print(f"    {cat}: {count}")
    else:
        console.print("\n[yellow]Database:[/yellow] Not initialized (run 'iol import')")


# =============================================================================
# Import commands
# =============================================================================


@iol_group.group()
def import_() -> None:
    """Import data from various sources."""
    pass


# Rename to avoid conflict with Python keyword
iol_group.add_command(import_, name="import")


@import_.command(name="tags")
@click.option("--config", "-c", "config_path", help="Path to iol.yaml")
@click.option("--path", "-p", help="Path to XML file or directory")
@click.option("--merge", "-m", is_flag=True, help="Merge with existing database")
def import_tags(config_path: str | None, path: str | None, merge: bool) -> None:
    """Import PLC tags from S7-1500 XML files."""
    config = get_config(config_path)

    from plc_iol.importers.xml_importer import XMLImporter

    importer = XMLImporter(config=config)

    if path:
        # Import from specified path
        p = Path(path)
        db = importer.import_file(p) if p.is_file() else importer.import_directory(p)
        source = path
    else:
        # Import from config
        result = importer.import_from_config()
        db = result.database
        source = "configuration"

        if result.errors:
            for error in result.errors:
                console.print(f"[yellow]Warning:[/yellow] {error}")

    # Save to database
    db_manager = DatabaseManager.from_config(config)

    if merge and db_manager.exists():
        stats = db_manager.merge(db, overwrite=False)
        console.print(f"[green]Merged:[/green] {stats['added']} added, {stats['skipped']} skipped")
    else:
        db_manager.save(db)
        console.print(f"[green]Imported:[/green] {len(db)} points from {source}")


@import_.command(name="iol")
@click.option("--config", "-c", "config_path", help="Path to iol.yaml")
@click.option("--path", "-p", help="Path to IOL Excel file")
@click.option("--merge", "-m", is_flag=True, help="Merge with existing database")
def import_iol(config_path: str | None, path: str | None, merge: bool) -> None:
    """Import I/O points from IOL Excel file."""
    config = get_config(config_path)

    from plc_iol.importers.excel_importer import ExcelImporter

    importer = ExcelImporter(config=config)

    if path:
        db = importer.import_file(Path(path))
        source = path
    else:
        result = importer.import_from_config()
        db = result.database
        source = "configuration"

        if result.errors:
            for error in result.errors:
                console.print(f"[yellow]Warning:[/yellow] {error}")

    # Save to database
    db_manager = DatabaseManager.from_config(config)

    if merge and db_manager.exists():
        stats = db_manager.merge(db, overwrite=False)
        console.print(f"[green]Merged:[/green] {stats['added']} added, {stats['skipped']} skipped")
    else:
        db_manager.save(db)
        console.print(f"[green]Imported:[/green] {len(db)} points from {source}")


# =============================================================================
# Export commands
# =============================================================================


@iol_group.group()
def export() -> None:
    """Export data to various formats."""
    pass


@export.command(name="tags")
@click.option("--config", "-c", "config_path", help="Path to iol.yaml")
@click.option("--output", "-o", help="Output directory")
@click.option(
    "--group-by",
    type=click.Choice(["functional_group", "xml_source", "single"]),
    default="functional_group",
)
def export_tags(config_path: str | None, output: str | None, group_by: str) -> None:
    """Export database to S7-1500 XML files."""
    config = get_config(config_path)

    from plc_iol.exporters.xml_exporter import XMLExporter

    db_manager = DatabaseManager.from_config(config)
    if not db_manager.exists():
        console.print("[red]Error:[/red] No database found. Run 'iol import' first.")
        raise SystemExit(1)

    db = db_manager.load()
    exporter = XMLExporter(config=config)

    output_dir = Path(output) if output else config.tags_path
    result = exporter.export_database(db, output_dir, group_by=group_by)

    if result.success:
        console.print(
            f"[green]Exported:[/green] {result.points_exported} points "
            f"to {len(result.files_created)} files"
        )
        for f in result.files_created:
            console.print(f"  - {f}")
    else:
        for error in result.errors:
            console.print(f"[red]Error:[/red] {error}")


@export.command(name="iol")
@click.option("--config", "-c", "config_path", help="Path to iol.yaml")
@click.option("--output", "-o", help="Output file path")
def export_iol(config_path: str | None, output: str | None) -> None:
    """Export database to IOL Excel file."""
    config = get_config(config_path)

    from plc_iol.exporters.excel_exporter import ExcelExporter

    db_manager = DatabaseManager.from_config(config)
    if not db_manager.exists():
        console.print("[red]Error:[/red] No database found. Run 'iol import' first.")
        raise SystemExit(1)

    db = db_manager.load()
    exporter = ExcelExporter(config=config)

    output_path = Path(output) if output else config.iol_path / "iol_export.xlsx"
    result = exporter.export_database(db, output_path)

    if result.success:
        console.print(f"[green]Exported:[/green] {result.points_exported} points to {result.file_path}")
    else:
        for error in result.errors:
            console.print(f"[red]Error:[/red] {error}")


# =============================================================================
# List command
# =============================================================================


@cli.command(name="list")
@click.option("--config", "-c", "config_path", help="Path to iol.yaml")
@click.option("--category", help="Filter by I/O category (DI, DO, AI, AO, SDI, SDO)")
@click.option("--group", help="Filter by functional group")
@click.option("--limit", "-n", default=50, help="Maximum rows to show")
def list_points(config_path: str | None, category: str | None, group: str | None, limit: int) -> None:
    """List I/O points in database."""
    config = get_config(config_path)

    db_manager = DatabaseManager.from_config(config)
    if not db_manager.exists():
        console.print("[yellow]No database found.[/yellow] Run 'iol import' first.")
        return

    db = db_manager.load()

    # Apply filters
    from plc_iol.core.models import IOCategory

    io_cat = None
    if category:
        try:
            io_cat = IOCategory(category.upper())
        except ValueError:
            console.print(f"[red]Invalid category:[/red] {category}")
            raise SystemExit(1) from None

    points = db.filter(io_category=io_cat, functional_group=group)

    # Create table
    table = Table(title=f"I/O Points ({len(points)} total)")
    table.add_column("Mnemonic", style="cyan")
    table.add_column("Signal Name")
    table.add_column("Category")
    table.add_column("Group")
    table.add_column("Address")

    for point in sorted(points, key=lambda p: p.mnemonic)[:limit]:
        table.add_row(
            point.mnemonic,
            point.signal_name[:30] if point.signal_name else "",
            point.io_category.value if point.io_category else "",
            point.functional_group or "",
            point.plc_address or "",
        )

    console.print(table)

    if len(points) > limit:
        console.print(f"\n[dim]Showing {limit} of {len(points)} points. Use --limit to show more.[/dim]")


# =============================================================================
# Compare command
# =============================================================================


@iol_group.command()
@click.option("--config", "-c", "config_path", help="Path to iol.yaml")
@click.option("--source", "-s", required=True, help="Source (tags or iol)")
@click.option("--target", "-t", required=True, help="Target (tags or iol)")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed differences")
def compare(config_path: str | None, source: str, target: str, verbose: bool) -> None:
    """Compare TAGS vs IOL or different sources."""
    config = get_config(config_path)

    from plc_iol.analyzers.comparison import DatabaseComparator
    from plc_iol.importers.excel_importer import ExcelImporter, ExcelImportResult
    from plc_iol.importers.xml_importer import XMLImporter, XMLImportResult

    def load_source(name: str) -> tuple[IODatabase, str]:
        importer: XMLImporter | ExcelImporter
        result: XMLImportResult | ExcelImportResult
        if name.lower() == "tags":
            importer = XMLImporter(config=config)
            result = importer.import_from_config()
            return result.database, "TAGS (XML)"
        elif name.lower() == "iol":
            importer = ExcelImporter(config=config)
            result = importer.import_from_config()
            return result.database, "IOL (Excel)"
        elif name.lower() == "db":
            db_manager = DatabaseManager.from_config(config)
            return db_manager.load(), "Database"
        else:
            # Assume it's a file path
            path = Path(name)
            if path.suffix.lower() == ".xml":
                importer = XMLImporter(config=config)
                return importer.import_file(path), path.name
            elif path.suffix.lower() in (".xlsx", ".xls"):
                importer = ExcelImporter(config=config)
                return importer.import_file(path), path.name
            else:
                console.print(f"[red]Unknown source:[/red] {name}")
                raise SystemExit(1)

    source_db, source_name = load_source(source)
    target_db, target_name = load_source(target)

    comparator = DatabaseComparator(config=config)
    result = comparator.compare(source_db, target_db, source_name, target_name)

    # Print summary
    console.print(f"\n[bold]Comparison: {source_name} → {target_name}[/bold]")
    console.print(f"Source: {result.source_count} points")
    console.print(f"Target: {result.target_count} points")
    console.print()

    if result.has_changes:
        console.print(f"[green]Added:[/green] {result.added_count}")
        console.print(f"[red]Removed:[/red] {result.removed_count}")
        console.print(f"[yellow]Modified:[/yellow] {result.modified_count}")

        if verbose:
            if result.get_added():
                console.print("\n[green]Added points:[/green]")
                for diff in result.get_added()[:20]:
                    console.print(f"  + {diff.mnemonic}")

            if result.get_removed():
                console.print("\n[red]Removed points:[/red]")
                for diff in result.get_removed()[:20]:
                    console.print(f"  - {diff.mnemonic}")

            if result.get_modified():
                console.print("\n[yellow]Modified points:[/yellow]")
                for diff in result.get_modified()[:20]:
                    console.print(f"  ~ {diff.mnemonic}")
                    for fd in diff.field_diffs:
                        console.print(f"      {fd.field_name}: {fd.source_value} → {fd.target_value}")
    else:
        console.print("[green]No differences found.[/green]")


# =============================================================================
# Validate command
# =============================================================================


@iol_group.command()
@click.option("--config", "-c", "config_path", help="Path to iol.yaml")
@click.option("--verbose", "-v", is_flag=True, help="Show all issues")
@click.option("--check-consistency", is_flag=True, help="Check TAGS vs IOL consistency")
def validate(config_path: str | None, verbose: bool, check_consistency: bool) -> None:
    """Validate database for issues."""
    config = get_config(config_path)

    from plc_iol.analyzers.validation import DatabaseValidator, IssueSeverity, IssueType
    from plc_iol.importers.excel_importer import ExcelImporter
    from plc_iol.importers.xml_importer import XMLImporter

    db_manager = DatabaseManager.from_config(config)
    if not db_manager.exists():
        console.print("[red]Error:[/red] No database found. Run 'iol import' first.")
        raise SystemExit(1)

    db = db_manager.load()

    # Load TAGS and IOL for consistency check if requested
    tags_db = None
    iol_db = None
    if check_consistency:
        console.print("Loading TAGS from XML files...")
        tags_importer = XMLImporter(config=config)
        tags_result = tags_importer.import_from_config()
        tags_db = tags_result.database

        console.print("Loading IOL from Excel files...")
        iol_importer = ExcelImporter(config=config)
        iol_result = iol_importer.import_from_config()
        iol_db = iol_result.database

        if not iol_result.database.points:
            console.print("[yellow]Warning:[/yellow] No IOL data found. Skipping consistency check.")
            iol_db = None

    validator = DatabaseValidator(config=config, tags_db=tags_db, iol_db=iol_db)
    result = validator.validate(db)

    console.print("\n[bold]Validation Results[/bold]")
    console.print(f"Points checked: {result.points_checked}")
    if result.internal_tags_count > 0:
        console.print(f"Internal PLC tags: {result.internal_tags_count}")
    console.print(f"Errors: {result.error_count}")
    console.print(f"Warnings: {result.warning_count}")

    if result.is_valid:
        console.print("\n[green]✓ Database is valid[/green]")
    else:
        console.print("\n[red]✗ Validation failed[/red]")

    # Show consistency check results
    if check_consistency and tags_db and iol_db:
        mismatch_issues = result.get_by_type(IssueType.TAGS_IOL_MISMATCH)
        only_in_tags = [i for i in mismatch_issues if "in TAGS but not in IOL" in i.message]
        only_in_iol = [i for i in mismatch_issues if "in IOL but not in TAGS" in i.message]

        console.print("\n[bold]TAGS vs IOL Consistency[/bold]")
        console.print(f"  Points only in TAGS: {len(only_in_tags)}")
        console.print(f"  Points only in IOL: {len(only_in_iol)}")

        if verbose:
            if only_in_tags:
                console.print("\n  [yellow]Only in TAGS:[/yellow]")
                for issue in only_in_tags:
                    console.print(f"    - {issue.mnemonic}")

            if only_in_iol:
                console.print("\n  [yellow]Only in IOL:[/yellow]")
                for issue in only_in_iol:
                    console.print(f"    - {issue.mnemonic}")

        # Show spare statistics from IOL import (counts all rows, not deduplicated)
        spare_counts = iol_result.spare_counts
        if spare_counts.total_spares > 0:
            console.print("\n[bold]Spare I/O Points[/bold]")
            console.print(f"  Total spares: {spare_counts.total_spares}")
            console.print("")
            # Show by category
            for category in ["DI", "DO", "AI", "AO", "SDI", "SDO", "SAI", "SAO"]:
                count = spare_counts.by_category.get(category, 0)
                if count > 0:
                    total = spare_counts.total_by_category.get(category, 0)
                    percentage = spare_counts.get_percentage(category)
                    console.print(f"  {category}: {count}/{total} ({percentage:.1f}%)")

    # Show other issues
    if verbose or result.error_count > 0:
        # Group issues by type for cleaner output
        error_issues = [
            i
            for i in result.issues
            if i.severity == IssueSeverity.ERROR and i.issue_type != IssueType.TAGS_IOL_MISMATCH
        ]
        warning_issues = [
            i
            for i in result.issues
            if i.severity == IssueSeverity.WARNING and i.issue_type != IssueType.TAGS_IOL_MISMATCH
        ]

        if error_issues:
            console.print(f"\n[bold red]Errors ({len(error_issues)}):[/bold red]")
            for issue in error_issues:
                console.print(f"  [red]ERROR:[/red] {issue.message}")
                if issue.mnemonic:
                    console.print(f"         Point: {issue.mnemonic}")

        if verbose and warning_issues:
            console.print(f"\n[bold yellow]Warnings ({len(warning_issues)}):[/bold yellow]")
            for issue in warning_issues:
                console.print(f"  [yellow]WARN:[/yellow] {issue.message}")
                if issue.mnemonic:
                    console.print(f"        Point: {issue.mnemonic}")


if __name__ == "__main__":
    cli()
