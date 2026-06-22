"""Bit-exact replay of the 18 001 a·sin(b) test vectors through the ladder interpreter.

Fixture paths are anchored to this file's location so the suite passes from
both the repo root and the package directory.  The fixture directory is
auto-registered as a sub-block search path by ``create_harness``, so
``ABS`` and ``SIGN`` resolve automatically.

The ``DataSafetyKinematics`` constant DB must be registered explicitly:
the runtime DB loader does not parse ``MEMBER[idx] := value;`` array
initialisers, so the ``LutSinQ14`` LUT would otherwise be empty and the
replay would silently produce wrong values.  We reuse the ``_load_array_db``
helper pattern from ``test_compile.py``.
"""

import csv
import re
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace

from plc_code.executor import FBTestHarness, create_harness

FIX = Path(__file__).parent.parent / "fixtures" / "ladder"

_ARRAY_ASSIGN_RE = re.compile(r"(\w+)\[(\d+)\]\s*:=\s*(-?\d+)")


def _load_array_db(path: Path) -> SimpleNamespace:
    """Build a DB namespace from ``MEMBER[idx] := value;`` array assignments.

    ``load_data_block`` only extracts scalar ``NAME : Type := value;``
    declarations; the array initialiser lines used by ``DataSafetyKinematics``
    are not parsed.  This loader fills that gap for the test.
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


def _make_harness() -> FBTestHarness:
    """Create and return a fully-initialised harness with the LUT registered."""
    h = create_harness(FIX / "SinCalculation.s7dcl")
    db = _load_array_db(FIX / "DataSafetyKinematics.s7dcl")
    # Sanity-check: ensure the LUT loaded correctly (indices 0..901 → 902 cells).
    assert len(db.LutSinQ14) == 902, (
        f"DataSafetyKinematics.LutSinQ14 has {len(db.LutSinQ14)} entries, expected 902; "
        "the DB loader may have failed silently."
    )
    h.runtime.register_db("DataSafetyKinematics", db)
    return h


def _vectors() -> Generator[tuple[int, int, int, bool], None, None]:
    with open(FIX / "test_vectors.csv", newline="") as f:
        for row in csv.DictReader(f):
            yield (
                int(row["angleCenti"]),
                int(row["lengthMm"]),
                int(row["expectedMm"]),
                bool(int(row["fault"])),
            )


def test_spot_checks() -> None:
    """Verify hand-picked angle→result pairs and the fault boundary."""
    h = _make_harness()
    for angle, expected in [(3000, 6553), (-4500, -9267), (4567, 9375), (9000, 13106)]:
        h.set_inputs(angle=angle, length=13106)
        h.execute()
        assert h.get_output("result") == expected, f"angle={angle}"
        assert h.get_output("fault") is False
    h.set_inputs(angle=9050, length=13106)
    h.execute()
    assert h.get_output("fault") is True


def test_full_18001_vectors_bit_exact() -> None:
    """Replay all 18 001 CSV vectors and confirm bit-exact agreement."""
    h = _make_harness()
    mismatches: list[tuple[int, int, int, object, bool]] = []
    n = 0
    for angle, length, expected, fault in _vectors():
        h.set_inputs(angle=angle, length=length)
        h.execute()
        n += 1
        got_result = h.get_output("result")
        got_fault = bool(h.get_output("fault"))
        if got_result != expected or got_fault != fault:
            mismatches.append((angle, got_result, expected, got_fault, fault))
            if len(mismatches) > 10:
                break
    assert n == 18001, f"expected 18001 vectors, replayed {n}"
    assert not mismatches, (
        "first mismatches (angle, got_result, expected_result, got_fault, expected_fault):\n"
        + "\n".join(str(m) for m in mismatches[:10])
    )
