"""Pytest configuration and fixtures."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from plc_iol.core.config import FunctionalGroupConfig, NamingConfig, PathsConfig, ProjectConfig
from plc_iol.core.models import DataType, IOCategory, IODatabase, IOPoint


@pytest.fixture
def sample_point() -> IOPoint:
    """Create a sample IO point."""
    return IOPoint(
        mnemonic="DI_STATION_PUMP_START",
        signal_name="PUMP START",
        customer_tag="DI-6001",
        functional_group="COMMON",
        io_category=IOCategory.DI,
        physical_type="Push button",
        data_type=DataType.BOOL,
        hw_address="E 1.0",
        plc_address="%I1.0",
        is_safety=False,
        circuit_ref="ZSC 1-1",
    )


@pytest.fixture
def sample_points() -> list[IOPoint]:
    """Create a list of sample IO points."""
    return [
        IOPoint(
            mnemonic="DI_STATION_PUMP_START",
            signal_name="PUMP START",
            io_category=IOCategory.DI,
            plc_address="%I1.0",
            functional_group="COMMON",
        ),
        IOPoint(
            mnemonic="DI_STATION_PUMP_STOP",
            signal_name="PUMP STOP",
            io_category=IOCategory.DI,
            plc_address="%I1.1",
            functional_group="COMMON",
        ),
        IOPoint(
            mnemonic="DO_STATION_PUMP_RUN",
            signal_name="PUMP RUN",
            io_category=IOCategory.DO,
            plc_address="%Q2.0",
            functional_group="COMMON",
        ),
        IOPoint(
            mnemonic="AI_DRIVE_PRESSURE",
            signal_name="DRIVE PRESSURE",
            io_category=IOCategory.AI,
            plc_address="%IW100",
            data_type=DataType.INT,
            functional_group="COMMON",
        ),
        IOPoint(
            mnemonic="DI_AXIS1_LIMIT_INNER",
            signal_name="INNER LIMIT",
            io_category=IOCategory.DI,
            plc_address="%I10.0",
            functional_group="AXIS1",
        ),
        IOPoint(
            mnemonic="SDI_AXIS1_ESTOP",
            signal_name="EMERGENCY STOP",
            io_category=IOCategory.SDI,
            plc_address="%I20.0",
            functional_group="AXIS1",
            is_safety=True,
        ),
    ]


@pytest.fixture
def sample_database(sample_points) -> IODatabase:
    """Create a sample database with points."""
    db = IODatabase()
    for point in sample_points:
        db.add(point)
    return db


@pytest.fixture
def temp_dir():
    """Create a temporary directory."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_config(temp_dir) -> ProjectConfig:
    """Create a sample project configuration."""
    # Create directory structure
    (temp_dir / "tags").mkdir()
    (temp_dir / "iol").mkdir()
    (temp_dir / ".iol").mkdir()

    return ProjectConfig(
        project_root=temp_dir,
        name="Test Project",
        code="TEST001",
        functional_groups=[
            FunctionalGroupConfig(
                id="COMMON",
                name="Common Equipment",
                xml_files=["Station.xml", "Drive.xml"],
                iol_sheets=["COMMON"],
            ),
            FunctionalGroupConfig(
                id="AXIS1",
                name="Axis 1",
                xml_files=["Axis1.xml"],
                iol_sheets=["AXIS1"],
            ),
        ],
        paths=PathsConfig(
            tags="tags",
            iol="iol",
            database=".iol",
        ),
        naming=NamingConfig(
            pattern="{io_category}_{location}_{signal}",
            locations=["STATION", "DRIVE", "AXIS1", "AXIS2"],
            max_length=64,
        ),
    )


@pytest.fixture
def sample_xml_content() -> str:
    """Create sample S7-1500 XML content."""
    return """<?xml version="1.0" encoding="utf-8"?>
<Document>
  <Engineering version="V21" />
  <SW.Tags.PlcTagTable ID="0">
    <AttributeList>
      <Name>TestTags</Name>
    </AttributeList>
    <ObjectList>
      <SW.Tags.PlcTag ID="1" CompositionName="Tags">
        <AttributeList>
          <DataTypeName>Bool</DataTypeName>
          <ExternalAccessible>false</ExternalAccessible>
          <LogicalAddress>%I1.0</LogicalAddress>
          <Name>DI_STATION_TEST_INPUT</Name>
        </AttributeList>
        <ObjectList>
          <MultilingualText ID="2" CompositionName="Comment">
            <ObjectList>
              <MultilingualTextItem ID="3" CompositionName="Items">
                <AttributeList>
                  <Culture>en-US</Culture>
                  <Text>ZSC 1-1</Text>
                </AttributeList>
              </MultilingualTextItem>
            </ObjectList>
          </MultilingualText>
        </ObjectList>
      </SW.Tags.PlcTag>
      <SW.Tags.PlcTag ID="4" CompositionName="Tags">
        <AttributeList>
          <DataTypeName>Int</DataTypeName>
          <ExternalAccessible>false</ExternalAccessible>
          <LogicalAddress>%IW100</LogicalAddress>
          <Name>AI_DRIVE_PRESSURE</Name>
        </AttributeList>
      </SW.Tags.PlcTag>
    </ObjectList>
  </SW.Tags.PlcTagTable>
</Document>"""
