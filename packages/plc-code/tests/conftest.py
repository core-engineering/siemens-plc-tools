"""Shared pytest fixtures for plc-code tests."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from plc_code.parser.expressions import Expression
from plc_code.parser.lexer import Token
from plc_code.parser.models import Block
from plc_code.parser.statement_parser import parse_statements
from plc_code.parser.statements import Assignment, Call, Case, For, If, Statement, While


def _statement_expression_slices(
    statements: list[Statement], label_prefix: str
) -> Iterator[tuple[str, list[Token], Expression | None]]:
    """Yield one entry per non-empty expression-bearing slice, recursing into nested bodies.

    Mirrors ``plc_code.parser.conformance._expression_slice_counts`` field for field and
    recursion site for recursion site — an ``If``'s ``branches`` **and its separate**
    ``else_body``, a ``Case``'s ``branches`` **and its separate** ``default``, a ``For``'s
    and a ``While``'s ``body`` — so matching that enumeration is how this walker is known
    not to miss a slice kind, rather than inventing its own and going quiet on one.

    An empty slice (e.g. a ``For`` loop with no ``BY`` clause) never held an expression to
    parse and is not yielded at all, same as ``_expression_slice_counts`` does not count it.

    Parameters
    ----------
    statements : list[Statement]
        Statements to walk, typically ``ParseResult.statements`` for one region or network.
    label_prefix : str
        Human-readable path to these statements (block, network, region), prepended to
        each yielded label so a divergence can be attributed to where it came from.

    Yields
    ------
    tuple[str, list[Token], Expression | None]
        A label identifying the slice, its token slice, and its parsed tree (``None`` when
        the slice could not be read as an expression).
    """
    for statement in statements:
        if isinstance(statement, Assignment):
            if statement.target:
                yield f"{label_prefix}: Assignment.target", statement.target, statement.target_expr
            if statement.value:
                yield f"{label_prefix}: Assignment.value", statement.value, statement.value_expr
        elif isinstance(statement, Call):
            if statement.callee:
                yield f"{label_prefix}: Call.callee", statement.callee, statement.callee_expr
            for index, argument in enumerate(statement.arguments):
                if argument.value:
                    yield (
                        f"{label_prefix}: Call.arguments[{index}].value",
                        argument.value,
                        argument.value_expr,
                    )
        elif isinstance(statement, If):
            for index, branch in enumerate(statement.branches):
                if branch.condition:
                    yield (
                        f"{label_prefix}: If.branches[{index}].condition",
                        branch.condition,
                        branch.condition_expr,
                    )
                yield from _statement_expression_slices(
                    branch.body, f"{label_prefix}: If.branches[{index}].body"
                )
            yield from _statement_expression_slices(statement.else_body, f"{label_prefix}: If.else_body")
        elif isinstance(statement, Case):
            if statement.selector:
                yield f"{label_prefix}: Case.selector", statement.selector, statement.selector_expr
            for index, case_branch in enumerate(statement.branches):
                for value_index, value in enumerate(case_branch.values):
                    if not value:
                        continue
                    value_expr = (
                        case_branch.values_expr[value_index]
                        if value_index < len(case_branch.values_expr)
                        else None
                    )
                    yield (
                        f"{label_prefix}: Case.branches[{index}].values[{value_index}]",
                        value,
                        value_expr,
                    )
                yield from _statement_expression_slices(
                    case_branch.body, f"{label_prefix}: Case.branches[{index}].body"
                )
            yield from _statement_expression_slices(statement.default, f"{label_prefix}: Case.default")
        elif isinstance(statement, For):
            if statement.start:
                yield f"{label_prefix}: For.start", statement.start, statement.start_expr
            if statement.end:
                yield f"{label_prefix}: For.end", statement.end, statement.end_expr
            if statement.step:
                yield f"{label_prefix}: For.step", statement.step, statement.step_expr
            yield from _statement_expression_slices(statement.body, f"{label_prefix}: For.body")
        elif isinstance(statement, While):
            if statement.condition:
                yield f"{label_prefix}: While.condition", statement.condition, statement.condition_expr
            yield from _statement_expression_slices(statement.body, f"{label_prefix}: While.body")


def _block_expression_slices(block: Block) -> Iterator[tuple[str, list[Token], Expression | None]]:
    """Every expression-bearing slice of a block: every network and every region.

    Walks ``block.networks[*].regions`` (parsing each region's ``tokens``) and each
    network's own out-of-region ``tokens``, same two populations
    ``parser.conformance.build_report`` measures.

    Parameters
    ----------
    block : Block
        A parsed block.

    Yields
    ------
    tuple[str, list[Token], Expression | None]
        Same shape as ``_statement_expression_slices``, labelled with the block name,
        network index, and region name (or "outside any region") the slice came from.
    """
    for index, network in enumerate(block.networks):
        for region in network.regions:
            if not region.tokens:
                continue
            result = parse_statements(region.tokens)
            label_prefix = f"{block.name} network[{index}] region {region.name!r}"
            yield from _statement_expression_slices(result.statements, label_prefix)
        if network.tokens:
            result = parse_statements(network.tokens)
            label_prefix = f"{block.name} network[{index}] outside any region"
            yield from _statement_expression_slices(result.statements, label_prefix)


@pytest.fixture
def expression_slices() -> Callable[[Block], Iterator[tuple[str, list[Token], Expression | None]]]:
    """Expose the expression-slice walker as a fixture.

    A later differential needs this same walker from a second test module; this
    repository forbids ``__init__.py`` in a ``tests/`` directory (see ``CLAUDE.md``
    §6), so a plain cross-file import is not the convention here — a fixture is.

    Returns
    -------
    Callable[[Block], Iterator[tuple[str, list[Token], Expression | None]]]
        ``_block_expression_slices``, so a test calls ``expression_slices(block)`` for
        one ``(label, tokens, tree)`` entry per non-empty expression-bearing slice.
    """
    return _block_expression_slices


@pytest.fixture
def simple_xml_tags_dir(tmp_path: Path) -> Path:
    """Create a minimal XML tags directory in TIA Portal V21 format.

    The fixture produces one ``Station.xml`` file with five I/O tags:

    * ``DI_LCP_LAMP_TEST``   — instrument tag ``DI-001``  at ``%E2.6``
    * ``DI_LCP_ALARM_ACK``   — instrument tag ``DI-002``  at ``%E2.7``
    * ``DI_LCP_SLOW_SPEED``  — instrument tag ``DI-003``  at ``%E2.9``
    * ``DI_LCP_HIGH_TEMP1``  — instrument tag ``DI-004``  at ``%E3.0``
    * ``DI_LCP_HIGH_TEMP2``  — instrument tag ``DI-005``  at ``%E3.1``

    Parameters
    ----------
    tmp_path : Path
        Pytest-provided temporary directory.

    Returns
    -------
    Path
        Directory containing one TIA Portal V21 XML tag table file.
    """
    d = tmp_path / "tags"
    d.mkdir()
    (d / "Station.xml").write_text(
        """\
<?xml version="1.0" encoding="utf-8"?>
<Document>
  <SW.Tags.PlcTagTable>
    <AttributeList><Name>Station</Name></AttributeList>
    <ObjectList>

      <SW.Tags.PlcTag>
        <AttributeList>
          <DataTypeName>Bool</DataTypeName>
          <LogicalAddress>%E2.6</LogicalAddress>
          <Name>DI_LCP_LAMP_TEST</Name>
        </AttributeList>
        <ObjectList>
          <MultilingualText CompositionName="Comment">
            <ObjectList>
              <MultilingualTextItem>
                <AttributeList>
                  <Culture>en-US</Culture>
                  <Text>010-DI-001</Text>
                </AttributeList>
              </MultilingualTextItem>
            </ObjectList>
          </MultilingualText>
        </ObjectList>
      </SW.Tags.PlcTag>

      <SW.Tags.PlcTag>
        <AttributeList>
          <DataTypeName>Bool</DataTypeName>
          <LogicalAddress>%E2.7</LogicalAddress>
          <Name>DI_LCP_ALARM_ACK</Name>
        </AttributeList>
        <ObjectList>
          <MultilingualText CompositionName="Comment">
            <ObjectList>
              <MultilingualTextItem>
                <AttributeList>
                  <Culture>en-US</Culture>
                  <Text>010-DI-002</Text>
                </AttributeList>
              </MultilingualTextItem>
            </ObjectList>
          </MultilingualText>
        </ObjectList>
      </SW.Tags.PlcTag>

      <SW.Tags.PlcTag>
        <AttributeList>
          <DataTypeName>Bool</DataTypeName>
          <LogicalAddress>%E2.9</LogicalAddress>
          <Name>DI_LCP_SLOW_SPEED</Name>
        </AttributeList>
        <ObjectList>
          <MultilingualText CompositionName="Comment">
            <ObjectList>
              <MultilingualTextItem>
                <AttributeList>
                  <Culture>en-US</Culture>
                  <Text>010-DI-003</Text>
                </AttributeList>
              </MultilingualTextItem>
            </ObjectList>
          </MultilingualText>
        </ObjectList>
      </SW.Tags.PlcTag>

      <SW.Tags.PlcTag>
        <AttributeList>
          <DataTypeName>Bool</DataTypeName>
          <LogicalAddress>%E3.0</LogicalAddress>
          <Name>DI_LCP_HIGH_TEMP1</Name>
        </AttributeList>
        <ObjectList>
          <MultilingualText CompositionName="Comment">
            <ObjectList>
              <MultilingualTextItem>
                <AttributeList>
                  <Culture>en-US</Culture>
                  <Text>010-DI-004</Text>
                </AttributeList>
              </MultilingualTextItem>
            </ObjectList>
          </MultilingualText>
        </ObjectList>
      </SW.Tags.PlcTag>

      <SW.Tags.PlcTag>
        <AttributeList>
          <DataTypeName>Bool</DataTypeName>
          <LogicalAddress>%E3.1</LogicalAddress>
          <Name>DI_LCP_HIGH_TEMP2</Name>
        </AttributeList>
        <ObjectList>
          <MultilingualText CompositionName="Comment">
            <ObjectList>
              <MultilingualTextItem>
                <AttributeList>
                  <Culture>en-US</Culture>
                  <Text>010-DI-005</Text>
                </AttributeList>
              </MultilingualTextItem>
            </ObjectList>
          </MultilingualText>
        </ObjectList>
      </SW.Tags.PlcTag>

    </ObjectList>
  </SW.Tags.PlcTagTable>
</Document>
""",
        encoding="utf-8",
    )
    return d


@pytest.fixture
def simple_scl_dir(tmp_path: Path) -> Path:
    """Create a minimal SCL directory exercising both FB declaration forms.

    The fixture produces one ``PumpControl.s7dcl`` file with:

    * ``motorStartCmd``   — instance of ``"MotorStarter"``  (quoted, legacy form)
    * ``pumpFaultAlarm``  — instance of ``_.MotorStarter``  (library-ref form)

    This covers both declaration syntaxes that the resolver must handle:
    quoted (user-defined FB) and underscore-dot library reference (TIA Portal library FB).

    Parameters
    ----------
    tmp_path : Path
        Pytest-provided temporary directory.

    Returns
    -------
    Path
        Directory containing one TIA Portal V21 SCL file.
    """
    d = tmp_path / "scl"
    d.mkdir()
    (d / "PumpControl.s7dcl").write_text(
        """FUNCTION_BLOCK "PumpControl"
{ S7_Optimized := 'TRUE' }
VERSION : 0.1
VAR
    motorStartCmd : "MotorStarter";       // quoted (legacy)
    pumpFaultAlarm : _.MotorStarter;      // library ref
END_VAR
BEGIN
    motorStartCmd(Trigger := input."DI-001",
                  Acknowledge := input.alarmAck,
                  alarmReset := input.alarmReset);
    pumpFaultAlarm(alarmTrigger := input.pumpFault,
                   alarmAcknowledge := TRUE,
                   alarmReset := input.alarmReset);
END_FUNCTION_BLOCK
""",
        encoding="utf-8",
    )
    return d
