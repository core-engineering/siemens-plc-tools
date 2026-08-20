"""A Network carries its tokens, not only their flattened text.

`Region.tokens` was added because `Region.content` is a lossy re-serialisation.
SCL written directly inside a NETWORK, outside any REGION, had no equivalent: it
reached `Network.content` as the same lossy string and its tokens were dropped
on the floor. 168 of 649 blocks in five production projects are written that
way — 52,288 tokens, 29% of the corpus SCL — and none of it could reach the
statement parser.

`Network.content` is unchanged, byte for byte. This is the same additive pair
`Region` already carries.
"""

from pathlib import Path

from plc_code.parser import parse_scl_file
from plc_code.parser.lexer import TokenType, tokenize_with_newlines
from plc_code.parser.parser import SCLParser
from plc_code.parser.statement_parser import parse_statements

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _network(path: Path, index: int = 0):
    block = parse_scl_file(path)
    assert block is not None
    return block.networks[index]


class TestNetworkTokens:
    def test_tokens_are_populated(self) -> None:
        network = _network(FIXTURES / "Doubler.s7dcl")
        assert [token.value for token in network.tokens] == [
            "#",
            "result",
            ":=",
            "#",
            "x",
            "*",
            "2.0",
            ";",
        ]

    def test_tokens_carry_source_positions(self) -> None:
        network = _network(FIXTURES / "Doubler.s7dcl")
        assert all(token.line > 0 and token.column > 0 for token in network.tokens)

    def test_content_keeps_its_lossy_spelling(self) -> None:
        # The whole point of the pair: content is unchanged, so its consumers
        # are unchanged, and the tokens carry what it lost.
        network = _network(FIXTURES / "Doubler.s7dcl")
        assert network.content == "# result := # x * 2.0 ;\n"

    def test_comments_and_newlines_are_not_tokens(self) -> None:
        network = _network(FIXTURES / "IsFiniteLreal.s7dcl")
        assert "//" not in "".join(token.value for token in network.tokens)
        assert all(token.type is not TokenType.COMMENT for token in network.tokens)
        assert all(token.type is not TokenType.NEWLINE for token in network.tokens)
        assert network.content.startswith("//")

    def test_a_network_holding_only_comments_has_no_tokens(self) -> None:
        source = """
FUNCTION_BLOCK "Test"
    { S7_Language := "SCL" }
    NETWORK
        // nothing but prose
    END_NETWORK
END_FUNCTION_BLOCK
"""
        block = SCLParser(tokenize_with_newlines(source)).parse()
        assert block.networks[0].tokens == []
        assert block.networks[0].content.strip() == "// nothing but prose"

    def test_region_tokens_do_not_leak_into_the_network(self) -> None:
        # A REGION is parsed by its own branch, so its tokens belong to it and
        # must not be counted twice by a caller walking both.
        source = """
FUNCTION_BLOCK "Test"
    { S7_Language := "SCL" }
    NETWORK
        #before := TRUE;
        REGION "Logic"
            #inside := TRUE;
        END_REGION
        #after := FALSE;
    END_NETWORK
END_FUNCTION_BLOCK
"""
        block = SCLParser(tokenize_with_newlines(source)).parse()
        network = block.networks[0]
        assert [token.value for token in network.regions[0].tokens] == [
            "#",
            "inside",
            ":=",
            "TRUE",
            ";",
        ]
        assert "inside" not in [token.value for token in network.tokens]
        assert "before" in [token.value for token in network.tokens]
        assert "after" in [token.value for token in network.tokens]

    def test_a_ladder_network_collects_no_scl_tokens(self) -> None:
        # RUNG elements are read by their own branch. Nothing in a LADDER
        # network should reach the statement parser as if it were SCL.
        source = """
FUNCTION_BLOCK "Test"
    { S7_Language := "LAD" }
    NETWORK
        RUNG
        END_RUNG
    END_NETWORK
END_FUNCTION_BLOCK
"""
        block = SCLParser(tokenize_with_newlines(source)).parse()
        assert block.networks[0].tokens == []


class TestNetworkTokensParse:
    def test_the_statement_parser_reads_them(self) -> None:
        network = _network(FIXTURES / "Doubler.s7dcl")
        result = parse_statements(network.tokens)
        assert result.errors == []
        assert len(result.statements) == 1

    def test_a_multi_statement_network_parses_whole(self) -> None:
        network = _network(FIXTURES / "OneBased1D.s7dcl")
        result = parse_statements(network.tokens)
        assert result.errors == []
        assert len(result.statements) == 4
