"""Integration tests for compiling F-LAD blocks through the harness.

Fixture paths are anchored to this file's location so the suite passes from
both the repo root and the package directory. The fixture directory is the
sub-block / constant-DB search path: ``from_scl_file`` registers the directory
containing the entry block automatically, so ``ABS``, ``SIGN`` and the constant
``DataSafetyKinematics`` DB all resolve without an explicit ``search_paths``
argument.
"""

import re
from pathlib import Path
from types import SimpleNamespace

from plc_code.executor import create_harness

FIX = Path(__file__).parent.parent / "fixtures" / "ladder"

_ARRAY_ASSIGN_RE = re.compile(r"(\w+)\[(\d+)\]\s*:=\s*(-?\d+)")


def _load_array_db(path: Path) -> SimpleNamespace:
    """Build a DB namespace from ``MEMBER[idx] := value;`` array assignments.

    ``load_data_block`` only extracts scalar ``NAME : Type := value;``
    declarations; the array initialiser lines used by ``DataSafetyKinematics``
    are not parsed. This local loader fills that gap for the test until the
    runtime DB loader handles arrays (Task 7).
    """
    text = path.read_text(encoding="utf-8-sig")
    arrays: dict[str, dict[int, int]] = {}
    for member, idx, value in _ARRAY_ASSIGN_RE.findall(text):
        arrays.setdefault(member, {})[int(idx)] = int(value)
    members = {
        name: [cells.get(i, 0) for i in range(max(cells) + 1)]
        for name, cells in arrays.items()
    }
    return SimpleNamespace(**members)


def test_abs_via_harness() -> None:
    h = create_harness(FIX / "ABS.s7dcl")
    h.set_inputs(x=-5)
    h.execute()
    assert h.get_output("y") == 5


def test_sin_calls_subblocks_and_db() -> None:
    h = create_harness(FIX / "SinCalculation.s7dcl")
    # The fixture directory is auto-registered as a block search path, so the
    # sub-blocks ABS/SIGN resolve. The constant DataSafetyKinematics DB does NOT
    # auto-load through ``runtime.get_db`` (which short-circuits on
    # ``__contains__`` before the lazy ``_GlobalDBs.__missing__`` autoload fires,
    # and whose loader ignores array initialisers anyway), so it is registered
    # explicitly here. See task-6-report.md / Task 7.
    h.runtime.register_db(
        "DataSafetyKinematics", _load_array_db(FIX / "DataSafetyKinematics.s7dcl")
    )
    h.set_inputs(angle=3000, length=13106)
    h.execute()
    assert h.get_output("result") == 6553
    assert h.get_output("fault") is False
