"""Persisted integration-test results cache keyed by PLC baseline fingerprint.

The cache enables a `pytest --last-failed`-style workflow: after a full run,
results are stored in `.sim/test_results.json` along with a SHA-256 fingerprint
of the PLC source files. A subsequent `plc sim test --last-failed` re-runs only
scenarios that did not pass, provided the baseline fingerprint still matches.

The fingerprint is computed over the project's `.s7dcl` (Program blocks +
PLC data types) and PLC tag `.xml` files. YAML test files are intentionally
excluded — modifying a test does not invalidate other passed scenarios.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from plc_core.testing.models import Outcome, TestSuiteResult
from plc_core.testing.schema import Scenario

logger = logging.getLogger(__name__)


# Outcomes considered "to be re-run" under --last-failed.
# PASSED and WARNING are treated as success (WARNING = test functionally passed
# with a non-blocking advisory).
RERUN_OUTCOMES = frozenset({Outcome.FAILED, Outcome.ERROR, Outcome.SKIPPED})


class LastFailedError(RuntimeError):
    """Raised when --last-failed cannot be honored (no cache or mismatch)."""


@dataclass(frozen=True)
class BaselineFingerprint:
    """SHA-256 fingerprint of the PLC source files at run time."""

    hash: str
    source_files: dict[str, str] = field(default_factory=dict)
    computed_at: str = ""

    def short(self) -> str:
        """Return a short prefix suitable for display."""
        return self.hash[:12]


@dataclass
class CachedScenarioResult:
    """Minimal scenario result subset persisted to the cache."""

    name: str
    source_file: str | None
    outcome: str  # Outcome.value (string form for JSON serialization)
    duration_s: float
    error_message: str | None
    executed_at: str

    @property
    def is_pass(self) -> bool:
        """Return True if this result is treated as a pass (not re-run with --lf)."""
        return self.outcome not in {o.value for o in RERUN_OUTCOMES}


@dataclass
class TestResultsCache:
    """Persistent cache of test results for a given PLC baseline."""

    __test__ = False  # Prevent pytest from collecting this dataclass as a test class.

    baseline: BaselineFingerprint
    results: dict[str, CachedScenarioResult] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Fingerprint computation
# ---------------------------------------------------------------------------


def compute_baseline_fingerprint(
    source_files: list[Path], *, root: Path | None = None
) -> BaselineFingerprint:
    """Compute a stable SHA-256 fingerprint over the given source files.

    Each file is hashed individually (binary mode, no line-ending normalization),
    then the sorted list of ``(relative_path, file_hash)`` pairs is hashed.

    Parameters
    ----------
    source_files : list[Path]
        Files contributing to the baseline (typically `.s7dcl` and `.xml`).
    root : Path | None
        Directory used to compute relative paths in the fingerprint metadata.
        Defaults to the common ancestor of ``source_files``.

    Returns
    -------
    BaselineFingerprint
        Fingerprint with overall hash + per-file hashes for diagnostics.
    """
    if not source_files:
        empty_hash = hashlib.sha256(b"").hexdigest()
        return BaselineFingerprint(
            hash=empty_hash,
            source_files={},
            computed_at=_utc_now_iso(),
        )

    if root is None:
        try:
            root = Path(_common_ancestor([p.resolve() for p in source_files]))
        except ValueError:
            root = source_files[0].resolve().parent

    per_file: dict[str, str] = {}
    for p in sorted(source_files):
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        try:
            rel = p.resolve().relative_to(root).as_posix()
        except ValueError:
            rel = p.resolve().as_posix()
        per_file[rel] = digest

    combined = hashlib.sha256()
    for rel in sorted(per_file):
        combined.update(rel.encode("utf-8"))
        combined.update(b"\0")
        combined.update(per_file[rel].encode("ascii"))
        combined.update(b"\n")

    return BaselineFingerprint(
        hash=combined.hexdigest(),
        source_files=per_file,
        computed_at=_utc_now_iso(),
    )


def discover_baseline_sources(globs: list[str], *, project_root: Path) -> list[Path]:
    """Discover PLC source files matching the configured globs.

    Parameters
    ----------
    globs : list[str]
        Glob patterns relative to ``project_root`` (e.g.
        ``"program-blocks/**/*.s7dcl"``).
    project_root : Path
        Project root directory (typically the directory containing ``plc.yaml``).

    Returns
    -------
    list[Path]
        Sorted list of unique matching files. Empty if no files match.
    """
    found: set[Path] = set()
    for pattern in globs:
        for path in project_root.glob(pattern):
            if path.is_file():
                found.add(path.resolve())
    return sorted(found)


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------


def load_results_cache(cache_path: Path) -> TestResultsCache | None:
    """Load the results cache from disk.

    Returns
    -------
    TestResultsCache | None
        ``None`` if the file is absent or corrupted (a warning is logged in
        the corruption case).
    """
    if not cache_path.exists():
        return None

    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Results cache at %s is unreadable: %s — ignoring.", cache_path, exc)
        return None

    try:
        baseline_data = raw["baseline"]
        baseline = BaselineFingerprint(
            hash=baseline_data["hash"],
            source_files=dict(baseline_data.get("source_files", {})),
            computed_at=baseline_data.get("computed_at", ""),
        )
        results = {name: CachedScenarioResult(**entry) for name, entry in raw.get("results", {}).items()}
    except (KeyError, TypeError) as exc:
        logger.warning("Results cache at %s has unexpected schema: %s — ignoring.", cache_path, exc)
        return None

    return TestResultsCache(baseline=baseline, results=results)


def save_results_cache(cache: TestResultsCache, cache_path: Path) -> None:
    """Persist the results cache to disk as JSON."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "baseline": asdict(cache.baseline),
        "results": {name: asdict(r) for name, r in cache.results.items()},
    }
    cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Merge + selection logic
# ---------------------------------------------------------------------------


def merge_results(
    cache: TestResultsCache | None,
    suite: TestSuiteResult,
    baseline: BaselineFingerprint,
) -> TestResultsCache:
    """Merge the latest run's results into the persisted cache.

    Behavior:
    - If the existing cache has a *different* baseline fingerprint, all old
      entries are discarded (the cache rebases on the new baseline).
    - If the fingerprint matches, results from this run overwrite their
      counterparts in the cache, while scenarios not run this time keep
      their previous result.
    """
    same_baseline = cache is not None and cache.baseline.hash == baseline.hash
    merged: dict[str, CachedScenarioResult] = (
        dict(cache.results) if same_baseline and cache is not None else {}
    )

    timestamp = _utc_now_iso()
    for sr in suite.scenario_results:
        merged[sr.name] = CachedScenarioResult(
            name=sr.name,
            source_file=str(sr.source_file) if sr.source_file else None,
            outcome=sr.outcome.value,
            duration_s=sr.duration_s,
            error_message=sr.error_message,
            executed_at=timestamp,
        )

    return TestResultsCache(baseline=baseline, results=merged)


def select_scenarios_to_rerun(
    cache: TestResultsCache | None,
    scenarios: list[Scenario],
    baseline: BaselineFingerprint,
) -> list[Scenario]:
    """Filter scenarios to those that should be re-run under --last-failed.

    Selection rules:
    - Scenarios whose previous outcome is in :data:`RERUN_OUTCOMES`
      (FAILED, ERROR, SKIPPED).
    - Scenarios that are not present in the cache (e.g. newly added tests).

    Raises
    ------
    LastFailedError
        If the cache is absent or its baseline does not match the current one.
    """
    if cache is None:
        raise LastFailedError(
            "No previous test results cache found. Run a full suite first " "(without --last-failed)."
        )
    if cache.baseline.hash != baseline.hash:
        raise LastFailedError(
            f"Baseline fingerprint mismatch: cached {cache.baseline.short()}, "
            f"current {baseline.short()}. The PLC sources have changed since "
            f"the last run. Use --reset-baseline to discard the cache and "
            f"re-run the full suite."
        )

    rerun_values = {o.value for o in RERUN_OUTCOMES}
    selected: list[Scenario] = []
    for s in scenarios:
        prev = cache.results.get(s.name)
        if prev is None or prev.outcome in rerun_values:
            selected.append(s)
    return selected


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _common_ancestor(paths: list[Path]) -> Path:
    """Return the longest common parent of a list of absolute paths."""
    if not paths:
        raise ValueError("paths must be non-empty")
    parts = [p.parts for p in paths]
    common: list[str] = []
    for tup in zip(*parts, strict=False):
        if len(set(tup)) == 1:
            common.append(tup[0])
        else:
            break
    if not common:
        raise ValueError("no common ancestor")
    return Path(*common)
