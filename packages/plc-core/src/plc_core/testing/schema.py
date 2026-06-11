"""YAML test scenario parsing and validation."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Duration parsing
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"^\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ms|s|m|min)?\s*$", re.IGNORECASE)


def parse_duration(text: str | int | float) -> float:
    """Parse a duration string into seconds.

    Supported formats: ``500ms``, ``5.5s``, ``1m``, ``90`` (bare number = seconds).
    """
    if isinstance(text, (int, float)):
        return float(text)

    m = _DURATION_RE.match(str(text))
    if not m:
        raise ValueError(f"Invalid duration: {text!r}")

    value = float(m.group("value"))
    unit = (m.group("unit") or "s").lower()

    if unit == "ms":
        return value / 1000.0
    if unit in ("m", "min"):
        return value * 60.0
    return value  # seconds


# ---------------------------------------------------------------------------
# Step dataclasses
# ---------------------------------------------------------------------------


@dataclass
class WriteStep:
    """Write values to PLC inputs."""

    step_type: str = "write"
    description: str = ""
    values: dict[str, Any] = field(default_factory=dict)


@dataclass
class WaitStep:
    """Pause execution for a fixed duration."""

    step_type: str = "wait"
    description: str = ""
    duration_s: float = 0.0


@dataclass
class AssertStep:
    """Assert PLC outputs match expected values."""

    step_type: str = "assert"
    description: str = ""
    values: dict[str, Any] = field(default_factory=dict)
    tolerance: float | None = None


@dataclass
class WaitUntilStep:
    """Poll a variable until it matches expected value or timeout."""

    step_type: str = "wait_until"
    description: str = ""
    path: str = ""
    value: Any = None
    timeout_s: float = 10.0
    poll_interval_s: float = 0.5


@dataclass
class ReadStep:
    """Read and log values (always passes)."""

    step_type: str = "read"
    description: str = ""
    paths: list[str] = field(default_factory=list)


@dataclass
class SnapshotStep:
    """Read and store PLC values for later restoration.

    Reads the current values of the specified paths and stores them
    under the given *id*.  A subsequent :class:`RestoreStep` with the
    same *id* writes the saved values back to the PLC.
    """

    step_type: str = "snapshot"
    description: str = ""
    id: str = ""
    paths: list[str] = field(default_factory=list)


@dataclass
class RestoreStep:
    """Restore previously snapshotted values to the PLC.

    Looks up the snapshot saved under *id* by a prior
    :class:`SnapshotStep` and writes every path/value pair back.
    """

    step_type: str = "restore"
    description: str = ""
    id: str = ""


@dataclass
class ModbusReadStep:
    """Read one or more Modbus registers and log their value.

    Always passes (logging only). Use :class:`ModbusAssertStep` to fail
    on mismatch or :class:`ModbusWaitUntilStep` to poll for a target.

    The ``register`` field uses the spec ``"AREA:ADDRESS"`` or
    ``"AREA:ADDRESS/BIT"`` — see ``plc_modbus.parse_register_address`` for
    valid areas (HOLDING, INPUT, COIL, DISCRETE).
    """

    step_type: str = "modbus_read"
    description: str = ""
    register: str = ""
    count: int = 1
    dtype: str = "uint16"


@dataclass
class ModbusAssertStep:
    """Assert that one or more Modbus registers hold expected values.

    ``values`` is a dict mapping register specs to expected values, e.g.::

        {"HOLDING:0/6": True, "HOLDING:42": 12345}

    Tolerance applies only to numeric comparisons.
    """

    step_type: str = "modbus_assert"
    description: str = ""
    values: dict[str, Any] = field(default_factory=dict)
    tolerance: float | None = None


@dataclass
class ModbusWaitUntilStep:
    """Poll a single Modbus register until it matches a target value or timeout."""

    step_type: str = "modbus_wait_until"
    description: str = ""
    register: str = ""
    value: Any = None
    timeout_s: float = 10.0
    poll_interval_s: float = 0.5
    dtype: str = "uint16"


@dataclass
class CaptureStep:
    """Record an OPC UA variable stream by subscription for a fixed window."""

    step_type: str = "capture"
    description: str = ""
    paths: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    until_path: str = ""
    until_value: Any = None
    output: str = ""
    sampling_interval_ms: int = 50


Step = (
    WriteStep
    | WaitStep
    | AssertStep
    | WaitUntilStep
    | ReadStep
    | SnapshotStep
    | RestoreStep
    | ModbusReadStep
    | ModbusAssertStep
    | ModbusWaitUntilStep
    | CaptureStep
)


@dataclass
class SuiteSetup:
    """Global initial state applied before any scenario runs.

    Loaded from ``setup.yaml`` in the test directory.

    Supports two-phase initialization:

    1. ``values`` are written first, then the runner waits ``settle_time_s``.
    2. If ``post_values`` is non-empty, those are written next and the runner
       waits ``post_settle_time_s``.

    This is needed for safety PLC reset sequences where the first phase
    forces a transient configuration (e.g. arm type ``'none'``) and the
    second phase restores operational settings.
    """

    description: str = ""
    settle_time_s: float = 1.0
    values: dict[str, Any] = field(default_factory=dict)
    post_values: dict[str, Any] = field(default_factory=dict)
    post_settle_time_s: float = 1.0


@dataclass
class Precondition:
    """Expected state before scenario starts."""

    path: str
    value: Any


@dataclass
class Scenario:
    """A complete test scenario parsed from YAML."""

    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    timeout_s: float = 60.0
    preconditions: list[Precondition] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    cleanup: list[Step] = field(default_factory=list)
    source_file: Path | None = None


# ---------------------------------------------------------------------------
# Step parser registry
# ---------------------------------------------------------------------------

_STEP_PARSERS: dict[str, Callable[[dict[str, Any]], Any]] = {}


def register_step_parser(step_type: str, parser: Callable[[dict[str, Any]], Any]) -> None:
    """Register a parser function for a custom step type.

    Parameters
    ----------
    step_type : str
        The step type identifier (e.g. ``"write"``, ``"assert_flash"``).
    parser : Callable[[dict[str, Any]], Any]
        A function that takes a raw YAML dict and returns a typed step object.
        The return type is ``Any`` because downstream packages register
        their own step subtypes (VerifyRedisStep, AssertFlashStep, ...) that
        are not part of the core ``Step`` union.
    """
    _STEP_PARSERS[step_type] = parser


# ---------------------------------------------------------------------------
# YAML -> typed objects
# ---------------------------------------------------------------------------


def _parse_step(raw: dict[str, Any]) -> Step:
    """Convert a raw YAML step dict to a typed Step object."""
    step_type = raw.get("step", "").lower()

    parser = _STEP_PARSERS.get(step_type)
    if parser is not None:
        # Parsers may return Step subtypes registered by downstream packages
        # (VerifyRedisStep, AssertFlashStep, ...). The registry is intentionally
        # polymorphic; see register_step_parser.
        return parser(raw)  # type: ignore[no-any-return]

    raise ValueError(f"Unknown step type: {step_type!r}")


def parse_scenario(path: Path) -> Scenario:
    """Load a YAML file and return a typed Scenario."""
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    if not isinstance(data, dict) or "scenario" not in data:
        raise ValueError(f"{path}: missing top-level 'scenario' key")

    sc = data["scenario"]

    # Timeout
    timeout_s = parse_duration(sc.get("timeout", "60s"))

    # Preconditions
    preconditions = [Precondition(path=p["path"], value=p["value"]) for p in sc.get("preconditions", [])]

    # Steps
    steps = [_parse_step(s) for s in sc.get("steps", [])]

    # Cleanup
    cleanup = [_parse_step(s) for s in sc.get("cleanup", [])]

    return Scenario(
        name=sc.get("name", path.stem),
        description=sc.get("description", ""),
        tags=[str(t) for t in sc.get("tags", [])],
        timeout_s=timeout_s,
        preconditions=preconditions,
        steps=steps,
        cleanup=cleanup,
        source_file=path,
    )


def parse_setup(test_dir: Path) -> SuiteSetup | None:
    """Load the optional ``setup.yaml`` from the test directory.

    Returns None if no setup file exists.
    """
    for name in ("setup.yaml", "setup.yml"):
        path = test_dir / name
        if path.exists():
            text = path.read_text(encoding="utf-8")
            data = yaml.safe_load(text)

            if not isinstance(data, dict) or "setup" not in data:
                raise ValueError(f"{path}: missing top-level 'setup' key")

            s = data["setup"]
            return SuiteSetup(
                description=s.get("description", ""),
                settle_time_s=parse_duration(s.get("settle_time", "1s")),
                values=s.get("values", {}),
                post_values=s.get("post_values", {}),
                post_settle_time_s=parse_duration(s.get("post_settle_time", "1s")),
            )

    return None


def discover_scenario_files(test_dir: Path) -> list[Path]:
    """Find all YAML test scenario files in a directory.

    Matches ``test_*.yaml``, ``test_*.yml``, ``EFAT_*.yaml``, and ``EFAT_*.yml`` (recursive).
    """
    if not test_dir.is_dir():
        return []

    files: list[Path] = []
    for pattern in ("test_*.yaml", "test_*.yml", "EFAT_*.yaml", "EFAT_*.yml"):
        files.extend(test_dir.rglob(pattern))

    return sorted(set(files))


# ---------------------------------------------------------------------------
# Register base step parsers
# ---------------------------------------------------------------------------


def _parse_write(raw: dict[str, Any]) -> WriteStep:
    return WriteStep(description=raw.get("description", ""), values=raw.get("values", {}))


def _parse_wait(raw: dict[str, Any]) -> WaitStep:
    return WaitStep(
        description=raw.get("description", ""),
        duration_s=parse_duration(raw.get("duration", "0s")),
    )


def _parse_assert(raw: dict[str, Any]) -> AssertStep:
    tolerance = raw.get("tolerance")
    return AssertStep(
        description=raw.get("description", ""),
        values=raw.get("values", {}),
        tolerance=float(tolerance) if tolerance is not None else None,
    )


def _parse_wait_until(raw: dict[str, Any]) -> WaitUntilStep:
    return WaitUntilStep(
        description=raw.get("description", ""),
        path=raw.get("path", ""),
        value=raw.get("value"),
        timeout_s=parse_duration(raw.get("timeout", "10s")),
        poll_interval_s=parse_duration(raw.get("poll_interval", "500ms")),
    )


def _parse_read(raw: dict[str, Any]) -> ReadStep:
    return ReadStep(description=raw.get("description", ""), paths=raw.get("paths", []))


def _parse_snapshot(raw: dict[str, Any]) -> SnapshotStep:
    snap_id = raw.get("id", "")
    if not snap_id:
        raise ValueError("snapshot step requires an 'id' field")
    return SnapshotStep(
        description=raw.get("description", ""),
        id=snap_id,
        paths=raw.get("paths", []),
    )


def _parse_restore(raw: dict[str, Any]) -> RestoreStep:
    snap_id = raw.get("id", "")
    if not snap_id:
        raise ValueError("restore step requires an 'id' field")
    return RestoreStep(description=raw.get("description", ""), id=snap_id)


def _parse_modbus_read(raw: dict[str, Any]) -> ModbusReadStep:
    register = raw.get("register", "")
    if not register:
        raise ValueError("modbus_read step requires a 'register' field")
    return ModbusReadStep(
        description=raw.get("description", ""),
        register=str(register),
        count=int(raw.get("count", 1)),
        dtype=str(raw.get("dtype", "uint16")),
    )


def _parse_modbus_assert(raw: dict[str, Any]) -> ModbusAssertStep:
    values = raw.get("values", {})
    if not isinstance(values, dict) or not values:
        raise ValueError("modbus_assert step requires a non-empty 'values' dict")
    tolerance = raw.get("tolerance")
    return ModbusAssertStep(
        description=raw.get("description", ""),
        values=values,
        tolerance=float(tolerance) if tolerance is not None else None,
    )


def _parse_modbus_wait_until(raw: dict[str, Any]) -> ModbusWaitUntilStep:
    register = raw.get("register", "")
    if not register:
        raise ValueError("modbus_wait_until step requires a 'register' field")
    if "value" not in raw:
        raise ValueError("modbus_wait_until step requires a 'value' field")
    return ModbusWaitUntilStep(
        description=raw.get("description", ""),
        register=str(register),
        value=raw["value"],
        timeout_s=parse_duration(raw.get("timeout", "10s")),
        poll_interval_s=parse_duration(raw.get("poll_interval", "500ms")),
        dtype=str(raw.get("dtype", "uint16")),
    )


def _parse_capture(raw: dict[str, Any]) -> CaptureStep:
    if not raw.get("paths"):
        raise ValueError("capture step requires a non-empty 'paths' list")
    if not raw.get("output"):
        raise ValueError("capture step requires an 'output' file path")
    until = raw.get("until") or {}
    duration_s = parse_duration(raw.get("duration", "0s"))
    until_path = until.get("path", "")
    if duration_s <= 0 and not until_path:
        raise ValueError(
            "capture step requires either a positive 'duration' or an 'until' condition"
        )
    return CaptureStep(
        description=raw.get("description", ""),
        paths=list(raw["paths"]),
        duration_s=duration_s,
        until_path=until_path,
        until_value=until.get("value"),
        output=raw["output"],
        sampling_interval_ms=int(raw.get("sampling_interval_ms", 50)),
    )


register_step_parser("write", _parse_write)
register_step_parser("wait", _parse_wait)
register_step_parser("assert", _parse_assert)
register_step_parser("wait_until", _parse_wait_until)
register_step_parser("read", _parse_read)
register_step_parser("snapshot", _parse_snapshot)
register_step_parser("restore", _parse_restore)
register_step_parser("modbus_read", _parse_modbus_read)
register_step_parser("modbus_assert", _parse_modbus_assert)
register_step_parser("modbus_wait_until", _parse_modbus_wait_until)
register_step_parser("capture", _parse_capture)
