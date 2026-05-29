"""Tests for quality analysis runner."""

from pathlib import Path
from typing import Literal

from plc_code.analyzer.quality.models import Severity
from plc_code.analyzer.quality.runner import AnalysisRunner
from plc_code.parser.models import Block, Network, Region, VariableDeclaration, VariableSection

BlockType = Literal["FUNCTION_BLOCK", "FUNCTION", "TYPE"]


def make_block(
    name: str = "TestBlock",
    block_type: BlockType = "FUNCTION_BLOCK",
    source_file: str = "",
) -> Block:
    """Create a test block."""
    return Block(name=name, block_type=block_type, source_file=source_file)


def make_block_with_header(name: str = "TestBlock") -> Block:
    """Create a block with a proper header."""
    block = make_block(name=name, block_type="FUNCTION_BLOCK")
    network = Network()
    header_region = Region(
        name="Block info header",
        content="""//===============================================================================
// Title:            TestBlock
// Comment/Function: Test block description
// Author:           Test Author
//-------------------------------------------------------------------------------
// Change log table:
// Version  | Date       | Expert in charge | Changes applied
//----------|------------|------------------|------------------------------
// v1.0.0   | 01/01/2025 | Test Author      | Initial version
//===============================================================================""",
    )
    network.regions.append(header_region)
    block.networks.append(network)
    return block


class TestAnalysisRunner:
    """Tests for AnalysisRunner class."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.runner = AnalysisRunner()

    def test_runner_has_rules(self) -> None:
        """Test that runner loads all registered rules."""
        assert len(self.runner.rules) > 0
        # Should have rules from all categories
        rule_codes = [r.info.code for r in self.runner.rules]
        # Check for at least one rule from each category
        assert any(c.startswith("N") for c in rule_codes)  # Naming
        assert any(c.startswith("C") for c in rule_codes)  # Complexity
        assert any(c.startswith("D") for c in rule_codes)  # Documentation
        assert any(c.startswith("B") for c in rule_codes)  # Best practices
        assert any(c.startswith("S") for c in rule_codes)  # Structure

    def test_analyze_empty_block(self) -> None:
        """Test analyzing a minimal block."""
        block = make_block(name="MinimalBlock")
        result = self.runner.analyze_block(block)

        assert result.block_name == "MinimalBlock"
        assert result.block_type == "FUNCTION_BLOCK"
        # Should have some violations (at least missing header)
        assert len(result.violations) > 0

    def test_analyze_block_with_header(self) -> None:
        """Test analyzing a block with proper header."""
        block = make_block_with_header(name="ProperBlock")
        result = self.runner.analyze_block(block)

        assert result.block_name == "ProperBlock"
        # D001 should not be triggered (has header)
        d001_violations = [v for v in result.violations if v.rule_code == "D001"]
        assert len(d001_violations) == 0

    def test_analyze_block_metrics(self) -> None:
        """Test that metrics are computed."""
        block = make_block_with_header()
        # Add some variables
        block.variable_sections.append(
            VariableSection(
                section_type="VAR_INPUT",
                variables=[
                    VariableDeclaration(name="input1", data_type="Int"),
                    VariableDeclaration(name="input2", data_type="Bool"),
                ],
            )
        )
        block.variable_sections.append(
            VariableSection(
                section_type="VAR_OUTPUT",
                variables=[
                    VariableDeclaration(name="output1", data_type="Int"),
                ],
            )
        )

        result = self.runner.analyze_block(block)

        assert "variable_count" in result.metrics
        assert "input_count" in result.metrics
        assert "output_count" in result.metrics
        assert result.metrics["input_count"] == 2
        assert result.metrics["output_count"] == 1

    def test_analyze_multiple_blocks(self) -> None:
        """Test analyzing multiple blocks."""
        blocks = [
            make_block(name="Block1", block_type="FUNCTION_BLOCK"),
            make_block(name="Block2", block_type="FUNCTION"),
            make_block(name="typeBlock3", block_type="TYPE"),
        ]

        result = self.runner.analyze_blocks(blocks)

        assert len(result.block_results) == 3
        assert result.block_results[0].block_name == "Block1"
        assert result.block_results[1].block_name == "Block2"
        assert result.block_results[2].block_name == "typeBlock3"

    def test_get_rule_info(self) -> None:
        """Test getting rule information."""
        rules_info = self.runner.get_rule_info()

        assert len(rules_info) > 0
        # Each info should have required fields
        for info in rules_info:
            assert "code" in info
            assert "name" in info
            assert "description" in info
            assert "severity" in info
            assert "category" in info

    def test_source_file_in_result(self) -> None:
        """Test that source file is captured in result."""
        block = make_block(
            name="TestBlock",
            source_file="/path/to/block.s7dcl",
        )
        result = self.runner.analyze_block(block)

        assert result.source_file == Path("/path/to/block.s7dcl")


class TestAnalysisRunnerNamingRules:
    """Tests for naming rule integration in runner."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.runner = AnalysisRunner()

    def test_detects_bad_variable_name(self) -> None:
        """Test detection of non-camelCase variable."""
        block = make_block_with_header(name="TestBlock")
        block.variable_sections.append(
            VariableSection(
                section_type="VAR",
                variables=[
                    VariableDeclaration(name="BadVariableName", data_type="Int"),
                ],
            )
        )

        result = self.runner.analyze_block(block)

        n001_violations = [v for v in result.violations if v.rule_code == "N001"]
        assert len(n001_violations) == 1
        assert "BadVariableName" in n001_violations[0].message

    def test_detects_bad_block_name(self) -> None:
        """Test detection of non-PascalCase block name."""
        block = make_block_with_header(name="badBlockName")

        result = self.runner.analyze_block(block)

        n003_violations = [v for v in result.violations if v.rule_code == "N003"]
        assert len(n003_violations) == 1


class TestAnalysisRunnerDocumentationRules:
    """Tests for documentation rule integration in runner."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.runner = AnalysisRunner()

    def test_detects_missing_header(self) -> None:
        """Test detection of missing block header."""
        block = make_block(name="NoHeaderBlock")

        result = self.runner.analyze_block(block)

        d001_violations = [v for v in result.violations if v.rule_code == "D001"]
        assert len(d001_violations) == 1
        assert d001_violations[0].severity == Severity.ERROR
