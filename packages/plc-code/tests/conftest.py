"""Shared pytest fixtures for plc-code tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from plc_code.executor.control_flow import ControlFlowTranslator
from plc_code.executor.generator import UnsupportedStatement, generate_statements
from plc_code.parser.lexer import Token
from plc_code.parser.models import Block
from plc_code.parser.statement_parser import parse_statements


def translate_old(block: Block) -> list[tuple[str, list[str]]]:
    """Every code unit of a block, translated by the text path.

    Parameters
    ----------
    block : Block
        A parsed block.

    Returns
    -------
    list[tuple[str, list[str]]]
        One entry per non-empty region and per network holding SCL outside any
        region: a label identifying the unit, and the Python lines the old path
        emits for it.
    """
    units: list[tuple[str, list[str]]] = []
    for index, network in enumerate(block.networks):
        for region in network.regions:
            if not region.content:
                continue
            label = f"{block.name} network[{index}] region {region.name!r}"
            units.append((label, ControlFlowTranslator().translate_block(region.content)))
        if network.content:
            label = f"{block.name} network[{index}] outside any region"
            units.append((label, ControlFlowTranslator().translate_block(network.content)))
    return units


@pytest.fixture
def differential_old() -> Callable[[Block], list[tuple[str, list[str]]]]:
    """The text-path translator, for differential comparison against the AST path.

    Returns
    -------
    Callable[[Block], list[tuple[str, list[str]]]]
        ``translate_old``, translating every code unit of a block with the
        existing text path.
    """
    return translate_old


def translate_new(block: Block) -> list[tuple[str, list[str]]]:
    """The same code units, translated from the statement AST.

    Returns
    -------
    list[tuple[str, list[str]]]
        Same labels and order as ``translate_old``. A unit whose statements the
        generator cannot yet handle yields the sentinel ``["<unsupported>"]``,
        so a partly-built generator fails one unit loudly instead of silently
        matching an empty list.
    """
    units: list[tuple[str, list[str]]] = []
    for index, network in enumerate(block.networks):
        for region in network.regions:
            if not region.content:
                continue
            label = f"{block.name} network[{index}] region {region.name!r}"
            units.append((label, _generate_or_sentinel(region.tokens)))
        if network.content:
            label = f"{block.name} network[{index}] outside any region"
            units.append((label, _generate_or_sentinel(network.tokens)))
    return units


def _generate_or_sentinel(tokens: list[Token]) -> list[str]:
    result = parse_statements(tokens)
    if result.errors:
        return ["<unparsed>"]
    try:
        return generate_statements(result.statements)
    except UnsupportedStatement:
        return ["<unsupported>"]


@pytest.fixture
def differential_new() -> Callable[[Block], list[tuple[str, list[str]]]]:
    """The AST-path translator, for differential comparison against the text path.

    Returns
    -------
    Callable[[Block], list[tuple[str, list[str]]]]
        ``translate_new``, translating every code unit of a block with the
        statement-AST generator.
    """
    return translate_new


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
