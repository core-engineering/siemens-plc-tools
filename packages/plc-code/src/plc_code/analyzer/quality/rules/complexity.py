"""Complexity rules for SCL code quality.

This module implements rules for detecting overly complex code
that may be difficult to understand, test, and maintain.
"""

from plc_code.analyzer.quality.metrics import calculate_block_metrics
from plc_code.analyzer.quality.models import RuleCategory, RuleInfo, Severity, Violation
from plc_code.analyzer.quality.rules import Rule, register_rule
from plc_code.parser.models import Block

# Thresholds for complexity rules
CYCLOMATIC_COMPLEXITY_THRESHOLD = 10
NESTING_DEPTH_THRESHOLD = 4
NESTING_DEPTH_THRESHOLD_OB = 7  # Higher threshold for organization blocks
BLOCK_SIZE_THRESHOLD = 500
VARIABLE_COUNT_THRESHOLD = 30
PARAMETER_COUNT_THRESHOLD = 10


@register_rule
class CyclomaticComplexityRule(Rule):
    """C001: Block cyclomatic complexity too high.

    This rule checks that blocks don't exceed a cyclomatic complexity
    threshold, indicating too many decision points.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="C001",
            name="cyclomatic-complexity",
            description=(f"Block cyclomatic complexity should not exceed {CYCLOMATIC_COMPLEXITY_THRESHOLD}"),
            severity=Severity.WARNING,
            category=RuleCategory.COMPLEXITY,
            rationale="High cyclomatic complexity indicates many decision paths, "
            "making code harder to test and maintain. Consider splitting into "
            "smaller, focused blocks.",
            examples_bad=["Block with many nested IF/CASE statements"],
            examples_good=["Block with clear, linear logic flow"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check cyclomatic complexity.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Single violation if complexity exceeds threshold.
        """
        violations = []

        metrics = calculate_block_metrics(block)
        if metrics.cyclomatic_complexity > CYCLOMATIC_COMPLEXITY_THRESHOLD:
            violations.append(
                self._create_violation(
                    message=(
                        f"Block '{block.name}' has cyclomatic complexity "
                        f"{metrics.cyclomatic_complexity} "
                        f"(threshold: {CYCLOMATIC_COMPLEXITY_THRESHOLD})"
                    ),
                    context=str(metrics.cyclomatic_complexity),
                    suggestion="Consider breaking the block into smaller, focused sub-blocks",
                )
            )

        return violations


@register_rule
class NestingDepthRule(Rule):
    """C002: Code nesting too deep.

    This rule checks that control structure nesting doesn't exceed
    a threshold, which would indicate overly complex logic.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="C002",
            name="nesting-depth",
            description=f"Code nesting depth should not exceed {NESTING_DEPTH_THRESHOLD}",
            severity=Severity.WARNING,
            category=RuleCategory.COMPLEXITY,
            rationale="Deeply nested code is hard to read and understand. "
            "Consider using early returns, guard clauses, or extracting "
            "nested logic into separate blocks.",
            examples_bad=["IF inside IF inside FOR inside CASE..."],
            examples_good=["Flat control flow with early exits"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check nesting depth.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Single violation if nesting exceeds threshold.
        """
        violations = []

        # Use higher threshold for organization blocks
        if block.block_type == "ORGANIZATION_BLOCK":
            threshold = NESTING_DEPTH_THRESHOLD_OB
        else:
            threshold = NESTING_DEPTH_THRESHOLD

        metrics = calculate_block_metrics(block)
        if metrics.max_nesting_depth > threshold:
            violations.append(
                self._create_violation(
                    message=f"Block '{block.name}' has nesting depth "
                    f"{metrics.max_nesting_depth} (threshold: {threshold})",
                    context=str(metrics.max_nesting_depth),
                    suggestion="Reduce nesting by using early returns or extracting sub-blocks",
                )
            )

        return violations


@register_rule
class BlockSizeRule(Rule):
    """C003: Block has too many lines.

    This rule checks that blocks don't exceed a line count threshold,
    suggesting they should be split into smaller units.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="C003",
            name="block-size",
            description=f"Block should not exceed {BLOCK_SIZE_THRESHOLD} lines of code",
            severity=Severity.INFO,
            category=RuleCategory.COMPLEXITY,
            rationale="Large blocks are harder to understand, test, and maintain. "
            "Consider splitting into smaller, focused blocks with clear responsibilities.",
            examples_bad=["1000-line function block"],
            examples_good=["Focused blocks under 500 lines"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check block size.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Single violation if block exceeds size threshold.
        """
        violations = []

        metrics = calculate_block_metrics(block)
        if metrics.code_lines > BLOCK_SIZE_THRESHOLD:
            violations.append(
                self._create_violation(
                    message=f"Block '{block.name}' has {metrics.code_lines} "
                    f"lines of code (threshold: {BLOCK_SIZE_THRESHOLD})",
                    context=str(metrics.code_lines),
                    suggestion="Consider splitting into smaller, focused blocks",
                )
            )

        return violations


@register_rule
class TooManyVariablesRule(Rule):
    """C004: Block has too many variables.

    This rule checks that blocks don't declare too many variables,
    which may indicate the block is doing too much.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="C004",
            name="too-many-variables",
            description=f"Block should not have more than {VARIABLE_COUNT_THRESHOLD} variables",
            severity=Severity.INFO,
            category=RuleCategory.COMPLEXITY,
            rationale="Many variables suggest the block has too many responsibilities. "
            "Consider splitting into smaller blocks or using structured data types.",
            examples_bad=["Block with 50+ local variables"],
            examples_good=["Block with focused variable set"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check variable count.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Single violation if variable count exceeds threshold.
        """
        violations = []

        metrics = calculate_block_metrics(block)
        if metrics.variable_count > VARIABLE_COUNT_THRESHOLD:
            violations.append(
                self._create_violation(
                    message=f"Block '{block.name}' has {metrics.variable_count} "
                    f"variables (threshold: {VARIABLE_COUNT_THRESHOLD})",
                    context=str(metrics.variable_count),
                    suggestion="Consider using UDTs to group related variables",
                )
            )

        return violations


@register_rule
class TooManyParametersRule(Rule):
    """C005: Function/FB has too many input parameters.

    This rule checks that blocks don't have too many input parameters,
    which makes them harder to use and test.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="C005",
            name="too-many-parameters",
            description=(f"Block should not have more than {PARAMETER_COUNT_THRESHOLD} input parameters"),
            severity=Severity.WARNING,
            category=RuleCategory.COMPLEXITY,
            rationale="Many parameters make blocks harder to call correctly and test. "
            "Consider grouping related parameters into UDTs.",
            examples_bad=["FB with 15 input parameters"],
            examples_good=["FB with focused parameter set or UDT inputs"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check input parameter count.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Single violation if parameter count exceeds threshold.
        """
        violations: list[Violation] = []

        # Only check function blocks and functions
        if block.block_type not in ("FUNCTION_BLOCK", "FUNCTION"):
            return violations

        input_count = len(block.inputs)
        if input_count > PARAMETER_COUNT_THRESHOLD:
            violations.append(
                self._create_violation(
                    message=f"Block '{block.name}' has {input_count} "
                    f"input parameters (threshold: {PARAMETER_COUNT_THRESHOLD})",
                    context=str(input_count),
                    suggestion="Consider grouping parameters into a UDT",
                )
            )

        return violations


__all__ = [
    "CyclomaticComplexityRule",
    "NestingDepthRule",
    "BlockSizeRule",
    "TooManyVariablesRule",
    "TooManyParametersRule",
    "CYCLOMATIC_COMPLEXITY_THRESHOLD",
    "NESTING_DEPTH_THRESHOLD",
    "BLOCK_SIZE_THRESHOLD",
    "VARIABLE_COUNT_THRESHOLD",
    "PARAMETER_COUNT_THRESHOLD",
]
