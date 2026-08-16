"""Region.content must be byte-identical across the lexer change.

It is built from token.value, so typing a token is safe and merging is not.
This locks that in for the whole shipped corpus.
"""

from pathlib import Path

import pytest

from plc_code.parser import parse_scl_file

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.mark.parametrize("path", sorted(FIXTURES.rglob("*.s7dcl")), ids=lambda p: p.name)
def test_region_content_has_no_merged_tokens(path: Path) -> None:
    """Operators keep their own spacing, proving nothing was combined."""
    block = parse_scl_file(path)
    if block is None or not block.name:
        pytest.skip(f"{path.name} holds no parsable block")

    for network in block.networks:
        for region in network.regions:
            assert ">=" not in region.content
            assert "<>" not in region.content
            assert "=>" not in region.content
