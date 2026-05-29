"""Sim-specific test step types: flash and stable assertions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from plc_core.testing.schema import parse_duration


@dataclass
class AssertStableStep:
    """Assert a variable holds a value for a duration."""

    step_type: str = "assert_stable"
    description: str = ""
    path: str = ""
    value: Any = None
    duration_s: float = 2.0
    poll_interval_s: float = 0.25


@dataclass
class AssertFlashStep:
    """Monitor a boolean signal and validate its flash pattern."""

    step_type: str = "assert_flash"
    description: str = ""
    path: str = ""
    pattern: str = "FL1"
    duration_s: float = 5.0
    poll_interval_s: float = 0.05
    tolerance_s: float = 0.15


def parse_assert_stable(raw: dict[str, Any]) -> AssertStableStep:
    """Parse assert_stable step from YAML."""
    return AssertStableStep(
        description=raw.get("description", ""),
        path=raw.get("path", ""),
        value=raw.get("value"),
        duration_s=parse_duration(raw.get("duration", "2s")),
        poll_interval_s=parse_duration(raw.get("poll_interval", "250ms")),
    )


def parse_assert_flash(raw: dict[str, Any]) -> AssertFlashStep:
    """Parse assert_flash step from YAML."""
    return AssertFlashStep(
        description=raw.get("description", ""),
        path=raw.get("path", ""),
        pattern=raw.get("pattern", "FL1").upper(),
        duration_s=parse_duration(raw.get("duration", "5s")),
        poll_interval_s=parse_duration(raw.get("poll_interval", "50ms")),
        tolerance_s=float(raw.get("tolerance", 0.15)),
    )
