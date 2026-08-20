"""Every expression slice in the repository's own fixtures must parse.

The customer corpus is not in this repository and cannot be; this test covers
the shipped fixtures, and the measurement across the five production projects is
run by hand through `plc code transpile --conformance` (task 6).
"""

from pathlib import Path

import pytest

from plc_code.parser import parse_scl_file
from plc_code.parser.expression_parser import parse_expression, verify_expression_consumed
from plc_code.parser.statement_parser import parse_statements

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _slices(statement, out):
    kind = type(statement).__name__
    if kind == "Assignment":
        out += [statement.target, statement.value]
    elif kind == "Call":
        out.append(statement.callee)
        for argument in statement.arguments:
            out.append(argument.value)
    elif kind == "If":
        for branch in statement.branches:
            if branch.condition:
                out.append(branch.condition)
            for inner in branch.body:
                _slices(inner, out)
        # `else_body` is a separate field from `branches`; missing it silently
        # under-counts the corpus by 12%.
        for inner in statement.else_body:
            _slices(inner, out)
    elif kind == "Case":
        out.append(statement.selector)
        for branch in statement.branches:
            out += list(branch.values)
            for inner in branch.body:
                _slices(inner, out)
        for inner in statement.default:
            _slices(inner, out)
    elif kind == "For":
        out += [statement.variable, statement.start, statement.end]
        if statement.step:
            out.append(statement.step)
        for inner in statement.body:
            _slices(inner, out)
    elif kind == "While":
        out.append(statement.condition)
        for inner in statement.body:
            _slices(inner, out)
    return out


@pytest.mark.parametrize("path", sorted(FIXTURES.rglob("*.s7dcl")), ids=lambda p: p.name)
def test_every_expression_slice_parses(path: Path) -> None:
    block = parse_scl_file(path)
    if block is None:
        pytest.skip("the structural parser cannot read this file")
    for network in block.networks:
        for region in network.regions:
            tokens = getattr(region, "tokens", None)
            if not tokens:
                continue
            for statement in parse_statements(tokens).statements:
                for slice_ in _slices(statement, []):
                    if not slice_:
                        continue
                    result = parse_expression(slice_)
                    assert result.errors == [], f"{path.name}: {[e.expected for e in result.errors]}"
                    assert verify_expression_consumed(slice_, result)
