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
# Empty, and meant to stay that way: a fixture in this directory is a block the
# toolchain is expected to handle. Deliberately broken SCL belongs in the test
# that needs it (see test_cli_transpile.py, which writes its own to tmp_path),
# not in the corpus — putting it here would weaken the guarantee this file
# exists to provide.
#
# The mechanism is kept because a genuine, not-yet-decided gap may need parking
# here for a while. The first entry it ever held was PumpControl.s7dcl, which
# read its VAR CONSTANT member PROC_READY once without the '#' prefix; that was
# a typo in the fixture, fixed rather than tolerated.
KNOWN_DEFECTS: dict[str, str] = {}


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
