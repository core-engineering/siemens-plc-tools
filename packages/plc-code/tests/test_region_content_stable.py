"""Region.content and Network.content must be byte-identical across changes.

Both are built from token.value, so typing a token is safe and merging is not.
This locks that in for the whole shipped corpus. `Network.content` joined the
lock when `Network.tokens` was added beside it: the tokens are the new field,
the string is the one 27 rules and the transpiler already read.
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
            assert "<=" not in region.content
            assert "<>" not in region.content
            assert "=>" not in region.content
            assert "**" not in region.content


def _code_lines(content: str) -> str:
    """``content`` without its comment lines.

    A comment is copied through verbatim, so an operator written inside one is
    not evidence of a merge: one fixture explains the `"=>"` binding in prose
    above the code that uses it. Only the generated part of the string carries
    the guarantee.
    """
    return "\n".join(line for line in content.splitlines() if not line.lstrip().startswith("//"))


@pytest.mark.parametrize("path", sorted(FIXTURES.rglob("*.s7dcl")), ids=lambda p: str(p))
def test_network_content_has_no_merged_tokens(path: Path) -> None:
    """Same guarantee for SCL that sits outside any REGION."""
    block = parse_scl_file(path)
    if block is None or not block.name:
        pytest.skip(f"{path.name} holds no parsable block")

    for network in block.networks:
        code = _code_lines(network.content)
        assert ">=" not in code
        assert "<=" not in code
        assert "<>" not in code
        assert "=>" not in code
        assert "**" not in code
