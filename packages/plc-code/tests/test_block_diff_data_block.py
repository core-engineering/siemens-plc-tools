"""Typed and inline DATA_BLOCKs are no longer opaque to `plc code diff`."""

from __future__ import annotations

from pathlib import Path

from s7dcl_helpers import write_s7dcl

from plc_code.analyzer.block_diff import diff_blocks
from plc_code.parser import parse_scl_file

HEADER = '{\n    S7_Optimized := "TRUE";\n    S7_StandardRetain := "FALSE";\n    S7_Version := "0.1"\n}\n'
TYPED_1 = HEADER + "DATA_BLOCK P : typeP\n    axes[1].absKind := 1;\n    delay := T#150ms;\nEND_DATA_BLOCK\n"
TYPED_2 = HEADER + "DATA_BLOCK P : typeP\n    axes[1].absKind := 2;\n    gain := 0.5;\nEND_DATA_BLOCK\n"
INLINE_1 = HEADER + "DATA_BLOCK P\n    VAR\n        a : Int;\n    END_VAR\nEND_DATA_BLOCK\n"
INLINE_2 = (
    HEADER + "DATA_BLOCK P\n    VAR\n        a : Int;\n        b : Real;\n    END_VAR\nEND_DATA_BLOCK\n"
)


def test_start_value_changes_are_listed(tmp_path: Path) -> None:
    old = parse_scl_file(write_s7dcl(tmp_path / "old", "P.s7dcl", TYPED_1))
    new = parse_scl_file(write_s7dcl(tmp_path / "new", "P.s7dcl", TYPED_2))
    diff = diff_blocks(old, new)
    assert diff.is_change
    assert "start value axes[1].absKind: 1 -> 2" in diff.notes
    assert "start value delay removed" in diff.notes
    assert "start value gain added" in diff.notes
    assert not any("not semantically compared" in n for n in diff.notes)


def test_identical_typed_dbs_are_identical(tmp_path: Path) -> None:
    old = parse_scl_file(write_s7dcl(tmp_path / "old", "P.s7dcl", TYPED_1))
    new = parse_scl_file(write_s7dcl(tmp_path / "new", "P.s7dcl", TYPED_1))
    assert not diff_blocks(old, new).is_change


def test_inline_member_added_shows_in_interface_diff(tmp_path: Path) -> None:
    old = parse_scl_file(write_s7dcl(tmp_path / "old", "P.s7dcl", INLINE_1))
    new = parse_scl_file(write_s7dcl(tmp_path / "new", "P.s7dcl", INLINE_2))
    diff = diff_blocks(old, new)
    assert diff.is_change
    assert any(change.name == "b" for change in diff.interface)
