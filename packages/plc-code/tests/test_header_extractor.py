"""Tests for header extraction from SCL blocks."""

from plc_code.extractor.header import (
    ExtractedHeader,
    HeaderExtractor,
    extract_header,
    extract_header_info,
)
from plc_code.parser.models import Block, Network, NetworkAttributes, Region


class TestExtractedHeaderModel:
    """Tests for ExtractedHeader dataclass."""

    def test_default_values(self) -> None:
        """Test default values for ExtractedHeader."""
        header = ExtractedHeader()

        assert header.title == ""
        assert header.comment == ""
        assert header.library == ""
        assert header.author == ""
        assert header.copyright == ""
        assert header.changelog == []
        assert header.description == ""
        assert header.raw_header == ""


class TestHeaderExtractor:
    """Tests for HeaderExtractor class."""

    def test_extract_empty_block(self) -> None:
        """Test extracting from block with no regions."""
        block = Block(name="Test", block_type="FUNCTION_BLOCK")

        extractor = HeaderExtractor(block)
        result = extractor.extract()

        assert result.title == ""
        assert result.description == ""

    def test_extract_title_from_header(self) -> None:
        """Test extracting title from Block info header."""
        header_content = """// Title:      MyFunctionBlock
// Comment:    This is a test block
// Library:    TestLib
// Author:     Test Author
// Copyright:  (c) 2025 Test Corp"""

        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            networks=[
                Network(
                    attributes=NetworkAttributes(language="SCL"),
                    regions=[Region(name="Block info header", content=header_content)],
                )
            ],
        )

        extractor = HeaderExtractor(block)
        result = extractor.extract()

        assert result.title == "MyFunctionBlock"
        assert result.comment == "This is a test block"
        assert result.library == "TestLib"
        assert result.author == "Test Author"
        assert result.copyright == "(c) 2025 Test Corp"

    def test_extract_function_as_comment(self) -> None:
        """Test extracting Function: as comment alias."""
        header_content = """// Title:      MyBlock
// Function:   Perform some calculation"""

        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            networks=[Network(regions=[Region(name="Block info header", content=header_content)])],
        )

        result = extract_header(block)

        assert result.comment == "Perform some calculation"

    def test_extract_family_as_library(self) -> None:
        """Test extracting Family: as library alias."""
        header_content = """// Title:      MyBlock
// Family:     ProcessLib"""

        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            networks=[Network(regions=[Region(name="Block info header", content=header_content)])],
        )

        result = extract_header(block)

        assert result.library == "ProcessLib"

    def test_extract_description_region(self) -> None:
        """Test extracting content from Description region."""
        description_content = """// This block manages hydraulic functionality.
// It handles pressure regulation and flow control.
//
// Usage: Call this block from the main program."""

        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            networks=[Network(regions=[Region(name="Description", content=description_content)])],
        )

        result = extract_header(block)

        assert "This block manages hydraulic functionality" in result.description
        assert "pressure regulation" in result.description
        assert "Usage:" in result.description

    def test_extract_changelog(self) -> None:
        """Test extracting changelog table."""
        header_content = """// Title:      MyBlock
// Change log
// | Version | Date       | Author          | Changes                    |
// +---------+------------+-----------------+----------------------------+
// | v2.0.0  | 13/06/2025 | Test Author     | Interface modification     |
// | v1.0.0  | 25/03/2025 | Test Author     | First released version     |"""

        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            networks=[Network(regions=[Region(name="Block info header", content=header_content)])],
        )

        result = extract_header(block)

        assert len(result.changelog) == 2
        assert result.changelog[0].version == "v2.0.0"
        assert result.changelog[0].date == "13/06/2025"
        assert result.changelog[0].author == "Test Author"
        assert result.changelog[0].changes == "Interface modification"
        assert result.changelog[1].version == "v1.0.0"
        assert result.changelog[1].changes == "First released version"

    def test_extract_changelog_skips_header_row(self) -> None:
        """Test that changelog extraction skips the header row."""
        header_content = """// Change log
// | Version | Date | Author | Changes |
// | v1.0.0  | 01/01/2025 | Author | Initial |"""

        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            networks=[Network(regions=[Region(name="Block info header", content=header_content)])],
        )

        result = extract_header(block)

        # Should only have one entry (not the header row)
        assert len(result.changelog) == 1
        assert result.changelog[0].version == "v1.0.0"

    def test_case_insensitive_region_name(self) -> None:
        """Test that region names are matched case-insensitively."""
        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            networks=[
                Network(
                    regions=[
                        Region(name="BLOCK INFO HEADER", content="// Title: Test"),
                        Region(name="DESCRIPTION", content="// Some description"),
                    ]
                )
            ],
        )

        result = extract_header(block)

        assert result.title == "Test"
        assert "Some description" in result.description

    def test_extract_from_nested_region(self) -> None:
        """Test extracting from nested regions."""
        outer = Region(
            name="Outer",
            nested_regions=[Region(name="Block info header", content="// Title: NestedTitle")],
        )

        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            networks=[Network(regions=[outer])],
        )

        result = extract_header(block)

        assert result.title == "NestedTitle"

    def test_raw_header_preserved(self) -> None:
        """Test that raw header content is preserved."""
        header_content = """// Title:      Test
// Author:     Test Author
// Some custom content here"""

        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            networks=[Network(regions=[Region(name="Block info header", content=header_content)])],
        )

        result = extract_header(block)

        assert result.raw_header == header_content

    def test_multiple_networks(self) -> None:
        """Test extraction with multiple networks."""
        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            networks=[
                Network(regions=[]),
                Network(regions=[Region(name="Block info header", content="// Title: Found")]),
                Network(regions=[Region(name="Description", content="// Desc here")]),
            ],
        )

        result = extract_header(block)

        assert result.title == "Found"
        assert "Desc here" in result.description


class TestExtractHeaderInfo:
    """Tests for extract_header_info function."""

    def test_returns_header_info_model(self) -> None:
        """Test that extract_header_info returns HeaderInfo model."""
        header_content = """// Title:      TestBlock
// Comment:    Test description
// Library:    TestLib
// Author:     Test Author
// Copyright:  (c) 2025"""

        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            networks=[Network(regions=[Region(name="Block info header", content=header_content)])],
        )

        result = extract_header_info(block)

        # Should return HeaderInfo from models
        assert result.title == "TestBlock"
        assert result.comment == "Test description"
        assert result.library == "TestLib"
        assert result.author == "Test Author"
        assert result.copyright == "(c) 2025"


class TestRealWorldExamples:
    """Tests using real-world header formats."""

    def test_code2docu_format(self) -> None:
        """Test extraction from Code2Docu format header."""
        header_content = """// -------------------------------------------------
// Title:       MotorStarter
// Comment:     Manage the motor starter state machine
// Library:     ProcessLib
// Author:      Example Author
// Copyright:   (c) Example Author 2025
// -------------------------------------------------
// Change log
// | Ver.    | Date       | Expert in charge        | Changes                    |
// +---------+------------+-------------------------+----------------------------+
// | v2.0.0  | 13/06/2025 | Example Author          | Interface modification     |
// | v1.0.0  | 25/03/2025 | Example Author          | First released version     |
// -------------------------------------------------"""

        block = Block(
            name="MotorStarter",
            block_type="FUNCTION_BLOCK",
            networks=[Network(regions=[Region(name="Block info header", content=header_content)])],
        )

        result = extract_header(block)

        assert result.title == "MotorStarter"
        assert result.comment == "Manage the motor starter state machine"
        assert result.library == "ProcessLib"
        assert result.author == "Example Author"
        assert result.copyright == "(c) Example Author 2025"
        assert len(result.changelog) == 2

    def test_multiline_description(self) -> None:
        """Test extraction of multiline description."""
        description_content = """// This function block controls the Hydraulic Power System.
//
// Key features:
// - Automatic pressure regulation
// - Flow rate monitoring
// - Temperature protection
//
// See Also:
//   - PumpConfig for configuration parameters
//   - PumpAlarms for alarm handling"""

        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            networks=[Network(regions=[Region(name="Description", content=description_content)])],
        )

        result = extract_header(block)

        assert "Hydraulic Power System" in result.description
        assert "Key features:" in result.description
        assert "Automatic pressure regulation" in result.description
        assert "PumpConfig" in result.description

    def test_minimal_header(self) -> None:
        """Test extraction from minimal header."""
        header_content = "// Title: Simple"

        block = Block(
            name="Test",
            block_type="FUNCTION_BLOCK",
            networks=[Network(regions=[Region(name="Block info header", content=header_content)])],
        )

        result = extract_header(block)

        assert result.title == "Simple"
        assert result.comment == ""
        assert result.library == ""
