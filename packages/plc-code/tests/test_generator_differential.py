"""The old text path and the AST path must emit the same Python, line for line.

The bar is byte-identical output, defects included: a divergence is reproduced,
never fixed here, so that an intentional difference can never be mistaken for a
regression. See the spec, section 4.

Until the generator exists this compares the old path against itself, which is
the point: the comparison machinery is proven before it has anything to catch.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from plc_code.parser import parse_scl_file
from plc_code.parser.models import Block

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.mark.parametrize("path", sorted(FIXTURES.rglob("*.s7dcl")), ids=lambda p: str(p))
def test_the_two_paths_agree(
    path: Path, differential_old: Callable[[Block], list[tuple[str, list[str]]]]
) -> None:
    block = parse_scl_file(path)
    if block is None or not block.name:
        pytest.skip(f"{path.name} holds no parsable block")

    left = differential_old(block)
    right = differential_old(block)

    assert [label for label, _ in left] == [label for label, _ in right]
    for (label, old_lines), (_, new_lines) in zip(left, right, strict=True):
        assert old_lines == new_lines, label
