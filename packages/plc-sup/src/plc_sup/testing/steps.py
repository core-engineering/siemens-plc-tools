"""Supervision-specific test step types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from plc_core.testing.schema import parse_duration, register_step_parser


@dataclass
class VerifyRedisStep:
    """Verify a value appears in a Redis stream."""

    step_type: str = "verify_redis"
    description: str = ""
    stream: str = ""
    path: str = ""
    value: Any = None
    timeout_s: float = 5.0
    poll_interval_s: float = 0.5


@dataclass
class VerifyDbStep:
    """Verify a record exists in TimescaleDB."""

    step_type: str = "verify_db"
    description: str = ""
    query: str = ""
    expected_rows: int = 1
    timeout_s: float = 10.0
    poll_interval_s: float = 1.0


@dataclass
class VerifyApiStep:
    """Verify an API endpoint response."""

    step_type: str = "verify_api"
    description: str = ""
    endpoint: str = ""
    method: str = "GET"
    expected_status: int = 200
    expected_json: dict[str, Any] | None = None
    timeout_s: float = 5.0


def _parse_verify_redis(raw: dict[str, Any]) -> VerifyRedisStep:
    return VerifyRedisStep(
        description=raw.get("description", ""),
        stream=raw.get("stream", ""),
        path=raw.get("path", ""),
        value=raw.get("value"),
        timeout_s=parse_duration(raw.get("timeout", "5s")),
        poll_interval_s=parse_duration(raw.get("poll_interval", "500ms")),
    )


def _parse_verify_db(raw: dict[str, Any]) -> VerifyDbStep:
    return VerifyDbStep(
        description=raw.get("description", ""),
        query=raw.get("query", ""),
        expected_rows=raw.get("expected_rows", 1),
        timeout_s=parse_duration(raw.get("timeout", "10s")),
        poll_interval_s=parse_duration(raw.get("poll_interval", "1s")),
    )


def _parse_verify_api(raw: dict[str, Any]) -> VerifyApiStep:
    return VerifyApiStep(
        description=raw.get("description", ""),
        endpoint=raw.get("endpoint", ""),
        method=raw.get("method", "GET").upper(),
        expected_status=raw.get("expected_status", 200),
        expected_json=raw.get("expected_json"),
        timeout_s=parse_duration(raw.get("timeout", "5s")),
    )


# Register step parsers
register_step_parser("verify_redis", _parse_verify_redis)
register_step_parser("verify_db", _parse_verify_db)
register_step_parser("verify_api", _parse_verify_api)


@dataclass
class InfraStep:
    """Infrastructure action: docker stop/start/restart or wait for user."""

    step_type: str = "infra"
    description: str = ""
    action: str = ""  # docker_stop | docker_start | docker_restart | wait_for_user | wait_healthy
    container: str = ""  # container name (for docker actions)
    timeout_s: float = 120.0  # timeout for wait_healthy


def _parse_infra(raw: dict[str, Any]) -> InfraStep:
    return InfraStep(
        description=raw.get("description", ""),
        action=raw.get("action", ""),
        container=raw.get("container", ""),
        timeout_s=parse_duration(raw.get("timeout", "120s")),
    )


register_step_parser("infra", _parse_infra)
