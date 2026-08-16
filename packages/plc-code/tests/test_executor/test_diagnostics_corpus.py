"""The diagnostics must be quiet on code that actually works.

A checker that cries wolf gets turned off, so this runs the real detector over
every ``.s7dcl`` fixture in the package and requires silence — except for a
short, named list of blocks with a *known* defect.

The exception list is a ratchet, not a carpet: each entry names the construct
the transpiler does not support. Fixing one makes this test fail until its entry
is removed, which is the point.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plc_code.executor.diagnostics import check_block
from plc_code.parser import parse_scl_file

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

# block file -> the unsupported construct it exercises.
#
# PumpControl declares PROC_READY in a VAR CONSTANT section and then reads it
# once *without* the '#' prefix (`IF #processState = PROC_READY THEN`), while
# the same file's other two uses are `#PROC_READY`. VAR CONSTANT members are
# generated as instance attributes, so the prefixed form resolves to
# `self.PROC_READY` and the bare one is left as a module global that nothing
# defines — NameError the first time that branch is taken. Either the fixture
# has a typo or bare constant references need transpiler support; until that is
# decided, the detector is right to flag it.
KNOWN_DEFECTS = {
    "PumpControl.s7dcl": "bare VAR CONSTANT reference (PROC_READY without '#')",
}


def _fixture_files() -> list[Path]:
    return sorted(FIXTURES.rglob("*.s7dcl"))


def test_the_corpus_is_not_empty() -> None:
    """Guard against the glob silently matching nothing."""
    assert len(_fixture_files()) >= 20


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.name)
def test_fixture_generates_resolvable_python(path: Path) -> None:
    """Every fixture transpiles to Python that parses and resolves."""
    block = parse_scl_file(path)
    if block is None or not block.name:
        pytest.skip(f"{path.name} holds no parsable block")

    diagnostics = check_block(block, source_file=path)

    if path.name in KNOWN_DEFECTS:
        assert diagnostics, (
            f"{path.name} is listed in KNOWN_DEFECTS "
            f"({KNOWN_DEFECTS[path.name]}) but now reports nothing — "
            "remove it from the list."
        )
        return

    assert diagnostics == [], f"{path.name} reports diagnostics on code believed to work:\n" + "\n".join(
        f"  {d.code} line {d.line}: {d.message}" for d in diagnostics
    )
