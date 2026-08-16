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


def _region_named(path: Path, name: str):
    """Return the region called ``name``, failing loudly if it is absent.

    Selection is by name, never by whether the region has tokens: these tests
    exist to prove tokens are populated, so a helper that filtered on tokens
    would make them unable to fail.
    """
    block = parse_scl_file(path)
    assert block is not None
    for network in block.networks:
        for region in network.regions:
            if region.name == name:
                return region
    raise AssertionError(f"{path.name} has no region named {name!r}")


class TestRegionTokens:
    def test_tokens_are_populated(self) -> None:
        region = _region_named(FIXTURES / "PumpControl.s7dcl", "Pump control state machine")
        assert region.tokens

    def test_tokens_carry_source_positions(self) -> None:
        region = _region_named(FIXTURES / "PumpControl.s7dcl", "Pump control state machine")
        assert all(t.line > 0 for t in region.tokens)
        assert all(t.column > 0 for t in region.tokens)

    def test_no_comment_or_newline_tokens(self) -> None:
        region = _region_named(FIXTURES / "PumpControl.s7dcl", "Pump control state machine")
        excluded = {TokenType.COMMENT, TokenType.BLOCK_COMMENT, TokenType.NEWLINE}
        assert not [t for t in region.tokens if t.type in excluded]

    def test_token_values_reconstruct_the_content(self) -> None:
        """Same coverage as content: joining the values reproduces it."""
        region = _region_named(FIXTURES / "PumpControl.s7dcl", "Pump control state machine")
        joined = " ".join(t.value for t in region.tokens)
        for value in ("CASE", "END_CASE", "PROC_READY"):
            assert (value in joined) == (value in region.content)

    def test_content_is_unchanged(self) -> None:
        """Adding tokens must not disturb the string every consumer reads."""
        region = _region_named(FIXTURES / "PumpControl.s7dcl", "Pump control state machine")
        assert region.content
        assert "# " in region.content or "#" in region.content

    def test_comment_only_region_has_no_tokens(self) -> None:
        """Comments contribute to content but never to tokens (see docstring above).

        This is the exact case that misled the original test design: a region
        can have substantial ``content`` while carrying zero ``tokens``, when
        that content is entirely comment text. Task 8/9 rely on comments being
        excluded from the statement-parser input.
        """
        region = _region_named(FIXTURES / "SignalDebounce.s7dcl", "Block info header")
        assert region.content
        assert region.tokens == []
