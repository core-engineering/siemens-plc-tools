"""Rebuilding the SCL text of a statement from the tokens that produced it.

`Region.content` is `token.value` joined with single spaces, so a slice of that
content rejoins the same way. The generator needs this because the existing
translators take strings, and reusing them verbatim is what makes the new path's
output byte-identical.
"""

from __future__ import annotations

from plc_code.executor.generator import scl_text
from plc_code.parser.lexer import TokenType, tokenize


def _tokens(source: str):
    return [t for t in tokenize(source) if t.type is not TokenType.EOF]


def test_a_slice_rejoins_with_single_spaces() -> None:
    assert scl_text(_tokens("#a := #b + 1")) == "# a := # b + 1"


def test_an_empty_slice_is_an_empty_string() -> None:
    assert scl_text([]) == ""


def test_it_matches_the_content_the_parser_built() -> None:
    from pathlib import Path

    from plc_code.parser import parse_scl_file

    fixtures = Path(__file__).resolve().parent / "fixtures"
    block = parse_scl_file(fixtures / "Doubler.s7dcl")
    network = block.networks[0]
    assert scl_text(network.tokens) == network.content.replace("\n", " ").strip()
