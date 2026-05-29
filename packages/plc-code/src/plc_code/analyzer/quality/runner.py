"""Analysis runner for executing all quality rules on blocks.

This module provides the main runner class that executes all registered
quality rules against parsed blocks and aggregates results.
"""

from pathlib import Path

from plc_code.analyzer.quality.metrics import calculate_block_metrics
from plc_code.analyzer.quality.models import BlockAnalysisResult, ProjectAnalysisResult
from plc_code.analyzer.quality.rules import ALL_RULES, Rule
from plc_code.parser.models import Block


class AnalysisRunner:
    """Runs all quality rules on blocks.

    This class is the main entry point for code quality analysis.
    It executes all registered rules against blocks and returns
    structured results.

    Examples
    --------
    >>> from plc_code.analyzer.quality import AnalysisRunner
    >>> from plc_code.parser import parse_scl_file
    >>>
    >>> runner = AnalysisRunner()
    >>> block = parse_scl_file(Path("myblock.s7dcl"))
    >>> result = runner.analyze_block(block)
    >>> print(f"Errors: {result.error_count}, Warnings: {result.warning_count}")
    """

    def __init__(self) -> None:
        """Initialize the runner with all registered rules."""
        self.rules: list[Rule] = [rule_class() for rule_class in ALL_RULES]

    def analyze_block(self, block: Block) -> BlockAnalysisResult:
        """Analyze a single block with all rules.

        Parameters
        ----------
        block : Block
            The parsed block to analyze.

        Returns
        -------
        BlockAnalysisResult
            Analysis result with all violations and metrics.
        """
        result = BlockAnalysisResult(
            block_name=block.name,
            block_type=block.block_type,
            source_file=Path(block.source_file) if block.source_file else Path(),
        )

        # Run all rules
        for rule in self.rules:
            violations = rule.check(block)
            result.violations.extend(violations)

        # Compute metrics
        metrics = calculate_block_metrics(block)
        result.metrics = {
            "cyclomatic_complexity": metrics.cyclomatic_complexity,
            "max_nesting_depth": metrics.max_nesting_depth,
            "code_lines": metrics.code_lines,
            "variable_count": metrics.variable_count,
            "input_count": metrics.input_count,
            "output_count": metrics.output_count,
            "network_count": metrics.network_count,
            "region_count": metrics.region_count,
        }

        return result

    def analyze_blocks(self, blocks: list[Block]) -> ProjectAnalysisResult:
        """Analyze multiple blocks.

        Parameters
        ----------
        blocks : list[Block]
            Blocks to analyze.

        Returns
        -------
        ProjectAnalysisResult
            Combined analysis results for all blocks.
        """
        result = ProjectAnalysisResult()

        for block in blocks:
            block_result = self.analyze_block(block)
            result.block_results.append(block_result)

        return result

    def get_rule_info(self) -> list[dict[str, str]]:
        """Get information about all registered rules.

        Returns
        -------
        list[dict[str, str]]
            List of rule info dictionaries with code, name, description, etc.
        """
        rules_info = []
        for rule in self.rules:
            info = rule.info
            rules_info.append(
                {
                    "code": info.code,
                    "name": info.name,
                    "description": info.description,
                    "severity": info.severity.value,
                    "category": info.category.value,
                    "rationale": info.rationale,
                }
            )
        return rules_info


__all__ = ["AnalysisRunner"]
