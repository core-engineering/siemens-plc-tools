"""Best practices rules for SCL code quality.

This module implements rules for detecting common anti-patterns
and enforcing best practices in SCL code.
"""

import re

from plc_code.analyzer.quality.models import RuleCategory, RuleInfo, Severity, Violation
from plc_code.analyzer.quality.rules import Rule, register_rule
from plc_code.parser.models import Block

# Pattern for magic numbers (numeric literals in code)
MAGIC_NUMBER_PATTERN = re.compile(
    r"(?<!:=\s)(?<!\[\s)(?<!\.\.)(?<!\d)"  # Not after := or [ or .. or digit
    r"(?<!#)(?<!MLC_)"  # Not after # or MLC_
    r"\b(\d+\.?\d*)\b"  # Number (int or float)
    r"(?!\s*\.\.)"  # Not before ..
    r"(?!\s*\])"  # Not before ]
    r"(?!\s*:)"  # Not before :
)

# Allowed magic numbers (commonly used values that don't need constants)
ALLOWED_MAGIC_NUMBERS = {"0", "1", "-1", "0.0", "1.0", "0.01", "0.1", "10", "100"}

# Pattern for hardcoded array indices
HARDCODED_INDEX_PATTERN = re.compile(r"\[\s*(\d+)\s*\]")

# Pattern for CASE without ELSE
CASE_WITHOUT_ELSE_PATTERN = re.compile(
    r"\bCASE\b.*?\bEND_CASE\b",
    re.IGNORECASE | re.DOTALL,
)
ELSE_IN_CASE_PATTERN = re.compile(r"\bELSE\b", re.IGNORECASE)


@register_rule
class MagicNumberRule(Rule):
    """B001: Magic numbers should be constants.

    This rule detects numeric literals in code that should be
    declared as named constants for clarity and maintainability.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="B001",
            name="magic-number",
            description="Numeric literals should be declared as named constants",
            severity=Severity.WARNING,
            category=RuleCategory.BEST_PRACTICES,
            rationale="Named constants make code more readable and easier to maintain. "
            "When a value needs to change, you only update it in one place.",
            examples_bad=["IF #counter > 42 THEN", "delay := 3600;"],
            examples_good=["IF #counter > MAX_RETRIES THEN", "delay := ONE_HOUR_SECONDS;"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check for magic numbers in code.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Violations for each magic number found.
        """
        violations = []

        # Gather all code content
        all_content = []
        for network in block.networks:
            for region in network.regions:
                # Skip Block info header and Description regions
                if region.name.lower() not in ("block info header", "description"):
                    all_content.append(region.content)

        content = "\n".join(all_content)

        # Find all numbers
        for match in MAGIC_NUMBER_PATTERN.finditer(content):
            number = match.group(1)
            if number not in ALLOWED_MAGIC_NUMBERS:
                violations.append(
                    self._create_violation(
                        message=f"Magic number '{number}' should be a named constant",
                        context=number,
                        suggestion="Declare as VAR CONSTANT with descriptive name",
                    )
                )

        return violations


def _collect_region_content(region: "Region") -> list[str]:
    """Recursively collect content from a region and its nested regions.

    Parameters
    ----------
    region : Region
        The region to collect content from.

    Returns
    -------
    list[str]
        List of content strings.
    """
    content = [region.content]
    for nested in region.nested_regions:
        content.extend(_collect_region_content(nested))
    return content


@register_rule
class UnusedVariableRule(Rule):
    """B002: Variable declared but never used.

    This rule detects variables that are declared but never referenced
    in the code, indicating dead code or incomplete implementation.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="B002",
            name="unused-variable",
            description="Variables should be used after declaration",
            severity=Severity.WARNING,
            category=RuleCategory.BEST_PRACTICES,
            rationale="Unused variables add clutter, increase memory usage, "
            "and may indicate incomplete code or logic errors.",
            examples_bad=["VAR temp : Int; END_VAR (temp never used)"],
            examples_good=["VAR temp : Int; END_VAR (temp used in logic)"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check for unused variables.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Violations for each unused variable found.
        """
        violations = []

        # Gather all code content to search for variable references
        # Must collect recursively from nested regions
        all_content = []
        for network in block.networks:
            all_content.append(network.content)
            for region in network.regions:
                all_content.extend(_collect_region_content(region))

        content = "\n".join(all_content)

        # Check each variable for usage
        for section in block.variable_sections:
            # Skip constants (they may be used for documentation/type safety)
            if section.is_constant or section.section_type == "VAR_CONSTANT":
                continue

            # Skip outputs (they're the purpose of the block)
            if section.section_type == "VAR_OUTPUT":
                continue

            for var in section.variables:
                # Search for variable usage (with # prefix for instance vars)
                # Note: SCL content may not have spaces between tokens,
                # so we check for the variable name directly (with optional # prefix)
                var_with_hash = f"#{var.name}"
                is_used = var_with_hash in content or var.name in content

                # If not found, variable is unused
                if not is_used:
                    violations.append(
                        self._create_violation(
                            message=f"Variable '{var.name}' is declared but never used",
                            context=var.name,
                            suggestion="Remove the variable or implement its usage",
                        )
                    )

        return violations


@register_rule
class HardcodedArrayIndexRule(Rule):
    """B003: Array accessed with hardcoded index.

    This rule detects array access with literal indices, which may
    indicate magic numbers or brittle code.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="B003",
            name="hardcoded-array-index",
            description="Array indices should use variables or constants",
            severity=Severity.INFO,
            category=RuleCategory.BEST_PRACTICES,
            rationale="Hardcoded indices are fragile and unclear. "
            "Use named constants or loop variables for clarity.",
            examples_bad=["arms[1].status", "data[42]"],
            examples_good=["arms[#armIndex].status", "data[FIRST_ELEMENT]"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check for hardcoded array indices.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Violations for each hardcoded index found.
        """
        violations = []

        # Gather all code content
        all_content = []
        for network in block.networks:
            for region in network.regions:
                if region.name.lower() not in ("block info header", "description"):
                    all_content.append(region.content)

        content = "\n".join(all_content)

        # Track found indices to avoid duplicate warnings
        found_indices: set[str] = set()

        for match in HARDCODED_INDEX_PATTERN.finditer(content):
            index = match.group(1)
            # Skip 1 (common for 1-based arrays in PLC)
            if index == "1":
                continue
            if index not in found_indices:
                found_indices.add(index)
                violations.append(
                    self._create_violation(
                        message=f"Hardcoded array index '{index}' - consider using a constant",
                        context=index,
                        suggestion="Use a named constant or loop variable",
                    )
                )

        return violations


@register_rule
class MissingDefaultCaseRule(Rule):
    """B004: CASE statement missing ELSE clause.

    This rule checks that CASE statements have an ELSE clause
    to handle unexpected values.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="B004",
            name="missing-default-case",
            description="CASE statements should have an ELSE clause",
            severity=Severity.WARNING,
            category=RuleCategory.BEST_PRACTICES,
            rationale="An ELSE clause handles unexpected values gracefully, "
            "preventing silent failures when state machines encounter "
            "undefined states.",
            examples_bad=["CASE #state OF 1: ...; 2: ...; END_CASE"],
            examples_good=["CASE #state OF 1: ...; ELSE ...; END_CASE"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check for CASE statements without ELSE.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Violations for each CASE without ELSE.
        """
        violations = []

        # Gather all code content
        all_content = []
        for network in block.networks:
            all_content.append(network.content)
            for region in network.regions:
                all_content.append(region.content)

        content = "\n".join(all_content)

        # Find all CASE blocks
        for match in CASE_WITHOUT_ELSE_PATTERN.finditer(content):
            case_block = match.group()
            if not ELSE_IN_CASE_PATTERN.search(case_block):
                violations.append(
                    self._create_violation(
                        message=f"Block '{block.name}' has CASE statement without ELSE clause",
                        context=block.name,
                        suggestion="Add an ELSE clause to handle unexpected values",
                    )
                )

        return violations


@register_rule
class EmptyRegionRule(Rule):
    """B005: REGION block is empty.

    This rule detects empty REGION blocks that add visual noise
    without providing organization value.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="B005",
            name="empty-region",
            description="REGION blocks should not be empty",
            severity=Severity.INFO,
            category=RuleCategory.BEST_PRACTICES,
            rationale="Empty REGIONs add visual noise without benefit. "
            "Either add content or remove the REGION.",
            examples_bad=["REGION Unused\\nEND_REGION"],
            examples_good=["REGION Process\\n(actual code)\\nEND_REGION"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check for empty REGION blocks.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Violations for each empty REGION.
        """
        violations = []

        def check_region(region: "Region", depth: int = 0) -> None:
            # Skip documentation regions
            if region.name.lower() in ("block info header", "description"):
                return

            # Check if region content is empty (accounting for nested regions)
            content = region.content.strip()
            has_nested = bool(region.nested_regions)

            if not content and not has_nested:
                violations.append(
                    self._create_violation(
                        message=f"REGION '{region.name}' is empty",
                        context=region.name,
                        suggestion="Add code to the region or remove it",
                    )
                )

            # Check nested regions recursively
            for nested in region.nested_regions:
                check_region(nested, depth + 1)

        for network in block.networks:
            for region in network.regions:
                check_region(region)

        return violations


@register_rule
class DeprecatedFunctionRule(Rule):
    """B006: Use of deprecated system function.

    This rule detects usage of deprecated or obsolete system functions
    that should be replaced with modern alternatives.
    """

    # Known deprecated functions and their replacements
    DEPRECATED_FUNCTIONS = {
        "ADD_TIME": "Use + operator instead",
        "SUB_TIME": "Use - operator instead",
        "CONCAT": "Consider using STRING operations",
    }

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="B006",
            name="deprecated-function",
            description="Deprecated functions should be replaced with modern alternatives",
            severity=Severity.WARNING,
            category=RuleCategory.BEST_PRACTICES,
            rationale="Deprecated functions may be removed in future versions. "
            "Use modern alternatives for better compatibility.",
            examples_bad=["result := ADD_TIME(t1, t2)"],
            examples_good=["result := t1 + t2"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check for deprecated function usage.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Violations for each deprecated function found.
        """
        violations = []

        # Gather all code content
        all_content = []
        for network in block.networks:
            all_content.append(network.content)
            for region in network.regions:
                all_content.append(region.content)

        content = "\n".join(all_content)

        for func, replacement in self.DEPRECATED_FUNCTIONS.items():
            pattern = re.compile(rf"\b{func}\b", re.IGNORECASE)
            if pattern.search(content):
                violations.append(
                    self._create_violation(
                        message=f"Deprecated function '{func}' used",
                        context=func,
                        suggestion=replacement,
                    )
                )

        return violations


# Import Region type for type hints
from plc_code.parser.models import Region  # noqa: E402

__all__ = [
    "MagicNumberRule",
    "UnusedVariableRule",
    "HardcodedArrayIndexRule",
    "MissingDefaultCaseRule",
    "EmptyRegionRule",
    "DeprecatedFunctionRule",
]
