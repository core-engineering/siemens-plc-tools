"""Sim-specific step executors: flash and stable assertions."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from plc_core.testing.models import Outcome, StepResult
from plc_core.testing.runner import ScenarioRunner, _values_match

if TYPE_CHECKING:
    from plc_sim.testing.steps import AssertFlashStep, AssertStableStep


# Flash pattern definitions: (on_time_s, off_time_s) or None for continuous ON
FLASH_PATTERNS: dict[str, tuple[float, float] | None] = {
    "FL1": (0.5, 0.5),
    "FL2": None,
    "FL3": (0.5, 1.5),
}


async def execute_assert_stable(
    runner: ScenarioRunner, index: int, step: AssertStableStep, t0: float
) -> StepResult:
    """Execute an assert_stable step."""
    tag = runner.tags.resolve(step.path)
    deadline = time.monotonic() + step.duration_s

    while time.monotonic() < deadline:
        val = await runner.client.read_value(tag.node_id)
        if not _values_match(val.value, step.value):
            return StepResult(
                step_index=index,
                step_type="assert_stable",
                description=step.description or f"Assert {step.path} stable at {step.value!r}",
                outcome=Outcome.FAILED,
                duration_s=time.monotonic() - t0,
                error_message=f"{step.path} changed to {val.value!r} (expected {step.value!r})",
                actual_values={step.path: val.value},
                expected_values={step.path: step.value},
            )
        await asyncio.sleep(step.poll_interval_s)

    return StepResult(
        step_index=index,
        step_type="assert_stable",
        description=step.description or f"Assert {step.path} stable at {step.value!r}",
        outcome=Outcome.PASSED,
        duration_s=time.monotonic() - t0,
        actual_values={step.path: step.value},
        expected_values={step.path: step.value},
    )


async def execute_assert_flash(
    runner: ScenarioRunner, index: int, step: AssertFlashStep, t0: float
) -> StepResult:
    """Execute an assert_flash step."""
    pattern_def = FLASH_PATTERNS.get(step.pattern)
    if step.pattern not in FLASH_PATTERNS:
        return StepResult(
            step_index=index,
            step_type="assert_flash",
            description=step.description,
            outcome=Outcome.ERROR,
            duration_s=time.monotonic() - t0,
            error_message=f"Unknown flash pattern: {step.pattern!r} (valid: FL1, FL2, FL3)",
        )

    tag = runner.tags.resolve(step.path)

    # Sample the signal
    samples: list[tuple[float, bool]] = []
    deadline = time.monotonic() + step.duration_s
    while time.monotonic() < deadline:
        sample = await runner.client.read_value(tag.node_id)
        samples.append((time.monotonic() - t0, bool(sample.value)))
        await asyncio.sleep(step.poll_interval_s)

    if not samples:
        return StepResult(
            step_index=index,
            step_type="assert_flash",
            description=step.description,
            outcome=Outcome.ERROR,
            duration_s=time.monotonic() - t0,
            error_message="No samples collected",
        )

    # FL2: continuous ON
    if pattern_def is None:
        false_count = sum(1 for _, v in samples if not v)
        if false_count == 0:
            return StepResult(
                step_index=index,
                step_type="assert_flash",
                description=step.description or f"Assert {step.path} continuous ON (FL2)",
                outcome=Outcome.PASSED,
                duration_s=time.monotonic() - t0,
                actual_values={"pattern": "FL2", "samples": len(samples), "all_true": True},
            )
        return StepResult(
            step_index=index,
            step_type="assert_flash",
            description=step.description or f"Assert {step.path} continuous ON (FL2)",
            outcome=Outcome.FAILED,
            duration_s=time.monotonic() - t0,
            error_message=f"Expected continuous ON, but {false_count}/{len(samples)} samples were FALSE",
            actual_values={"pattern": "FL2", "false_count": false_count, "total": len(samples)},
        )

    # FL1/FL3: transitions
    expected_on, expected_off = pattern_def
    _DEAD_SIGNAL_THRESHOLD = 0.05
    true_count = sum(1 for _, v in samples if v)
    true_ratio = true_count / len(samples)

    if true_ratio < _DEAD_SIGNAL_THRESHOLD:
        return StepResult(
            step_index=index,
            step_type="assert_flash",
            description=step.description or f"Assert {step.path} flashing at {step.pattern}",
            outcome=Outcome.FAILED,
            duration_s=time.monotonic() - t0,
            error_message=(
                f"Signal appears dead: {true_count}/{len(samples)} samples TRUE "
                f"({true_ratio:.1%}), expected {step.pattern} flashing"
            ),
            actual_values={
                "pattern": step.pattern,
                "true_ratio": round(true_ratio, 3),
                "samples": len(samples),
            },
        )

    transitions: list[tuple[float, str]] = []
    on_durations: list[float] = []
    off_durations: list[float] = []
    last_val = samples[0][1]
    last_change_t = samples[0][0]

    for ts, val in samples[1:]:
        if val != last_val:
            duration = ts - last_change_t
            if last_val:
                on_durations.append(duration)
                transitions.append((ts, "falling"))
            else:
                off_durations.append(duration)
                transitions.append((ts, "rising"))
            last_val = val
            last_change_t = ts

    if len(transitions) < 2:
        return StepResult(
            step_index=index,
            step_type="assert_flash",
            description=step.description or f"Assert {step.path} flashing at {step.pattern}",
            outcome=Outcome.WARNING,
            duration_s=time.monotonic() - t0,
            error_message=(
                f"Signal active ({true_ratio:.0%} TRUE) but only {len(transitions)} transition(s) "
                f"in {step.duration_s}s — possible network/PLC jitter"
            ),
            actual_values={
                "pattern": step.pattern,
                "transitions": len(transitions),
                "true_ratio": round(true_ratio, 3),
                "samples": len(samples),
            },
        )

    tol = step.tolerance_s
    failures: list[str] = []

    if on_durations:
        check_on = on_durations[1:] if len(on_durations) > 1 else on_durations
        avg_on = sum(check_on) / len(check_on)
        if abs(avg_on - expected_on) > tol:
            failures.append(f"ON duration: avg {avg_on:.3f}s, expected {expected_on}s (±{tol}s)")

    if off_durations:
        check_off = off_durations[1:] if len(off_durations) > 1 else off_durations
        avg_off = sum(check_off) / len(check_off)
        if abs(avg_off - expected_off) > tol:
            failures.append(f"OFF duration: avg {avg_off:.3f}s, expected {expected_off}s (±{tol}s)")

    outcome = Outcome.PASSED if not failures else Outcome.WARNING
    actual: dict[str, Any] = {
        "pattern": step.pattern,
        "transitions": len(transitions),
        "true_ratio": round(true_ratio, 3),
        "samples": len(samples),
        "avg_on_s": round(sum(on_durations) / len(on_durations), 3) if on_durations else None,
        "avg_off_s": round(sum(off_durations) / len(off_durations), 3) if off_durations else None,
        "expected_on_s": expected_on,
        "expected_off_s": expected_off,
    }

    return StepResult(
        step_index=index,
        step_type="assert_flash",
        description=step.description or f"Assert {step.path} flashing at {step.pattern}",
        outcome=outcome,
        duration_s=time.monotonic() - t0,
        error_message="; ".join(failures) if failures else None,
        actual_values=actual,
        expected_values={"on_s": expected_on, "off_s": expected_off},
    )
