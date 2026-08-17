"""Async scenario executor for integration tests.

Connects to the live PLC, resolves tags, and executes scenarios
step-by-step with real-time reporting.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from rich.console import Console

from plc_core.opcua.client import OpcUaClient
from plc_core.opcua.models import OpcUaValue
from plc_core.testing.models import Outcome, ScenarioResult, StepResult, TestSuiteResult
from plc_core.testing.schema import (
    AssertStep,
    CaptureStep,
    ModbusAssertStep,
    ModbusReadStep,
    ModbusWaitUntilStep,
    ReadStep,
    RestoreStep,
    Scenario,
    SnapshotStep,
    Step,
    SuiteSetup,
    WaitStep,
    WaitUntilStep,
    WriteStep,
)
from plc_core.testing.tag_resolver import TagResolver

logger = logging.getLogger(__name__)


def _values_match(actual: Any, expected: Any, tolerance: float | None = None) -> bool:
    """Compare actual vs expected, with optional numeric tolerance."""
    if tolerance is not None:
        try:
            return abs(float(actual) - float(expected)) <= tolerance
        except (TypeError, ValueError):
            pass
    # Boolean comparison — handle string "true"/"false" from YAML
    if isinstance(expected, bool):
        if isinstance(actual, bool):
            return actual == expected
        # asyncua may return numpy bool or int
        try:
            return bool(actual) == expected
        except (TypeError, ValueError):
            return False
    return bool(actual == expected)


class ScenarioRunner:
    """Execute test scenarios against a live PLC.

    Parameters
    ----------
    client : OpcUaClient
        Connected OPC UA client.
    tag_resolver : TagResolver
        Tag resolver with loaded cache.
    console : Console
        Rich console for live output.
    verbose : bool
        Show detailed step output.
    setup : SuiteSetup | None
        Optional global setup to apply before each scenario.
    step_executors : dict[str, Callable] | None
        Optional custom step executors to register. Each callable must have
        the signature ``(index: int, step: Any, t0: float) -> Awaitable[StepResult]``.
    """

    def __init__(
        self,
        client: OpcUaClient,
        tag_resolver: TagResolver,
        console: Console,
        verbose: bool = False,
        setup: SuiteSetup | None = None,
        step_executors: dict[str, Callable[..., Awaitable[StepResult]]] | None = None,
        write_settle_s: float = 0.3,
        modbus_client: Any = None,
    ) -> None:
        self._client = client
        self._tags = tag_resolver
        self._console = console
        self._verbose = verbose
        self._setup = setup
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._write_settle_s = write_settle_s
        # Optional Modbus client for the modbus_* step types. Typed as Any to
        # avoid a hard dependency on plc-modbus in plc-core (module boundary
        # rules forbid plc-core from importing plc-modbus). The client must
        # expose an async `read_register_at(spec, dtype) -> Any` method.
        self._modbus_client = modbus_client

        # Build step executor registry with base executors
        self._step_executors: dict[str, Callable[..., Awaitable[StepResult]]] = {
            "write": self._execute_write,
            "wait": self._execute_wait,
            "assert": self._execute_assert,
            "wait_until": self._execute_wait_until,
            "read": self._execute_read,
            "capture": self._execute_capture,
            "snapshot": self._execute_snapshot,
            "restore": self._execute_restore,
            "modbus_read": self._execute_modbus_read,
            "modbus_assert": self._execute_modbus_assert,
            "modbus_wait_until": self._execute_modbus_wait_until,
        }

        # Merge custom executors if provided
        if step_executors:
            self._step_executors.update(step_executors)

    # ------------------------------------------------------------------
    # Public properties for external executor access
    # ------------------------------------------------------------------

    @property
    def client(self) -> OpcUaClient:
        """The OPC UA client instance."""
        return self._client

    @property
    def tags(self) -> TagResolver:
        """The tag resolver instance."""
        return self._tags

    @property
    def console(self) -> Console:
        """The Rich console instance."""
        return self._console

    @property
    def verbose(self) -> bool:
        """Whether verbose output is enabled."""
        return self._verbose

    @property
    def snapshots(self) -> dict[str, dict[str, Any]]:
        """The current snapshot store."""
        return self._snapshots

    # ------------------------------------------------------------------
    # Step executor registration
    # ------------------------------------------------------------------

    def register_step(self, step_type: str, executor: Callable[..., Awaitable[StepResult]]) -> None:
        """Register a custom step executor.

        Parameters
        ----------
        step_type : str
            The step type identifier (e.g. ``"assert_flash"``).
        executor : Callable
            An async callable with signature
            ``(index: int, step: Any, t0: float) -> StepResult``.
        """
        self._step_executors[step_type] = executor

    # ------------------------------------------------------------------
    # Suite setup
    # ------------------------------------------------------------------

    async def apply_setup(self) -> None:
        """Write global initial values to the PLC.

        Called before every scenario to guarantee a clean baseline.
        Supports two-phase initialization: ``values`` first, then
        ``post_values`` (if any) after the initial settle time.
        """
        if not self._setup or not self._setup.values:
            return

        # Phase 1: write initial values
        self._console.print(f"  [dim]setup: writing {len(self._setup.values)} initial value(s)[/dim]")

        for path, value in self._setup.values.items():
            tag = self._tags.resolve(path)
            await self._client.write_value(tag.node_id, value, tag.data_type)

        await asyncio.sleep(self._setup.settle_time_s)

        # Phase 2: write post-values (e.g. restore operational config after safety reset)
        if self._setup.post_values:
            self._console.print(f"  [dim]setup: writing {len(self._setup.post_values)} post-value(s)[/dim]")

            for path, value in self._setup.post_values.items():
                tag = self._tags.resolve(path)
                await self._client.write_value(tag.node_id, value, tag.data_type)

            await asyncio.sleep(self._setup.post_settle_time_s)

    # ------------------------------------------------------------------
    # Suite runner
    # ------------------------------------------------------------------

    async def run_suite(
        self,
        scenarios: list[Scenario],
        filter_pattern: str | None = None,
    ) -> TestSuiteResult:
        """Run multiple scenarios.

        Parameters
        ----------
        scenarios : list[Scenario]
            Parsed scenarios to run.
        filter_pattern : str | None
            If set, only run scenarios whose name or filename contains this substring.

        Returns
        -------
        TestSuiteResult
        """
        if filter_pattern:
            pattern = filter_pattern.lower()
            scenarios = [
                s
                for s in scenarios
                if pattern in s.name.lower() or (s.source_file and pattern in s.source_file.stem.lower())
            ]

        suite = TestSuiteResult()
        t0 = time.monotonic()

        for scenario in scenarios:
            # Apply global setup before every scenario
            await self.apply_setup()
            result = await self.run_scenario(scenario)
            suite.scenario_results.append(result)

        suite.total_duration_s = time.monotonic() - t0
        return suite

    # ------------------------------------------------------------------
    # Scenario runner
    # ------------------------------------------------------------------

    async def run_scenario(self, scenario: Scenario) -> ScenarioResult:
        """Execute a single scenario with cleanup guarantee.

        Returns
        -------
        ScenarioResult
        """
        result = ScenarioResult(
            name=scenario.name,
            source_file=scenario.source_file,
        )
        self._snapshots.clear()
        t0 = time.monotonic()

        self._console.print(f"\n[bold]{scenario.name}[/bold]")
        if scenario.description:
            self._console.print(f"  [dim]{scenario.description}[/dim]")

        if scenario.skip:
            reason = scenario.skip_reason or "no reason given"
            self._console.print(f"  [yellow]SKIP[/yellow] {reason}")
            result.outcome = Outcome.SKIPPED
            result.skip_reason = scenario.skip_reason or None
            result.duration_s = time.monotonic() - t0
            return result

        try:
            # Check preconditions
            for pre in scenario.preconditions:
                tag = self._tags.resolve(pre.path)
                val = await self._client.read_value(tag.node_id)
                if not _values_match(val.value, pre.value):
                    self._console.print(
                        f"  [yellow]PRECONDITION[/yellow] {pre.path} = {val.value} "
                        f"(expected {pre.value}), writing..."
                    )
                    await self._client.write_value(tag.node_id, pre.value, tag.data_type)
                    await asyncio.sleep(0.5)

            # Execute steps
            stop_on_fail = False
            for idx, step in enumerate(scenario.steps):
                if stop_on_fail:
                    sr = StepResult(
                        step_index=idx,
                        step_type=step.step_type,
                        description=step.description,
                        outcome=Outcome.SKIPPED,
                    )
                    result.step_results.append(sr)
                    self._print_step(idx, sr)
                    continue

                sr = await self._execute_step(idx, step)
                result.step_results.append(sr)
                self._print_step(idx, sr)

                if sr.failed:
                    stop_on_fail = True

        except Exception as e:
            result.error_message = str(e)
            logger.error("Scenario %s failed: %s", scenario.name, e)
        finally:
            # Always run cleanup
            if scenario.cleanup:
                self._console.print("  [dim]cleanup[/dim]")
                for idx, step in enumerate(scenario.cleanup):
                    sr = await self._execute_step(idx, step)
                    result.cleanup_results.append(sr)

        result.duration_s = time.monotonic() - t0

        # Determine outcome
        if result.error_message:
            result.outcome = Outcome.ERROR
        elif any(s.failed for s in result.step_results):
            result.outcome = Outcome.FAILED
        else:
            result.outcome = Outcome.PASSED

        # Summary line
        status_style = "green" if result.passed else "red"
        status_text = "PASSED" if result.passed else "FAILED"
        warn_suffix = ""
        if result.steps_warned:
            warn_suffix = f", [yellow]{result.steps_warned} warning(s)[/yellow]"
        self._console.print(
            f"  [{status_style}]{status_text}[/{status_style}]  "
            f"{result.steps_passed}/{result.total_steps} steps"
            f"{warn_suffix} "
            f"({result.duration_s:.2f}s)"
        )

        return result

    # ------------------------------------------------------------------
    # Step dispatcher
    # ------------------------------------------------------------------

    async def _execute_step(self, index: int, step: Step) -> StepResult:
        """Dispatch and execute a single step via the executor registry."""
        t0 = time.monotonic()
        try:
            executor = self._step_executors.get(step.step_type)
            if executor is None:
                return StepResult(
                    step_index=index,
                    step_type=step.step_type,
                    description=step.description,
                    outcome=Outcome.ERROR,
                    duration_s=time.monotonic() - t0,
                    error_message=f"Unknown step type: {step.step_type}",
                )
            return await executor(index, step, t0)
        except Exception as e:
            return StepResult(
                step_index=index,
                step_type=step.step_type,
                description=step.description,
                outcome=Outcome.ERROR,
                duration_s=time.monotonic() - t0,
                error_message=str(e),
            )

    # ------------------------------------------------------------------
    # Step executors
    # ------------------------------------------------------------------

    async def _execute_write(self, index: int, step: WriteStep, t0: float) -> StepResult:
        for path, value in step.values.items():
            tag = self._tags.resolve(path)
            await self._client.write_value(tag.node_id, value, tag.data_type)

        # Settle: give the PLC at least one scan cycle to propagate the write
        # before any subsequent read / wait_until / assert. Without this delay,
        # OPC UA subscription caches can return stale values immediately after
        # a write, producing flaky test failures.
        if self._write_settle_s > 0:
            await asyncio.sleep(self._write_settle_s)

        return StepResult(
            step_index=index,
            step_type="write",
            description=step.description or f"Write {len(step.values)} value(s)",
            outcome=Outcome.PASSED,
            duration_s=time.monotonic() - t0,
        )

    async def _execute_wait(self, index: int, step: WaitStep, t0: float) -> StepResult:
        await asyncio.sleep(step.duration_s)
        return StepResult(
            step_index=index,
            step_type="wait",
            description=step.description or f"Wait {step.duration_s:.1f}s",
            outcome=Outcome.PASSED,
            duration_s=time.monotonic() - t0,
        )

    async def _execute_assert(self, index: int, step: AssertStep, t0: float) -> StepResult:
        expected: dict[str, Any] = {}
        actual: dict[str, Any] = {}
        failures: list[str] = []

        for path, expected_val in step.values.items():
            tag = self._tags.resolve(path)
            val = await self._client.read_value(tag.node_id)
            expected[path] = expected_val
            actual[path] = val.value

            if not _values_match(val.value, expected_val, step.tolerance):
                failures.append(f"{path}: expected {expected_val!r}, got {val.value!r}")

        outcome = Outcome.PASSED if not failures else Outcome.FAILED
        error_msg = "; ".join(failures) if failures else None

        return StepResult(
            step_index=index,
            step_type="assert",
            description=step.description or f"Assert {len(step.values)} value(s)",
            outcome=outcome,
            duration_s=time.monotonic() - t0,
            error_message=error_msg,
            expected_values=expected,
            actual_values=actual,
        )

    async def _execute_wait_until(self, index: int, step: WaitUntilStep, t0: float) -> StepResult:
        tag = self._tags.resolve(step.path)
        deadline = time.monotonic() + step.timeout_s

        while time.monotonic() < deadline:
            val = await self._client.read_value(tag.node_id)
            if _values_match(val.value, step.value):
                return StepResult(
                    step_index=index,
                    step_type="wait_until",
                    description=step.description or f"Wait until {step.path} = {step.value!r}",
                    outcome=Outcome.PASSED,
                    duration_s=time.monotonic() - t0,
                    actual_values={step.path: val.value},
                    expected_values={step.path: step.value},
                )
            await asyncio.sleep(step.poll_interval_s)

        # Timed out
        val = await self._client.read_value(tag.node_id)
        return StepResult(
            step_index=index,
            step_type="wait_until",
            description=step.description or f"Wait until {step.path} = {step.value!r}",
            outcome=Outcome.FAILED,
            duration_s=time.monotonic() - t0,
            error_message=(
                f"Timeout after {step.timeout_s}s: {step.path} = {val.value!r} " f"(expected {step.value!r})"
            ),
            actual_values={step.path: val.value},
            expected_values={step.path: step.value},
        )

    async def _execute_read(self, index: int, step: ReadStep, t0: float) -> StepResult:
        actual: dict[str, Any] = {}
        for path in step.paths:
            tag = self._tags.resolve(path)
            val = await self._client.read_value(tag.node_id)
            actual[path] = val.value

        return StepResult(
            step_index=index,
            step_type="read",
            description=step.description or f"Read {len(step.paths)} value(s)",
            outcome=Outcome.PASSED,
            duration_s=time.monotonic() - t0,
            actual_values=actual,
        )

    async def _execute_capture(self, index: int, step: CaptureStep, t0: float) -> StepResult:
        # Resolve paths -> node-ids and build a reverse map for labelling samples.
        node_to_path: dict[str, str] = {}
        node_ids: list[str] = []
        for path in step.paths:
            tag = self._tags.resolve(path)
            node_to_path[tag.node_id] = path
            node_ids.append(tag.node_id)

        # The OPC UA subscription handler enqueues values via `put_nowait`; if this
        # bounded queue (maxsize 10000) saturates, values are silently dropped, so a
        # very high-rate capture can under-report samples.
        queue: asyncio.Queue[OpcUaValue] = asyncio.Queue(maxsize=10000)
        sub_id = await self._client.subscribe(node_ids, queue, interval_ms=step.sampling_interval_ms)

        samples: list[dict[str, Any]] = []
        start = time.monotonic()
        deadline = start + step.duration_s if step.duration_s > 0 else None
        try:
            while True:
                if deadline is None:
                    # `until` mode: poll the queue at a fixed cadence.
                    timeout = 0.1
                else:
                    # duration mode: loop-top check handles expiry; wait the remaining
                    # time, clamped to a small positive minimum so we never pass <= 0.
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    timeout = max(0.001, remaining)
                try:
                    val = await asyncio.wait_for(queue.get(), timeout=timeout)
                except TimeoutError:
                    if deadline is None:
                        # `until` mode with no traffic — poll the stop condition.
                        if step.until_path:
                            tag = self._tags.resolve(step.until_path)
                            cur = await self._client.read_value(tag.node_id)
                            if _values_match(cur.value, step.until_value):
                                break
                    continue
                path = node_to_path.get(val.node_id, val.node_id)
                samples.append(
                    {
                        "t": time.monotonic() - start,
                        "path": path,
                        "value": val.value,
                    }
                )
                if step.until_path and path == step.until_path and _values_match(val.value, step.until_value):
                    break
        finally:
            await self._client.unsubscribe(sub_id)

        out_path = Path(step.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {
                    "meta": {
                        "paths": step.paths,
                        "sampling_interval_ms": step.sampling_interval_ms,
                        "duration_s": step.duration_s,
                    },
                    "samples": samples,
                },
                indent=2,
            )
        )

        return StepResult(
            step_index=index,
            step_type="capture",
            description=step.description or f"Capture {len(step.paths)} path(s)",
            outcome=Outcome.PASSED,
            duration_s=time.monotonic() - t0,
            actual_values={"samples": len(samples), "output": step.output},
            expected_values={},
        )

    async def _execute_snapshot(self, index: int, step: SnapshotStep, t0: float) -> StepResult:
        actual: dict[str, Any] = {}
        for path in step.paths:
            tag = self._tags.resolve(path)
            val = await self._client.read_value(tag.node_id)
            actual[path] = val.value

        self._snapshots[step.id] = actual
        logger.info("Snapshot '%s': %s", step.id, actual)

        return StepResult(
            step_index=index,
            step_type="snapshot",
            description=step.description or f"Snapshot '{step.id}' ({len(step.paths)} value(s))",
            outcome=Outcome.PASSED,
            duration_s=time.monotonic() - t0,
            actual_values=actual,
        )

    async def _execute_restore(self, index: int, step: RestoreStep, t0: float) -> StepResult:
        saved = self._snapshots.get(step.id)
        if saved is None:
            return StepResult(
                step_index=index,
                step_type="restore",
                description=step.description or f"Restore '{step.id}'",
                outcome=Outcome.ERROR,
                duration_s=time.monotonic() - t0,
                error_message=f"No snapshot found with id '{step.id}'",
            )

        for path, value in saved.items():
            tag = self._tags.resolve(path)
            await self._client.write_value(tag.node_id, value, tag.data_type)

        logger.info("Restored '%s': %s", step.id, saved)

        return StepResult(
            step_index=index,
            step_type="restore",
            description=step.description or f"Restore '{step.id}' ({len(saved)} value(s))",
            outcome=Outcome.PASSED,
            duration_s=time.monotonic() - t0,
            actual_values=saved,
        )

    # ------------------------------------------------------------------
    # Modbus executors
    # ------------------------------------------------------------------

    def _modbus_unavailable_result(
        self, index: int, step_type: str, description: str, t0: float
    ) -> StepResult:
        """Return an ERROR step result when a modbus_* step is hit without a configured client."""
        return StepResult(
            step_index=index,
            step_type=step_type,
            description=description or step_type,
            outcome=Outcome.ERROR,
            duration_s=time.monotonic() - t0,
            error_message=(
                f"Modbus client is not configured but a {step_type!r} step was hit. "
                "Add a 'sim.modbus' block to plc.yaml (host, port, unit_id, timeout_s)."
            ),
        )

    async def _execute_modbus_read(self, index: int, step: ModbusReadStep, t0: float) -> StepResult:
        if self._modbus_client is None:
            return self._modbus_unavailable_result(index, "modbus_read", step.description, t0)

        # Always the block call, even for the count=1 default: a single code path
        # is what keeps `count` from being dropped again. The client returns one
        # entry per register, keyed by that register's own spec, so a range shows
        # up in the report as HOLDING:10, HOLDING:11, ... rather than one opaque
        # list under the starting address. plc-core cannot build those keys
        # itself — it must not import plc-modbus to parse the spec.
        try:
            values = await self._modbus_client.read_register_block(
                step.register, step.count, dtype=step.dtype
            )
        except Exception as e:
            return StepResult(
                step_index=index,
                step_type="modbus_read",
                description=step.description or f"Modbus read {step.register}",
                outcome=Outcome.ERROR,
                duration_s=time.monotonic() - t0,
                error_message=f"{type(e).__name__}: {e}",
            )

        default_description = (
            f"Modbus read {step.register}"
            if step.count == 1
            else f"Modbus read {step.count} registers from {step.register}"
        )
        return StepResult(
            step_index=index,
            step_type="modbus_read",
            description=step.description or default_description,
            outcome=Outcome.PASSED,
            duration_s=time.monotonic() - t0,
            actual_values=dict(values),
        )

    async def _execute_modbus_assert(self, index: int, step: ModbusAssertStep, t0: float) -> StepResult:
        if self._modbus_client is None:
            return self._modbus_unavailable_result(index, "modbus_assert", step.description, t0)

        expected: dict[str, Any] = {}
        actual: dict[str, Any] = {}
        failures: list[str] = []

        for register, expected_val in step.values.items():
            # Booleans (bit specs / coils / discretes) read as bool;
            # uint16 by default for whole-register values.
            dtype = "bool" if isinstance(expected_val, bool) else "uint16"
            try:
                val = await self._modbus_client.read_register_at(register, dtype=dtype)
            except Exception as e:
                return StepResult(
                    step_index=index,
                    step_type="modbus_assert",
                    description=step.description or f"Modbus assert {len(step.values)} register(s)",
                    outcome=Outcome.ERROR,
                    duration_s=time.monotonic() - t0,
                    error_message=f"{register}: {type(e).__name__}: {e}",
                    expected_values=expected,
                    actual_values=actual,
                )

            expected[register] = expected_val
            actual[register] = val

            if not _values_match(val, expected_val, step.tolerance):
                failures.append(f"{register}: expected {expected_val!r}, got {val!r}")

        outcome = Outcome.PASSED if not failures else Outcome.FAILED
        error_msg = "; ".join(failures) if failures else None

        return StepResult(
            step_index=index,
            step_type="modbus_assert",
            description=step.description or f"Modbus assert {len(step.values)} register(s)",
            outcome=outcome,
            duration_s=time.monotonic() - t0,
            error_message=error_msg,
            expected_values=expected,
            actual_values=actual,
        )

    async def _execute_modbus_wait_until(
        self, index: int, step: ModbusWaitUntilStep, t0: float
    ) -> StepResult:
        if self._modbus_client is None:
            return self._modbus_unavailable_result(index, "modbus_wait_until", step.description, t0)

        # If user provided a bool target, force bool decoding regardless of dtype param.
        dtype = "bool" if isinstance(step.value, bool) else step.dtype

        deadline = time.monotonic() + step.timeout_s
        last_value: Any = None

        while time.monotonic() < deadline:
            try:
                last_value = await self._modbus_client.read_register_at(step.register, dtype=dtype)
            except Exception as e:
                return StepResult(
                    step_index=index,
                    step_type="modbus_wait_until",
                    description=step.description or f"Modbus wait until {step.register} = {step.value!r}",
                    outcome=Outcome.ERROR,
                    duration_s=time.monotonic() - t0,
                    error_message=f"{type(e).__name__}: {e}",
                )

            if _values_match(last_value, step.value):
                return StepResult(
                    step_index=index,
                    step_type="modbus_wait_until",
                    description=step.description or f"Modbus wait until {step.register} = {step.value!r}",
                    outcome=Outcome.PASSED,
                    duration_s=time.monotonic() - t0,
                    actual_values={step.register: last_value},
                    expected_values={step.register: step.value},
                )
            await asyncio.sleep(step.poll_interval_s)

        return StepResult(
            step_index=index,
            step_type="modbus_wait_until",
            description=step.description or f"Modbus wait until {step.register} = {step.value!r}",
            outcome=Outcome.FAILED,
            duration_s=time.monotonic() - t0,
            error_message=(
                f"Timeout after {step.timeout_s}s: {step.register} = {last_value!r} "
                f"(expected {step.value!r})"
            ),
            actual_values={step.register: last_value},
            expected_values={step.register: step.value},
        )

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def _print_step(self, index: int, result: StepResult) -> None:
        """Print a single step result to console."""
        if result.outcome == Outcome.PASSED:
            icon = "[green]PASS[/green]"
        elif result.outcome == Outcome.WARNING:
            icon = "[yellow]WARN[/yellow]"
        elif result.outcome == Outcome.FAILED:
            icon = "[red]FAIL[/red]"
        elif result.outcome == Outcome.SKIPPED:
            icon = "[yellow]SKIP[/yellow]"
        else:
            icon = "[red]ERR [/red]"

        desc = result.description or result.step_type
        self._console.print(f"  [{icon}]  {index + 1}. {desc:<50s} {result.duration_s:.2f}s")

        if result.failed and self._verbose and result.error_message:
            self._console.print(f"         [red]{result.error_message}[/red]")

        if result.outcome == Outcome.WARNING and result.error_message:
            self._console.print(f"         [yellow]{result.error_message}[/yellow]")

        if result.outcome == Outcome.PASSED and self._verbose and result.actual_values:
            for path, val in result.actual_values.items():
                self._console.print(f"         [dim]{path} = {val!r}[/dim]")
