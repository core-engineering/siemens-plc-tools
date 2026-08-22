"""The unit-level differential: `generate_statements` against `_generate_statements_via_strings`.

Task 6's instrument. The expression-level differential (`test_renderer_differential.py`)
compares `render(tree)` against `ExpressionTranslator().translate(scl_text(tokens))` --
one expression at a time, in isolation. This module compares one level up: for every
statement list found in the corpus (one per region, one per network's own out-of-region
tokens -- the same two populations `conftest._block_expression_slices` walks), it runs
BOTH generator entry points over the *same* parsed statements and asserts the Python
lines they produce line-for-line agree::

    _generate_statements_via_strings(statements, string_constants=...)
        against
    generate_statements(statements, string_constants=...)

`string_constants` is collected per block exactly as `SCLTranspiler.transpile` does
(`self._collect_string_constants()`, a pre-scan over every region's raw text), so a
block that uses symbolic CASE labels or symbolic assignments exercises the same mapping
in this differential that a real `transpile_block` run would use.

Unlike the expression-level differential, no divergence is expected or tolerated here.
`_generate_statements_via_strings` is the *pre-Task-6* generator, believed correct
(it is what every corpus project has been transpiled and tested with up to this
commit); `generate_statements` is one commit's worth of change away from it. A
divergence here means the native `Assignment` branch silently changed what some real
corpus statement means, and per the plan this task must not proceed past that -- there
is no whitespace-normalisation bar the way the expression-level differential has one:
these are the literal Python lines both sides would put in a generated module, and they
either match or they don't.

No golden file: the generated Python and the SCL it came from both carry customer
identifiers, and this repository is public (see `tests/test_no_confidential_references.py`).
Everything is compared and reported in memory, for one session, and never written to
disk.

Skips (rather than fails) when `PLC_CORPUS_ROOTS` is unset -- same convention as
`test_renderer_differential.py` and the same reason: the corpus is a read-only sibling
of this repository, present on a developer machine but absent on CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plc_code.executor.generator import _generate_statements_via_strings, generate_statements
from plc_code.executor.transpiler import SCLTranspiler
from plc_code.parser.models import Block
from plc_code.parser.statement_parser import parse_statements
from plc_code.parser.statements import Statement


def _corpus_statement_lists(block: Block) -> list[tuple[str, list[Statement]]]:
    """One entry per region and per network's own out-of-region tokens, parsed to statements.

    Mirrors `conftest._block_expression_slices`'s two populations (`network.regions[*]`
    and each network's own `tokens`) at the statement-list level rather than the
    expression-slice level -- this differential compares whole `generate_statements`
    calls, which take a *list* of statements, not one expression at a time.

    Parameters
    ----------
    block : Block
        A parsed block.

    Returns
    -------
    list[tuple[str, list[Statement]]]
        A label (block name, network index, region name or "outside any region") paired
        with the statements `parse_statements` reads from that unit's tokens. A unit
        whose tokens fail to parse contributes an empty statement list -- this
        differential is not the parser's own conformance check (see
        `test_statement_parser_corpus.py`), so a parse failure is treated the same on
        both sides of the comparison rather than skipped.
    """
    units: list[tuple[str, list[Statement]]] = []
    for index, network in enumerate(block.networks):
        for region in network.regions:
            if not region.tokens:
                continue
            result = parse_statements(region.tokens)
            label = f"{block.name} network[{index}] region {region.name!r}"
            units.append((label, result.statements))
        if network.tokens:
            result = parse_statements(network.tokens)
            label = f"{block.name} network[{index}] outside any region"
            units.append((label, result.statements))
    return units


def _block_string_constants(block: Block) -> dict[str, int]:
    """The string-constant mapping a real `transpile_block` run would use for `block`.

    Parameters
    ----------
    block : Block
        A parsed block.

    Returns
    -------
    dict[str, int]
        `SCLTranspiler._collect_string_constants`'s own result: the same pre-scan
        `SCLTranspiler.transpile` performs before generating any code, run here so this
        differential exercises the same `string_constants` a real transpile would pass
        to `generate_statements`.
    """
    transpiler = SCLTranspiler(block=block)
    transpiler._collect_string_constants()  # noqa: SLF001 - reusing the real pre-scan, not reinventing it
    return transpiler._string_constants  # noqa: SLF001


def test_generator_native_differential_over_the_corpus(
    corpus_blocks: tuple[tuple[Path, Block], ...],
) -> None:
    """`_generate_statements_via_strings` against `generate_statements`, over every unit found.

    No divergence is tolerated: see the module docstring for why this bar has no
    whitespace-normalisation or "expected residual" carve-out the way the
    expression-level differential does.

    Parameters
    ----------
    corpus_blocks : tuple[tuple[Path, Block], ...]
        The session-scoped, once-parsed corpus fixture from `conftest.py`.
    """
    blocks_seen = 0
    units_seen = 0
    agreements = 0
    divergences: list[str] = []

    for _path, block in corpus_blocks:
        blocks_seen += 1
        string_constants = _block_string_constants(block)
        for label, statements in _corpus_statement_lists(block):
            units_seen += 1
            old_lines = _generate_statements_via_strings(statements, string_constants=string_constants)
            new_lines = generate_statements(statements, string_constants=string_constants)
            if old_lines == new_lines:
                agreements += 1
            else:
                divergences.append(label)

    if blocks_seen == 0:
        pytest.skip("PLC_CORPUS_ROOTS is unset or names no readable project")

    print(
        f"\ngenerator native differential: {units_seen} unit(s) examined across "
        f"{blocks_seen} block(s), {agreements} agree, {len(divergences)} diverge"
    )
    assert divergences == []
    assert units_seen > 0
