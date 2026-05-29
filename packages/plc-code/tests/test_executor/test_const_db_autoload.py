"""Lazy auto-loading of constant DATA_BLOCKs referenced from code.

A ``"DbName".MEMBER`` reference should resolve at execution time by loading
``DbName.s7dcl`` from the runtime's block search paths (mirroring how
``call_named_block`` auto-discovers FUNCTION/FB sub-blocks), so that shared
constant DBs need not be registered by hand in every test.
"""

from pathlib import Path

from plc_code.executor.harness import FBTestHarness
from plc_code.executor.runtime import PLCRuntime, load_data_block

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def test_load_data_block_parses_typed_literals() -> None:
    db = load_data_block(FIXTURES_DIR / "dbDemoConst.s7dcl")
    assert db.LIMIT_HI == 100
    assert db.EPS == 1.0e-9
    assert db.CODE_OK == 0x7000
    assert db.FLAG_ON is True


def test_constant_db_autoloads_from_search_path() -> None:
    runtime = PLCRuntime(block_search_paths=[FIXTURES_DIR])
    harness = FBTestHarness.from_scl_file(FIXTURES_DIR / "UsesDbConst.s7dcl", runtime)
    harness.execute()
    assert harness.get_output("limit") == 100
    assert harness.get_output("UsesDbConst") == 0x7000


def test_db_reference_after_comparison_operator_resolves() -> None:
    """``IF #v < "db".MEMBER`` must not be mistaken for an enum-string comparison.

    The string-constant collector treats ``< "NAME"`` as a CASE/enum comparison
    and maps it to an integer; a quoted name followed by ``.member`` is a DB
    reference and must be left alone.
    """
    runtime = PLCRuntime(block_search_paths=[FIXTURES_DIR])
    h1 = FBTestHarness.from_scl_file(FIXTURES_DIR / "UsesDbCompare.s7dcl", runtime)
    h1.set_inputs(v=50)
    h1.execute()
    assert h1.get_output("UsesDbCompare") is True  # 50 < 100

    runtime2 = PLCRuntime(block_search_paths=[FIXTURES_DIR])
    h2 = FBTestHarness.from_scl_file(FIXTURES_DIR / "UsesDbCompare.s7dcl", runtime2)
    h2.set_inputs(v=150)
    h2.execute()
    assert h2.get_output("UsesDbCompare") is False  # 150 < 100 is false


def test_unregistered_db_still_raises_keyerror() -> None:
    """get_db on a name that exists nowhere must still raise (no silent autoload)."""
    runtime = PLCRuntime()
    try:
        runtime.get_db("doesNotExist")
    except KeyError:
        return
    raise AssertionError("expected KeyError for unknown DB")
