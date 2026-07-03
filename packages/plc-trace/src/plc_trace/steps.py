"""Trace scenario steps: ``trace_start`` / ``trace_stop`` / ``trace_fetch``.

Step dataclasses, YAML parsers, executors, and :func:`register_trace_steps`
which wires the three step types onto a ``ScenarioRunner`` (plc-sim's
``plc sim test`` command; see the soft-import block in ``plc_sim.cli``).

Executors take a pre-built :class:`~plc_trace.client.TraceClient` as their
first argument (rather than the full ``ScenarioRunner``, as sim's own
``execute_assert_flash``/``execute_assert_stable`` do) because the trace
protocol is stateful across steps: ``TraceClient.start()`` records
``started_at_iso``, which ``TraceClient.fetch()`` later reads back into the
recording's metadata. That state has to survive between the ``trace_start``
and ``trace_fetch`` steps of the same scenario, so :func:`register_trace_steps`
builds exactly **one** ``TraceClient`` (lazily, on the first trace_* step
executed — not at registration time, so the tag cache does not need to be
loaded yet when this function runs) and shares it across all three
executors.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from plc_core.testing.models import Outcome, StepResult
from plc_core.testing.runner import ScenarioRunner
from plc_core.testing.schema import register_step_parser
from plc_core.testing.tag_resolver import TagResolver

from plc_trace.client import TraceClient
from plc_trace.config import TraceConfig

# ---------------------------------------------------------------------------
# Step dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TraceStartStep:
    """Arm the on-PLC trace recorder."""

    step_type: str = "trace_start"
    description: str = ""
    mode: str = "ring"
    decimation: int = 1


@dataclass
class TraceStopStep:
    """Stop the on-PLC trace recorder."""

    step_type: str = "trace_stop"
    description: str = ""


@dataclass
class TraceFetchStep:
    """Fetch the recorded trace and save it as CSV.

    ``output`` is a path; if relative, it is resolved against the
    ``output_dir`` passed to :func:`register_trace_steps`. If empty, the
    default filename is ``<output_dir>/<scenario-name>.csv``, where the
    scenario name comes from the ``scenario_name_provider`` callable
    supplied at registration time. If that provider is unavailable or
    raises (e.g. the scenario name isn't reachable from the call site
    wiring it up), the executor falls back to a timestamped filename
    (``trace_<YYYYmmdd_HHMMSS>.csv``) — acceptable here since this is
    runtime tooling output, not a test artifact needing a stable name.
    """

    step_type: str = "trace_fetch"
    description: str = ""
    output: str = ""


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def parse_trace_start(raw: dict[str, Any]) -> TraceStartStep:
    """Parse a ``trace_start`` step from YAML."""
    return TraceStartStep(
        description=raw.get("description", ""),
        mode=str(raw.get("mode", "ring")),
        decimation=int(raw.get("decimation", 1)),
    )


def parse_trace_stop(raw: dict[str, Any]) -> TraceStopStep:
    """Parse a ``trace_stop`` step from YAML."""
    return TraceStopStep(description=raw.get("description", ""))


def parse_trace_fetch(raw: dict[str, Any]) -> TraceFetchStep:
    """Parse a ``trace_fetch`` step from YAML."""
    return TraceFetchStep(
        description=raw.get("description", ""),
        output=raw.get("output", ""),
    )


register_step_parser("trace_start", parse_trace_start)
register_step_parser("trace_stop", parse_trace_stop)
register_step_parser("trace_fetch", parse_trace_fetch)


# ---------------------------------------------------------------------------
# Field discovery
# ---------------------------------------------------------------------------


def browse_trace_fields(tags: TagResolver, db_path: str) -> list[str]:
    """Discover UDT field names from the loaded tag cache, in cache order.

    Fields are the DB's direct array-variable children besides ``control``,
    ``status``, and ``sampleCycles`` (see :mod:`plc_trace.scaffold` for the
    contract layout). Iteration follows the tag cache's insertion order,
    which mirrors the UDT's declaration order (the recursive OPC UA browse,
    and the JSON cache round-trip, both preserve it).

    Parameters
    ----------
    tags : TagResolver
        Loaded tag resolver (cache already built).
    db_path : str
        Tag path of the trace interface DB (``TraceConfig.db_path``).

    Returns
    -------
    list[str]
        Field names, in declaration order.
    """
    prefix = f"{db_path}."
    excluded = {"control", "status", "sampleCycles"}
    fields: list[str] = []
    for tag in tags.search(db_path):
        if not tag.path.startswith(prefix):
            continue
        remainder = tag.path[len(prefix) :]
        if "." in remainder or remainder in excluded:
            continue
        fields.append(remainder)
    return fields


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------


def _scenario_output_name(provider: Callable[[], str]) -> str:
    """Resolve the default fetch filename stem: scenario name, or a timestamp."""
    try:
        name = provider()
    except Exception:
        name = ""
    return name or f"trace_{datetime.now():%Y%m%d_%H%M%S}"


async def execute_trace_start(client: TraceClient, index: int, step: TraceStartStep, t0: float) -> StepResult:
    """Execute a ``trace_start`` step: arm the recorder and wait for it to start."""
    description = step.description or f"Start trace (mode={step.mode}, decimation={step.decimation})"
    try:
        await client.start(mode=step.mode, decimation=step.decimation)
    except Exception as e:
        return StepResult(
            step_index=index,
            step_type="trace_start",
            description=description,
            outcome=Outcome.ERROR,
            duration_s=time.monotonic() - t0,
            error_message=f"{type(e).__name__}: {e}",
        )

    return StepResult(
        step_index=index,
        step_type="trace_start",
        description=description,
        outcome=Outcome.PASSED,
        duration_s=time.monotonic() - t0,
        actual_values={"mode": step.mode, "decimation": step.decimation},
    )


async def execute_trace_stop(client: TraceClient, index: int, step: TraceStopStep, t0: float) -> StepResult:
    """Execute a ``trace_stop`` step: stop the recorder and report its final status."""
    description = step.description or "Stop trace"
    try:
        status = await client.stop()
    except Exception as e:
        return StepResult(
            step_index=index,
            step_type="trace_stop",
            description=description,
            outcome=Outcome.ERROR,
            duration_s=time.monotonic() - t0,
            error_message=f"{type(e).__name__}: {e}",
        )

    return StepResult(
        step_index=index,
        step_type="trace_stop",
        description=description,
        outcome=Outcome.PASSED,
        duration_s=time.monotonic() - t0,
        actual_values={
            "sample_count": status.sample_count,
            "wrapped": status.wrapped,
            "recording": status.recording,
        },
    )


async def execute_trace_fetch(
    client: TraceClient,
    index: int,
    step: TraceFetchStep,
    t0: float,
    output_dir: Path,
    scenario_name_provider: Callable[[], str],
) -> StepResult:
    """Execute a ``trace_fetch`` step: fetch the recording and save it as CSV.

    See :class:`TraceFetchStep` for the default-filename fallback policy.
    """
    description = step.description or "Fetch trace"
    try:
        recording = await client.fetch()
    except Exception as e:
        return StepResult(
            step_index=index,
            step_type="trace_fetch",
            description=description,
            outcome=Outcome.ERROR,
            duration_s=time.monotonic() - t0,
            error_message=f"{type(e).__name__}: {e}",
        )

    if step.output:
        out_path = Path(step.output)
        if not out_path.is_absolute():
            out_path = output_dir / out_path
    else:
        out_path = output_dir / f"{_scenario_output_name(scenario_name_provider)}.csv"

    try:
        recording.save(out_path)
    except OSError as e:
        return StepResult(
            step_index=index,
            step_type="trace_fetch",
            description=description,
            outcome=Outcome.ERROR,
            duration_s=time.monotonic() - t0,
            error_message=f"Failed to save trace to {out_path}: {e}",
        )

    return StepResult(
        step_index=index,
        step_type="trace_fetch",
        description=description or f"Fetch trace ({len(recording.sample_cycles)} sample(s))",
        outcome=Outcome.PASSED,
        duration_s=time.monotonic() - t0,
        actual_values={"output": str(out_path), "samples": len(recording.sample_cycles)},
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_trace_steps(
    runner: ScenarioRunner,
    config: TraceConfig,
    output_dir: Path,
    scenario_name_provider: Callable[[], str],
) -> None:
    """Register the ``trace_start``/``trace_stop``/``trace_fetch`` executors.

    Builds a single lazily-initialized :class:`~plc_trace.client.TraceClient`
    — created on the first trace_* step actually executed, not here at
    registration time, so the tag cache does not need to be loaded yet when
    this function runs — and shares it across all three step types (see the
    module docstring for why sharing one instance matters).

    Parameters
    ----------
    runner : ScenarioRunner
        Target scenario runner. Only ``.client``, ``.tags``, and
        ``.register_step`` are used.
    config : TraceConfig
        Trace module configuration (``db_path``, ``fetch_chunk``, ...).
    output_dir : Path
        Default directory for ``trace_fetch`` output when the step's
        ``output`` field is empty or relative.
    scenario_name_provider : Callable[[], str]
        Returns the name of the scenario currently executing; used to build
        the default fetch filename. Called lazily, once per ``trace_fetch``
        step (not cached), so it always reflects the scenario in progress.
    """
    holder: dict[str, TraceClient] = {}

    def _client() -> TraceClient:
        client = holder.get("client")
        if client is None:
            fields = browse_trace_fields(runner.tags, config.db_path)
            client = TraceClient(
                runner.client,
                lambda path: runner.tags.resolve(path).node_id,
                config,
                fields=fields,
            )
            holder["client"] = client
        return client

    runner.register_step(
        "trace_start",
        lambda idx, step, t0: execute_trace_start(_client(), idx, step, t0),
    )
    runner.register_step(
        "trace_stop",
        lambda idx, step, t0: execute_trace_stop(_client(), idx, step, t0),
    )
    runner.register_step(
        "trace_fetch",
        lambda idx, step, t0: execute_trace_fetch(
            _client(), idx, step, t0, output_dir, scenario_name_provider
        ),
    )
