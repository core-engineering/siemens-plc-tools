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

    def __init__(self, safety_path_pattern: str = "safety") -> None:
        """Initialize the runner with all registered rules.

        Parameters
        ----------
        safety_path_pattern : str
            Case-insensitive substring marking a directory as safety territory,
            forwarded to ``build_safety_report`` when ``analyze_blocks`` is given
            ``sources``.
        """
        self.rules: list[Rule] = [rule_class() for rule_class in ALL_RULES]
        self.safety_path_pattern = safety_path_pattern

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

    def analyze_blocks(
        self,
        blocks: list[Block],
        sources: list[tuple[Path, Block]] | None = None,
    ) -> ProjectAnalysisResult:
        """Analyse every block, and the project as a whole when paths are given.

        Parameters
        ----------
        blocks : list[Block]
            Blocks to check with the per-block rules.
        sources : list[tuple[Path, Block]] | None
            Source path and block pairs. When given, project-level checks run and
            their findings land in ``ProjectAnalysisResult.project_violations``.
            Deliberately not a name-keyed mapping: a UDT's name may be absent.

        Returns
        -------
        ProjectAnalysisResult
            Combined analysis results.
        """
        result = ProjectAnalysisResult()

        for block in blocks:
            result.block_results.append(self.analyze_block(block))

        if sources is not None:
            from plc_code.analyzer.safety_crossref import build_safety_report

            result.project_violations.extend(
                build_safety_report(sources, self.safety_path_pattern).violations
            )

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
