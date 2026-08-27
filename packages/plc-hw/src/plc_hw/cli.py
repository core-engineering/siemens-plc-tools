"""``plc hw`` — dump, diff and check TIA hardware parameters."""

from __future__ import annotations

import importlib
import json as json_module
import tempfile
from pathlib import Path
from typing import cast

import click
import yaml
from plc_core.reporting import Finding
from rich.console import Console

from plc_hw.config import load_hw_config
from plc_hw.diff import build_report, diff_snapshots
from plc_hw.reader import DumpReadError, read_dump
from plc_hw.record import (
    FixtureError,
    RecordingSource,
    ReplaySource,
    anonymise,
    load_fixture,
    save_fixture,
)
from plc_hw.source import HardwareSource
from plc_hw.walk import walk_project
from plc_hw.writer import DumpRootError, write_dump

# soft_wrap=True on both: Rich assumes 80 columns whenever it cannot detect a
# real terminal -- true for every pipe and every CI capture -- and inserts real
# newlines into the output to fit. That silently breaks a `grep` on any phrase
# this module prints, on both streams: `plc hw check` piped in CI is exactly
# that scenario for stderr, and its "Wrote N file(s) to <path>" success line is
# just as often parsed on stdout.
console = Console(soft_wrap=True)
console_err = Console(stderr=True, soft_wrap=True)

#: Raw recordings may only land here. The directory is git-ignored.
RAW_RECORD_DIR = ".plc-hw-record"

# Two kinds of bad input, neither a programming error, that must still land on
# exit 2 rather than escape as an unhandled exception (which Click would report
# as exit 1, breaking the "0 success, 2 any failure" contract every command
# below documents):
#
# - A hand-edited or truncated `--source replay:<path>` fixture. `load_fixture`
#   and `ReplaySource` validate eagerly and raise `FixtureError` -- the only
#   failure mode of loading or replaying a fixture, mirroring how `read_dump`
#   raises only `DumpReadError`. `dump` and `check` catch that one type; a
#   `KeyError` or `TypeError` reaching here now is a genuine bug in this
#   package's own code (e.g. inside `walk_project`), not bad input, and is left
#   to escape with its traceback rather than be reported as "could not read".
# - A plc.yaml with invalid YAML syntax, surfaced by plc_core's `load_yaml` as
#   `yaml.YAMLError`. Caught in its own narrow `try` around the
#   `load_hw_config()` call alone, not folded into the main try below: nothing
#   else in either command can raise `yaml.YAMLError` on purpose, and widening
#   the main catch to include it would also swallow
#   `yaml.representer.RepresenterError` (a `YAMLError` subclass) from a real
#   `write_dump` serialisation bug.
#
# `dump` and `check` each therefore have two `try` blocks: one narrow one around
# `load_hw_config()`, and the main one around everything else.


def record_to_parts(path: Path) -> tuple[str, ...]:
    """Return the path parts, so the raw-recording guard can inspect them."""
    return path.parts


_FORMAT = click.option(
    "-f",
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
)
_SOURCE = click.option(
    "--source",
    default=None,
    help="Read from a recorded fixture instead of TIA, as replay:<path>.",
)
_ATTACH = click.option("--attach", is_flag=True, help="Attach to a running TIA session.")
_PROJECT = click.option(
    "--project", type=click.Path(path_type=Path), default=None, help="TIA project to open headless."
)


@click.group(name="hw")
def hw_group() -> None:
    """Version TIA Portal hardware parameters.

    ``dump`` and ``check`` need Windows with TIA Portal installed. ``diff``
    compares two dumps and runs anywhere.
    """


def _open_source(source: str | None, attach: bool, project: Path | None) -> HardwareSource:
    """Resolve the requested source.

    Raises
    ------
    click.ClickException
        If the scheme is unknown, if Openness support is not installed on
        this machine, or if Openness cannot be reached.
    """
    if source is not None:
        if not source.startswith("replay:"):
            raise click.ClickException(f"unknown source {source!r}; expected replay:<path>")
        return ReplaySource(load_fixture(Path(source.removeprefix("replay:"))))

    # Imported here on purpose: `plc hw diff` must work on a machine with no TIA
    # and no pythonnet installed. Loaded dynamically, not with a static `from ...
    # import ...`: the module does not exist until Task 10 creates it, and mypy
    # treats a missing submodule of an *installed* package as "installed but
    # untyped" rather than "not found", which would otherwise force either an
    # ignore comment or a config override -- neither of which belongs here for a
    # module that is genuinely absent, not merely unstubbed.
    try:
        openness = importlib.import_module("plc_hw.openness.source")
    except ImportError as exc:
        raise click.ClickException(
            "TIA Openness support is unavailable on this machine ('plc_hw.openness' could not be "
            "imported). Install the 'hw' extra on a Windows machine with TIA Portal and pythonnet "
            "to enable it, or pass --source replay:<path> to work without TIA."
        ) from exc

    try:
        return cast(HardwareSource, openness.open_source(attach=attach, project=project))
    except openness.OpennessError as exc:
        raise click.ClickException(str(exc)) from exc


def _emit(findings: list[Finding], output_format: str) -> None:
    """Render a diff result and exit with 0 or 1."""
    if output_format == "json":
        # Plain print, not console.print_json: the output is parsed by callers.
        print(
            json_module.dumps(
                {
                    "identical": not findings,
                    "findings": [
                        {
                            "rule_code": f.rule_code,
                            "severity": f.severity.value,
                            "title": f.title,
                            "location": f.location,
                            "context": f.context,
                            "message": f.message,
                        }
                        for f in findings
                    ],
                }
            )
        )
        raise SystemExit(1 if findings else 0)

    if not findings:
        console.print("[green]Identical[/green] — no hardware difference.")
        raise SystemExit(0)

    report = build_report(findings)
    for section in report.sections:
        console.print(f"\n[bold]{section.title}[/bold]")
        for finding in section.findings:
            colour = finding.severity.color
            console.print(
                f"  [{colour}]{finding.severity.symbol}[/{colour}] "
                f"{finding.rule_code} {finding.location}: {finding.message}"
            )
    console.print(f"\n{report.total_errors} error(s), {report.total_warnings} warning(s)")
    raise SystemExit(1)


@hw_group.command()
@click.option("--out", type=click.Path(path_type=Path), default=None, help="Dump root.")
@_SOURCE
@_ATTACH
@_PROJECT
@click.option("--record", "record_to", type=click.Path(path_type=Path), default=None)
@click.option("--no-anonymize", is_flag=True, help="Record raw. Never commit the result.")
def dump(
    out: Path | None,
    source: str | None,
    attach: bool,
    project: Path | None,
    record_to: Path | None,
    no_anonymize: bool,
) -> None:
    """Write the hardware parameter tree.

    Exit code: 0 on success, 2 on any failure.
    """
    try:
        config, root = load_hw_config()
    except yaml.YAMLError as exc:
        console_err.print(f"[red]error:[/red] plc.yaml is not valid YAML: {exc}")
        raise SystemExit(2) from exc
    target = out or (root / config.dump_dir)
    try:
        if no_anonymize and record_to is not None and RAW_RECORD_DIR not in record_to_parts(record_to):
            raise click.ClickException(
                f"--no-anonymize may only write under {RAW_RECORD_DIR}/, which is git-ignored; "
                "a raw recording carries device names, plant tags and the project name"
            )
        target_source = _open_source(
            source, attach, project or (Path(config.project) if config.project else None)
        )
        recorder = RecordingSource(target_source) if record_to is not None else None
        hardware: HardwareSource = recorder or target_source
        snapshot = walk_project(hardware, volatile=config.volatile_attributes)
        written = write_dump(snapshot, target)
        if recorder is not None and record_to is not None:
            fixture = recorder.fixture()
            if config.anonymize and not no_anonymize:
                fixture, _ = anonymise(fixture)
            save_fixture(fixture, record_to)
    except (DumpRootError, click.ClickException, OSError, FixtureError) as exc:
        console_err.print(f"[red]error:[/red] {exc}")
        raise SystemExit(2) from exc
    console.print(f"[green]Wrote[/green] {len(written)} file(s) to {target}")


@hw_group.command()
@click.argument("old_path", type=click.Path(path_type=Path))
@click.argument("new_path", type=click.Path(path_type=Path))
@_FORMAT
def diff(old_path: Path, new_path: Path, output_format: str) -> None:
    """Compare two dumps.

    Exit code: 0 identical, 1 differences, 2 a dump could not be read.
    """
    try:
        findings = diff_snapshots(read_dump(old_path), read_dump(new_path))
    except DumpReadError as exc:
        console_err.print(f"[red]error:[/red] {exc}")
        raise SystemExit(2) from exc
    _emit(findings, output_format)


@hw_group.command()
@click.option("--baseline", type=click.Path(path_type=Path), default=None)
@_SOURCE
@_ATTACH
@_PROJECT
@_FORMAT
def check(
    baseline: Path | None,
    source: str | None,
    attach: bool,
    project: Path | None,
    output_format: str,
) -> None:
    """Dump the live project and compare it to the committed baseline.

    Exit code: 0 identical, 1 the hardware moved, 2 nothing could be read.
    """
    try:
        config, root = load_hw_config()
    except yaml.YAMLError as exc:
        console_err.print(f"[red]error:[/red] plc.yaml is not valid YAML: {exc}")
        raise SystemExit(2) from exc
    reference = baseline or (root / config.dump_dir)
    try:
        hardware = _open_source(source, attach, project or (Path(config.project) if config.project else None))
        snapshot = walk_project(hardware, volatile=config.volatile_attributes)
        with tempfile.TemporaryDirectory() as scratch:
            live = Path(scratch) / "dump"
            write_dump(snapshot, live)
            findings = diff_snapshots(read_dump(reference), read_dump(live))
    except (DumpReadError, DumpRootError, click.ClickException, OSError, FixtureError) as exc:
        console_err.print(f"[red]error:[/red] {exc}")
        raise SystemExit(2) from exc
    _emit(findings, output_format)


__all__ = ["hw_group"]
