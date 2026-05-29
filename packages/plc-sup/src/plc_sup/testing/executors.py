"""Supervision-specific step executors."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from plc_core.testing.models import Outcome, StepResult

if TYPE_CHECKING:
    from plc_core.testing.runner import ScenarioRunner

    from plc_sup.testing.clients import ApiVerifier, DbVerifier, InfraClient, RedisVerifier
    from plc_sup.testing.steps import InfraStep, VerifyApiStep, VerifyDbStep, VerifyRedisStep

logger = logging.getLogger(__name__)


async def execute_verify_redis(
    runner: ScenarioRunner,
    index: int,
    step: VerifyRedisStep,
    t0: float,
    *,
    redis_client: RedisVerifier,
) -> StepResult:
    """Verify a value appears in a Redis stream."""
    deadline = time.monotonic() + step.timeout_s

    while time.monotonic() < deadline:
        actual = await redis_client.get_latest_stream_value(step.stream, step.path)
        if actual is not None and actual == step.value:
            return StepResult(
                step_index=index,
                step_type="verify_redis",
                description=step.description or f"Verify {step.stream}:{step.path} = {step.value!r}",
                outcome=Outcome.PASSED,
                duration_s=time.monotonic() - t0,
                expected_values={f"{step.stream}:{step.path}": step.value},
                actual_values={f"{step.stream}:{step.path}": actual},
            )
        await asyncio.sleep(step.poll_interval_s)

    # Timeout
    actual = await redis_client.get_latest_stream_value(step.stream, step.path)
    return StepResult(
        step_index=index,
        step_type="verify_redis",
        description=step.description or f"Verify {step.stream}:{step.path} = {step.value!r}",
        outcome=Outcome.FAILED,
        duration_s=time.monotonic() - t0,
        error_message=(
            f"Timeout after {step.timeout_s}s: {step.stream}:{step.path} = "
            f"{actual!r} (expected {step.value!r})"
        ),
        expected_values={f"{step.stream}:{step.path}": step.value},
        actual_values={f"{step.stream}:{step.path}": actual},
    )


async def execute_verify_db(
    runner: ScenarioRunner,
    index: int,
    step: VerifyDbStep,
    t0: float,
    *,
    db_client: DbVerifier,
) -> StepResult:
    """Verify a record exists in TimescaleDB."""
    deadline = time.monotonic() + step.timeout_s

    while time.monotonic() < deadline:
        count = await db_client.query_count(step.query)
        if count >= step.expected_rows:
            return StepResult(
                step_index=index,
                step_type="verify_db",
                description=step.description or f"Verify DB: {step.query[:50]}...",
                outcome=Outcome.PASSED,
                duration_s=time.monotonic() - t0,
                expected_values={"rows": step.expected_rows},
                actual_values={"rows": count},
            )
        await asyncio.sleep(step.poll_interval_s)

    count = await db_client.query_count(step.query)
    return StepResult(
        step_index=index,
        step_type="verify_db",
        description=step.description or f"Verify DB: {step.query[:50]}...",
        outcome=Outcome.FAILED,
        duration_s=time.monotonic() - t0,
        error_message=f"Timeout after {step.timeout_s}s: got {count} rows (expected >= {step.expected_rows})",
        expected_values={"rows": step.expected_rows},
        actual_values={"rows": count},
    )


async def execute_verify_api(
    runner: ScenarioRunner,
    index: int,
    step: VerifyApiStep,
    t0: float,
    *,
    api_client: ApiVerifier,
) -> StepResult:
    """Verify an API endpoint response."""
    try:
        status_code, body = await api_client.request(step.endpoint, step.method, step.timeout_s)
    except Exception as e:
        return StepResult(
            step_index=index,
            step_type="verify_api",
            description=step.description or f"Verify API {step.method} {step.endpoint}",
            outcome=Outcome.ERROR,
            duration_s=time.monotonic() - t0,
            error_message=f"Request failed: {e}",
        )

    failures: list[str] = []
    if status_code != step.expected_status:
        failures.append(f"status: expected {step.expected_status}, got {status_code}")

    if step.expected_json and body:
        for key, expected_val in step.expected_json.items():
            actual_val = body.get(key)
            if actual_val != expected_val:
                failures.append(f"{key}: expected {expected_val!r}, got {actual_val!r}")

    outcome = Outcome.PASSED if not failures else Outcome.FAILED

    return StepResult(
        step_index=index,
        step_type="verify_api",
        description=step.description or f"Verify API {step.method} {step.endpoint}",
        outcome=outcome,
        duration_s=time.monotonic() - t0,
        error_message="; ".join(failures) if failures else None,
        expected_values={"status": step.expected_status},
        actual_values={"status": status_code, "body": body},
    )


async def execute_infra(
    runner: ScenarioRunner,
    index: int,
    step: InfraStep,
    t0: float,
    *,
    infra_client: InfraClient,
) -> StepResult:
    """Execute an infrastructure action."""
    try:
        if step.action == "docker_stop":
            await infra_client.docker_stop(step.container)
            return StepResult(
                step_index=index,
                step_type="infra",
                description=step.description or f"docker stop {step.container}",
                outcome=Outcome.PASSED,
                duration_s=time.monotonic() - t0,
            )

        if step.action == "docker_start":
            await infra_client.docker_start(step.container)
            return StepResult(
                step_index=index,
                step_type="infra",
                description=step.description or f"docker start {step.container}",
                outcome=Outcome.PASSED,
                duration_s=time.monotonic() - t0,
            )

        if step.action == "docker_restart":
            await infra_client.docker_restart(step.container)
            return StepResult(
                step_index=index,
                step_type="infra",
                description=step.description or f"docker restart {step.container}",
                outcome=Outcome.PASSED,
                duration_s=time.monotonic() - t0,
            )

        if step.action == "wait_healthy":
            ok = await infra_client.wait_healthy(step.container, step.timeout_s)
            return StepResult(
                step_index=index,
                step_type="infra",
                description=step.description or f"Wait for {step.container} healthy",
                outcome=Outcome.PASSED if ok else Outcome.FAILED,
                duration_s=time.monotonic() - t0,
                error_message=(
                    None if ok else f"Container {step.container} not healthy after {step.timeout_s}s"
                ),
            )

        if step.action == "wait_all_healthy":
            ok = await infra_client.wait_all_healthy(step.timeout_s)
            return StepResult(
                step_index=index,
                step_type="infra",
                description=step.description or "Wait for all containers healthy",
                outcome=Outcome.PASSED if ok else Outcome.FAILED,
                duration_s=time.monotonic() - t0,
                error_message=(None if ok else f"Not all containers healthy after {step.timeout_s}s"),
            )

        if step.action == "wait_for_user":
            await infra_client.wait_for_user(step.description)
            return StepResult(
                step_index=index,
                step_type="infra",
                description=step.description,
                outcome=Outcome.PASSED,
                duration_s=time.monotonic() - t0,
            )

        return StepResult(
            step_index=index,
            step_type="infra",
            description=step.description,
            outcome=Outcome.ERROR,
            duration_s=time.monotonic() - t0,
            error_message=f"Unknown infra action: {step.action!r}",
        )

    except Exception as e:
        return StepResult(
            step_index=index,
            step_type="infra",
            description=step.description,
            outcome=Outcome.ERROR,
            duration_s=time.monotonic() - t0,
            error_message=str(e),
        )
