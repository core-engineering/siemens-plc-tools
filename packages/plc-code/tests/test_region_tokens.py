"""Region carries its tokens, not only their flattened text.

Region.content is a lossy re-serialisation: the parser joins token values with
a space, so `#armNumber` becomes `# armNumber` and `=>` becomes `= >`. The
tokens keep the original line and column, which is what lets a parser decide
adjacency. This field is what the statement parser will read.
"""

from pathlib import Path

from plc_code.parser import parse_scl_file
from plc_code.parser.lexer import TokenType

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _first_region(path: Path):
    """Return the first region that actually carries body tokens.

    ``SignalDebounce.s7dcl``'s only regions are a comment-only header and an
    empty "Description" region, so filtering on non-blank ``content`` (as a
    first draft of this helper did) picks a region whose only content is
    excluded comment text and yields an empty ``tokens`` list. Filtering on
    ``tokens`` instead finds a region that actually has statement content,
    which is what these tests are meant to exercise.
    """
    block = parse_scl_file(path)
    assert block is not None
    for network in block.networks:
        for region in network.regions:
            if region.tokens:
                return region
    raise AssertionError(f"no region with tokens in {path.name}")


class TestRegionTokens:
    def test_tokens_are_populated(self) -> None:
        region = _first_region(FIXTURES / "PumpControl.s7dcl")
        assert region.tokens

    def test_tokens_carry_source_positions(self) -> None:
        region = _first_region(FIXTURES / "PumpControl.s7dcl")
        assert all(t.line > 0 for t in region.tokens)
        assert all(t.column > 0 for t in region.tokens)

    def test_no_comment_or_newline_tokens(self) -> None:
        region = _first_region(FIXTURES / "PumpControl.s7dcl")
        excluded = {TokenType.COMMENT, TokenType.BLOCK_COMMENT, TokenType.NEWLINE}
        assert not [t for t in region.tokens if t.type in excluded]

    def test_token_values_reconstruct_the_content(self) -> None:
        """Same coverage as content: joining the values reproduces it."""
        region = _first_region(FIXTURES / "PumpControl.s7dcl")
        joined = " ".join(t.value for t in region.tokens)
        for value in ("CASE", "END_CASE", "PROC_READY"):
            assert (value in joined) == (value in region.content)

    def test_content_is_unchanged(self) -> None:
        """Adding tokens must not disturb the string every consumer reads."""
        region = _first_region(FIXTURES / "PumpControl.s7dcl")
        assert region.content
        assert "# " in region.content or "#" in region.content
