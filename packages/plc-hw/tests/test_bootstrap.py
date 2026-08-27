"""Finding the Openness assemblies, and saying something useful when we cannot."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from plc_hw.openness.bootstrap import (
    AssemblySet,
    OpennessError,
    candidate_api_dirs,
    discover_assemblies,
    load_clr,
    resolve,
)


def _make(directory: Path, *names: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_bytes(b"")
    return directory


def test_v21_split_layout_is_recognised(tmp_path: Path) -> None:
    api = _make(
        tmp_path / "net48",
        "Siemens.Engineering.Base.dll",
        "Siemens.Engineering.Step7.dll",
        "Siemens.Engineering.Safety.dll",
    )
    found = discover_assemblies(api)
    assert found.layout == "split"
    assert [p.name for p in found.assemblies] == [
        "Siemens.Engineering.Base.dll",
        "Siemens.Engineering.Step7.dll",
        "Siemens.Engineering.Safety.dll",
    ]


def test_split_layout_tolerates_a_missing_safety_assembly(tmp_path: Path) -> None:
    api = _make(tmp_path / "net48", "Siemens.Engineering.Base.dll", "Siemens.Engineering.Step7.dll")
    assert discover_assemblies(api).layout == "split"


def test_legacy_single_assembly_layout_is_recognised(tmp_path: Path) -> None:
    api = _make(tmp_path / "v19", "Siemens.Engineering.dll")
    found = discover_assemblies(api)
    assert found.layout == "single"
    assert [p.name for p in found.assemblies] == ["Siemens.Engineering.dll"]


def test_a_directory_with_neither_layout_says_what_it_looked_for(tmp_path: Path) -> None:
    api = _make(tmp_path / "empty", "readme.txt")
    with pytest.raises(OpennessError) as excinfo:
        discover_assemblies(api)
    message = str(excinfo.value)
    assert "Siemens.Engineering.Base.dll" in message
    assert "Siemens.Engineering.dll" in message
    assert str(api) in message


def test_a_missing_directory_is_reported(tmp_path: Path) -> None:
    with pytest.raises(OpennessError, match="does not exist"):
        discover_assemblies(tmp_path / "nope")


def test_a_path_that_is_a_file_not_a_directory_says_so(tmp_path: Path) -> None:
    path = tmp_path / "not-a-directory"
    path.write_bytes(b"")
    with pytest.raises(OpennessError, match="not a directory"):
        discover_assemblies(path)


def test_the_environment_override_comes_first(tmp_path: Path) -> None:
    override = tmp_path / "custom"
    candidates = candidate_api_dirs({"PLC_HW_OPENNESS_PATH": str(override)}, tmp_path / "pf")
    assert candidates[0] == override


def test_installed_portal_versions_are_offered_newest_first(tmp_path: Path) -> None:
    pf = tmp_path / "pf"
    for version in ("V19", "V21", "V20"):
        _make(pf / "Siemens" / "Automation" / f"Portal {version}" / "PublicAPI" / version / "net48")
    candidates = candidate_api_dirs({}, pf)
    assert [c.parent.name for c in candidates] == ["V21", "V20", "V19"]


def test_no_installation_yields_no_candidates(tmp_path: Path) -> None:
    assert candidate_api_dirs({}, tmp_path / "pf") == []


# --- Defect found while transcribing: a directory holding only
# Siemens.Engineering.Base.dll (no Step7) was being reported as a valid
# "split" layout with a single assembly. Only the Safety assembly is meant to
# be optional -- see test_split_layout_tolerates_a_missing_safety_assembly
# above. Fixed in discover_assemblies; this pins the corrected behaviour.


def test_split_layout_requires_step7_not_just_base(tmp_path: Path) -> None:
    api = _make(tmp_path / "net48", "Siemens.Engineering.Base.dll")
    with pytest.raises(OpennessError):
        discover_assemblies(api)


def test_a_partial_split_install_names_what_was_found_and_missing(tmp_path: Path) -> None:
    api = _make(tmp_path / "net48", "Siemens.Engineering.Base.dll")
    with pytest.raises(OpennessError) as excinfo:
        discover_assemblies(api)
    message = str(excinfo.value)
    assert "Siemens.Engineering.Base.dll" in message
    assert "Siemens.Engineering.Step7.dll" in message


# --- Additional tests for resolve() (Correction 2: part of the public surface)


def test_resolve_skips_an_empty_candidate_and_keeps_looking(tmp_path: Path) -> None:
    pf = tmp_path / "pf"
    _make(pf / "Siemens" / "Automation" / "Portal V21" / "PublicAPI" / "V21" / "net48")
    _make(
        pf / "Siemens" / "Automation" / "Portal V20" / "PublicAPI" / "V20" / "net48",
        "Siemens.Engineering.dll",
    )
    found = resolve({}, pf)
    assert found.layout == "single"
    assert found.directory == pf / "Siemens" / "Automation" / "Portal V20" / "PublicAPI" / "V20" / "net48"


def test_resolve_error_names_every_candidate_tried(tmp_path: Path) -> None:
    pf = tmp_path / "pf"
    v21 = _make(pf / "Siemens" / "Automation" / "Portal V21" / "PublicAPI" / "V21" / "net48")
    v20 = _make(pf / "Siemens" / "Automation" / "Portal V20" / "PublicAPI" / "V20" / "net48")
    with pytest.raises(OpennessError) as excinfo:
        resolve({}, pf)
    message = str(excinfo.value)
    assert str(v21) in message
    assert str(v20) in message


def test_resolve_with_no_installation_names_the_environment_override(tmp_path: Path) -> None:
    pf = tmp_path / "pf"
    with pytest.raises(OpennessError, match="PLC_HW_OPENNESS_PATH"):
        resolve({}, pf)


# --- load_clr


def test_load_clr_on_non_windows_names_the_replay_alternative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assemblies = AssemblySet(directory=Path("/nonexistent"), assemblies=(), layout="single")
    with pytest.raises(OpennessError) as excinfo:
        load_clr(assemblies)
    message = str(excinfo.value)
    assert "replay" in message
    # The platform check must happen before any attempt to import clr: on
    # Linux pythonnet is not installed, so if `import clr` ran first we would
    # see the "pythonnet is not installed" message instead of this one.
    assert "pythonnet" not in message


def test_load_clr_called_twice_does_not_duplicate_sys_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    recorded: list[str] = []
    fake_clr = types.ModuleType("clr")
    fake_clr.AddReference = recorded.append  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "clr", fake_clr)

    directory = _make(tmp_path / "net48", "Siemens.Engineering.dll")
    assemblies = AssemblySet(
        directory=directory, assemblies=(directory / "Siemens.Engineering.dll",), layout="single"
    )

    original_sys_path = list(sys.path)
    try:
        load_clr(assemblies)
        load_clr(assemblies)
        assert sys.path.count(str(directory)) == 1
        assert recorded == [str(directory / "Siemens.Engineering.dll")] * 2
    finally:
        sys.path[:] = original_sys_path
