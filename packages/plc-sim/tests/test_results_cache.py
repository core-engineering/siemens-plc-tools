"""Unit tests for the persistent test-results cache."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from plc_core.testing.models import Outcome, ScenarioResult, TestSuiteResult
from plc_core.testing.schema import Scenario

from plc_sim.testing.results_cache import (
    BaselineFingerprint,
    CachedScenarioResult,
    LastFailedError,
    TestResultsCache,
    compute_baseline_fingerprint,
    discover_baseline_sources,
    load_results_cache,
    merge_results,
    save_results_cache,
    select_scenarios_to_rerun,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_files(root: Path, files: dict[str, bytes]) -> list[Path]:
    """Create files under ``root`` and return their absolute paths."""
    paths = []
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        paths.append(p)
    return paths


def _make_suite(*results: tuple[str, Outcome]) -> TestSuiteResult:
    suite = TestSuiteResult()
    for name, outcome in results:
        suite.scenario_results.append(
            ScenarioResult(
                name=name,
                source_file=Path(f"tests/{name}.yaml"),
                outcome=outcome,
                duration_s=1.0,
            )
        )
    return suite


def _scenarios(*names: str) -> list[Scenario]:
    return [Scenario(name=n, source_file=Path(f"tests/{n}.yaml")) for n in names]


# ---------------------------------------------------------------------------
# compute_baseline_fingerprint
# ---------------------------------------------------------------------------


def test_compute_fingerprint_deterministic(tmp_path: Path) -> None:
    files = _write_files(tmp_path, {"a.s7dcl": b"AAAA", "b.s7dcl": b"BBBB"})
    fp1 = compute_baseline_fingerprint(files, root=tmp_path)
    fp2 = compute_baseline_fingerprint(list(reversed(files)), root=tmp_path)

    assert fp1.hash == fp2.hash
    assert set(fp1.source_files) == {"a.s7dcl", "b.s7dcl"}


def test_compute_fingerprint_changes_on_content(tmp_path: Path) -> None:
    files = _write_files(tmp_path, {"a.s7dcl": b"AAAA"})
    fp1 = compute_baseline_fingerprint(files, root=tmp_path)
    files[0].write_bytes(b"AAAB")
    fp2 = compute_baseline_fingerprint(files, root=tmp_path)

    assert fp1.hash != fp2.hash


def test_compute_fingerprint_changes_on_added_file(tmp_path: Path) -> None:
    files = _write_files(tmp_path, {"a.s7dcl": b"AAAA"})
    fp1 = compute_baseline_fingerprint(files, root=tmp_path)
    extra = _write_files(tmp_path, {"b.s7dcl": b"BBBB"})
    fp2 = compute_baseline_fingerprint(files + extra, root=tmp_path)

    assert fp1.hash != fp2.hash


def test_compute_fingerprint_empty_inputs() -> None:
    fp = compute_baseline_fingerprint([])
    assert fp.hash  # well-defined empty hash
    assert fp.source_files == {}


# ---------------------------------------------------------------------------
# discover_baseline_sources
# ---------------------------------------------------------------------------


def test_discover_baseline_sources_matches_globs(tmp_path: Path) -> None:
    _write_files(
        tmp_path,
        {
            "program-blocks/A.s7dcl": b"a",
            "data-types/T.s7dcl": b"t",
            "tags/Tags.xml": b"<x/>",
            "tests/integration-tests/EFAT_001.yaml": b"# not included",
        },
    )
    found = discover_baseline_sources(
        [
            "program-blocks/**/*.s7dcl",
            "data-types/**/*.s7dcl",
            "tags/**/*.xml",
        ],
        project_root=tmp_path,
    )

    rel = sorted(p.relative_to(tmp_path).as_posix() for p in found)
    assert rel == [
        "data-types/T.s7dcl",
        "program-blocks/A.s7dcl",
        "tags/Tags.xml",
    ]


# ---------------------------------------------------------------------------
# load / save cache
# ---------------------------------------------------------------------------


def test_load_cache_missing_returns_none(tmp_path: Path) -> None:
    assert load_results_cache(tmp_path / "nope.json") is None


def test_load_cache_corrupted_returns_none_warns(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("{not valid json", encoding="utf-8")

    with caplog.at_level("WARNING"):
        result = load_results_cache(cache_path)

    assert result is None
    assert any("unreadable" in rec.message for rec in caplog.records)


def test_load_cache_unexpected_schema_returns_none(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({"results": {}}), encoding="utf-8")  # missing baseline

    with caplog.at_level("WARNING"):
        result = load_results_cache(cache_path)

    assert result is None


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    cache_path = tmp_path / ".sim" / "test_results.json"
    fp = BaselineFingerprint(hash="deadbeef", source_files={"a.s7dcl": "x"}, computed_at="t0")
    cache = TestResultsCache(
        baseline=fp,
        results={
            "EFAT-001": CachedScenarioResult(
                name="EFAT-001",
                source_file="tests/EFAT_001.yaml",
                outcome="passed",
                duration_s=1.5,
                error_message=None,
                executed_at="t1",
            )
        },
    )

    save_results_cache(cache, cache_path)
    loaded = load_results_cache(cache_path)

    assert loaded is not None
    assert loaded.baseline.hash == "deadbeef"
    assert loaded.results["EFAT-001"].outcome == "passed"


# ---------------------------------------------------------------------------
# merge_results
# ---------------------------------------------------------------------------


def test_merge_same_fingerprint_preserves_old_results() -> None:
    fp = BaselineFingerprint(hash="abc", computed_at="t0")
    old = TestResultsCache(
        baseline=fp,
        results={
            "T1": CachedScenarioResult("T1", None, "passed", 1.0, None, "t0"),
            "T2": CachedScenarioResult("T2", None, "failed", 1.0, "boom", "t0"),
        },
    )
    suite = _make_suite(("T2", Outcome.PASSED))  # only T2 was re-run, now passes

    merged = merge_results(old, suite, fp)

    # T1 unchanged, T2 updated
    assert merged.results["T1"].outcome == "passed"
    assert merged.results["T1"].executed_at == "t0"
    assert merged.results["T2"].outcome == "passed"
    assert merged.results["T2"].error_message is None


def test_merge_different_fingerprint_replaces_all() -> None:
    old_fp = BaselineFingerprint(hash="abc", computed_at="t0")
    new_fp = BaselineFingerprint(hash="xyz", computed_at="t1")
    old = TestResultsCache(
        baseline=old_fp,
        results={"T1": CachedScenarioResult("T1", None, "passed", 1.0, None, "t0")},
    )
    suite = _make_suite(("T2", Outcome.PASSED))

    merged = merge_results(old, suite, new_fp)

    assert merged.baseline.hash == "xyz"
    assert "T1" not in merged.results
    assert "T2" in merged.results


def test_merge_with_no_existing_cache() -> None:
    fp = BaselineFingerprint(hash="abc", computed_at="t0")
    suite = _make_suite(("T1", Outcome.PASSED), ("T2", Outcome.FAILED))

    merged = merge_results(None, suite, fp)

    assert merged.baseline.hash == "abc"
    assert set(merged.results) == {"T1", "T2"}


# ---------------------------------------------------------------------------
# select_scenarios_to_rerun
# ---------------------------------------------------------------------------


def test_select_scenarios_to_rerun_filters_passed_warning() -> None:
    fp = BaselineFingerprint(hash="abc", computed_at="t0")
    cache = TestResultsCache(
        baseline=fp,
        results={
            "PASS": CachedScenarioResult("PASS", None, "passed", 1.0, None, "t0"),
            "WARN": CachedScenarioResult("WARN", None, "warning", 1.0, None, "t0"),
            "FAIL": CachedScenarioResult("FAIL", None, "failed", 1.0, "boom", "t0"),
            "ERR": CachedScenarioResult("ERR", None, "error", 1.0, "boom", "t0"),
            "SKIP": CachedScenarioResult("SKIP", None, "skipped", 1.0, None, "t0"),
        },
    )
    scenarios = _scenarios("PASS", "WARN", "FAIL", "ERR", "SKIP", "NEW")

    selected = select_scenarios_to_rerun(cache, scenarios, fp)

    names = sorted(s.name for s in selected)
    assert names == ["ERR", "FAIL", "NEW", "SKIP"]


def test_select_scenarios_to_rerun_raises_on_fingerprint_mismatch() -> None:
    cache = TestResultsCache(baseline=BaselineFingerprint(hash="old", computed_at="t0"), results={})
    fp = BaselineFingerprint(hash="new", computed_at="t1")

    with pytest.raises(LastFailedError, match="fingerprint mismatch"):
        select_scenarios_to_rerun(cache, _scenarios("T1"), fp)


def test_select_scenarios_to_rerun_raises_on_no_cache() -> None:
    fp = BaselineFingerprint(hash="abc", computed_at="t0")
    with pytest.raises(LastFailedError, match="No previous test results"):
        select_scenarios_to_rerun(None, _scenarios("T1"), fp)
