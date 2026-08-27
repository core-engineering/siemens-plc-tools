"""The three commands, driven over a replay source so no TIA is needed."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from plc_hw.cli import hw_group
from plc_hw.reader import read_dump
from plc_hw.record import RecordingSource, ReplaySource, load_fixture, save_fixture
from plc_hw.testing import build_fake_source
from plc_hw.walk import walk_project


def _fixture(tmp_path: Path) -> Path:
    recorder = RecordingSource(build_fake_source())
    walk_project(recorder)
    path = tmp_path / "fixture.json"
    save_fixture(recorder.fixture(), path)
    return path


def test_dump_writes_a_tree_from_a_replay_source(tmp_path: Path) -> None:
    out = tmp_path / "dump"
    result = CliRunner().invoke(
        hw_group,
        ["dump", "--source", f"replay:{_fixture(tmp_path)}", "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert (out / "_project.yaml").exists()
    assert (out / "IO_STATION_1" / "00-00-F-DI.yaml").exists()


def test_diff_of_a_dump_against_itself_exits_zero(tmp_path: Path) -> None:
    out = tmp_path / "dump"
    runner = CliRunner()
    runner.invoke(hw_group, ["dump", "--source", f"replay:{_fixture(tmp_path)}", "--out", str(out)])
    result = runner.invoke(hw_group, ["diff", str(out), str(out)])
    assert result.exit_code == 0
    assert "Identical" in result.output


def test_diff_reports_a_change_and_exits_one(tmp_path: Path) -> None:
    runner = CliRunner()
    old, new = tmp_path / "old", tmp_path / "new"
    fixture = _fixture(tmp_path)
    runner.invoke(hw_group, ["dump", "--source", f"replay:{fixture}", "--out", str(old)])
    runner.invoke(hw_group, ["dump", "--source", f"replay:{fixture}", "--out", str(new)])
    path = new / "IO_STATION_1" / "00-00-F-DI.yaml"
    path.write_text(path.read_text().replace("SomeParameter: 150", "SomeParameter: 500"))
    result = runner.invoke(hw_group, ["diff", str(old), str(new)])
    assert result.exit_code == 1
    assert "HW010" in result.output


def test_diff_json_output_is_machine_readable(tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "dump"
    runner.invoke(hw_group, ["dump", "--source", f"replay:{_fixture(tmp_path)}", "--out", str(out)])
    result = runner.invoke(hw_group, ["diff", str(out), str(out), "-f", "json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["identical"] is True


def test_diff_on_an_unreadable_dump_exits_two(tmp_path: Path) -> None:
    result = CliRunner().invoke(hw_group, ["diff", str(tmp_path / "a"), str(tmp_path / "b")])
    assert result.exit_code == 2
    assert "does not exist" in result.output


def test_check_against_a_matching_baseline_exits_zero(tmp_path: Path) -> None:
    runner = CliRunner()
    baseline = tmp_path / "baseline"
    fixture = _fixture(tmp_path)
    runner.invoke(hw_group, ["dump", "--source", f"replay:{fixture}", "--out", str(baseline)])
    result = runner.invoke(hw_group, ["check", "--source", f"replay:{fixture}", "--baseline", str(baseline)])
    assert result.exit_code == 0


def test_check_against_a_drifted_baseline_exits_one(tmp_path: Path) -> None:
    runner = CliRunner()
    baseline = tmp_path / "baseline"
    fixture = _fixture(tmp_path)
    runner.invoke(hw_group, ["dump", "--source", f"replay:{fixture}", "--out", str(baseline)])
    path = baseline / "IO_STATION_1" / "00-00-F-DI.yaml"
    path.write_text(path.read_text().replace("firmware: V2.0", "firmware: V1.0"))
    result = runner.invoke(hw_group, ["check", "--source", f"replay:{fixture}", "--baseline", str(baseline)])
    assert result.exit_code == 1
    assert "HW009" in result.output


def test_check_against_a_baseline_with_a_missing_marker_exits_two_not_one(tmp_path: Path) -> None:
    # An empty directory (no .plc-hw-dump marker) is "could not read", not "no
    # differences": a missing baseline must never be reported as a clean check.
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    fixture = _fixture(tmp_path)
    result = CliRunner().invoke(
        hw_group, ["check", "--source", f"replay:{fixture}", "--baseline", str(baseline)]
    )
    assert result.exit_code == 2
    assert "not a plc-hw dump" in result.output


def test_dump_refuses_a_directory_it_did_not_create(tmp_path: Path) -> None:
    out = tmp_path / "dump"
    out.mkdir()
    (out / "someone-elses-work.txt").write_text("keep me")
    result = CliRunner().invoke(
        hw_group,
        ["dump", "--source", f"replay:{_fixture(tmp_path)}", "--out", str(out)],
    )
    assert result.exit_code == 2
    assert "not a plc-hw dump" in result.output
    assert (out / "someone-elses-work.txt").exists()


def test_raw_recording_outside_the_ignored_directory_is_refused(tmp_path: Path) -> None:
    out = tmp_path / "dump"
    raw_record = tmp_path / "raw.json"
    result = CliRunner().invoke(
        hw_group,
        [
            "dump",
            "--source",
            f"replay:{_fixture(tmp_path)}",
            "--out",
            str(out),
            "--record",
            str(raw_record),
            "--no-anonymize",
        ],
    )
    assert result.exit_code == 2
    assert ".plc-hw-record" in result.output
    # The real guard: the write must genuinely be refused, not merely reworded.
    assert not raw_record.exists()
    assert not out.exists()


def test_an_unknown_source_scheme_is_rejected(tmp_path: Path) -> None:
    result = CliRunner().invoke(hw_group, ["dump", "--source", "nonsense:x", "--out", str(tmp_path / "d")])
    assert result.exit_code == 2
    assert "replay:" in result.output


def test_dump_without_a_source_reports_openness_unavailable(tmp_path: Path) -> None:
    """No ``--source`` on this machine must never crash with a raw traceback.

    ``plc_hw.openness.source`` does not exist yet (Task 10 creates it), so today
    this always hits the ImportError branch. The assertions only check the
    externally-visible contract -- exit code 2 and a message mentioning
    Openness -- so they hold just as well once Task 10 lands and the failure
    instead comes from ``OpennessError`` (e.g. no TIA session to attach to).
    """
    result = CliRunner().invoke(hw_group, ["dump", "--out", str(tmp_path / "dump")])
    assert result.exit_code == 2
    assert "Openness" in result.output


def test_dump_record_writes_a_fixture_that_replays_to_the_same_snapshot(tmp_path: Path) -> None:
    out = tmp_path / "dump"
    record_path = tmp_path / ".plc-hw-record" / "raw.json"
    result = CliRunner().invoke(
        hw_group,
        [
            "dump",
            "--source",
            f"replay:{_fixture(tmp_path)}",
            "--out",
            str(out),
            "--record",
            str(record_path),
            "--no-anonymize",
        ],
    )
    assert result.exit_code == 0, result.output
    fixture = load_fixture(record_path)
    replayed = walk_project(ReplaySource(fixture))
    assert replayed == read_dump(out)


def test_dump_from_a_corrupted_fixture_exits_two_not_one(tmp_path: Path) -> None:
    # A hand-edited or truncated fixture file is bad input, not a programming
    # error: dump's contract is "0 on success, 2 on any failure", with no room
    # for a bare exit 1 and an empty stderr.
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    result = CliRunner().invoke(
        hw_group, ["dump", "--source", f"replay:{bad}", "--out", str(tmp_path / "out")]
    )
    assert result.exit_code == 2
    assert result.output.strip() != ""


def test_check_from_a_corrupted_live_fixture_exits_two_not_one(tmp_path: Path) -> None:
    runner = CliRunner()
    baseline = tmp_path / "baseline"
    runner.invoke(hw_group, ["dump", "--source", f"replay:{_fixture(tmp_path)}", "--out", str(baseline)])
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    result = runner.invoke(hw_group, ["check", "--source", f"replay:{bad}", "--baseline", str(baseline)])
    assert result.exit_code == 2
    assert result.output.strip() != ""


def test_dump_with_an_invalid_plc_yaml_exits_two_not_one(tmp_path: Path) -> None:
    # load_hw_config() reads whatever plc.yaml it finds walking up from the cwd,
    # regardless of --out or --source; a syntax error there is bad input too,
    # not a reason to crash with an unhandled yaml.YAMLError and exit code 1.
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("plc.yaml").write_text("hw:\n  bad: [unterminated\n")
        result = runner.invoke(hw_group, ["dump", "--out", "out"])
    assert result.exit_code == 2
    assert result.output.strip() != ""
