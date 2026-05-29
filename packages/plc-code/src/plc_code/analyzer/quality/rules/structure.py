"""Structure rules for SCL code quality.

This module implements rules for checking code structure integrity,
ensuring balanced constructs and proper organization.
"""

import re

from plc_code.analyzer.quality.models import RuleCategory, RuleInfo, Severity, Violation
from plc_code.analyzer.quality.rules import Rule, register_rule
from plc_code.parser.models import Block

# Patterns for structure checks
REGION_OPEN = re.compile(r"\bREGION\b", re.IGNORECASE)
REGION_CLOSE = re.compile(r"\bEND_REGION\b", re.IGNORECASE)

IF_OPEN = re.compile(r"\bIF\b", re.IGNORECASE)
IF_CLOSE = re.compile(r"\bEND_IF\b", re.IGNORECASE)

CASE_OPEN = re.compile(r"\bCASE\b", re.IGNORECASE)
CASE_CLOSE = re.compile(r"\bEND_CASE\b", re.IGNORECASE)

FOR_OPEN = re.compile(r"\bFOR\b", re.IGNORECASE)
FOR_CLOSE = re.compile(r"\bEND_FOR\b", re.IGNORECASE)

WHILE_OPEN = re.compile(r"\bWHILE\b", re.IGNORECASE)
WHILE_CLOSE = re.compile(r"\bEND_WHILE\b", re.IGNORECASE)

# Patterns to strip comments before counting
BLOCK_COMMENT = re.compile(r"\(\*.*?\*\)", re.DOTALL)
LINE_COMMENT = re.compile(r"//[^\n]*")


def _strip_comments(content: str) -> str:
    """Remove comments from content before analysis.

    Parameters
    ----------
    content : str
        The content to process.

    Returns
    -------
    str
        Content with block comments (* *) and line comments (//) removed.
    """
    # Remove block comments first (may span multiple lines)
    content = BLOCK_COMMENT.sub("", content)
    # Remove line comments
    content = LINE_COMMENT.sub("", content)
    return content


def _count_matches(pattern: re.Pattern[str], content: str) -> int:
    """Count pattern matches in content."""
    return len(pattern.findall(content))


@register_rule
class UnbalancedRegionRule(Rule):
    """S001: Missing END_REGION for REGION.

    This rule checks that every REGION has a matching END_REGION.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="S001",
            name="unbalanced-region",
            description="Every REGION must have a matching END_REGION",
            severity=Severity.ERROR,
            category=RuleCategory.STRUCTURE,
            rationale="Unbalanced REGION blocks cause syntax errors and "
            "indicate incomplete or corrupted code.",
            examples_bad=["REGION Process\\n(code without END_REGION)"],
            examples_good=["REGION Process\\n(code)\\nEND_REGION"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check for balanced REGION/END_REGION.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Single violation if regions are unbalanced.
        """
        violations = []

        # Gather all content
        all_content = []
        for network in block.networks:
            all_content.append(network.content)
            for region in network.regions:
                all_content.append(region.content)

        content = "\n".join(all_content)

        # Strip comments before counting to avoid false positives
        content = _strip_comments(content)

        opens = _count_matches(REGION_OPEN, content)
        closes = _count_matches(REGION_CLOSE, content)

        if opens != closes:
            diff = opens - closes
            if diff > 0:
                violations.append(
                    self._create_violation(
                        message=f"Block '{block.name}' has {diff} unclosed REGION(s)",
                        context=str(diff),
                        suggestion="Add missing END_REGION statement(s)",
                    )
                )
            else:
                violations.append(
                    self._create_violation(
                        message=f"Block '{block.name}' has {-diff} extra END_REGION(s)",
                        context=str(-diff),
                        suggestion="Remove extra END_REGION statement(s)",
                    )
                )

        return violations


@register_rule
class UnbalancedIfRule(Rule):
    """S002: Missing END_IF for IF.

    This rule checks that every IF has a matching END_IF.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="S002",
            name="unbalanced-if",
            description="Every IF must have a matching END_IF",
            severity=Severity.ERROR,
            category=RuleCategory.STRUCTURE,
            rationale="Unbalanced IF statements cause syntax errors.",
            examples_bad=["IF condition THEN\\n(code without END_IF)"],
            examples_good=["IF condition THEN\\n(code)\\nEND_IF"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check for balanced IF/END_IF.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Single violation if IFs are unbalanced.
        """
        violations = []

        # Gather all content
        all_content = []
        for network in block.networks:
            all_content.append(network.content)
            for region in network.regions:
                all_content.append(region.content)

        content = "\n".join(all_content)

        # Strip comments before counting to avoid false positives
        content = _strip_comments(content)

        opens = _count_matches(IF_OPEN, content)
        closes = _count_matches(IF_CLOSE, content)

        if opens != closes:
            diff = opens - closes
            if diff > 0:
                violations.append(
                    self._create_violation(
                        message=f"Block '{block.name}' has {diff} unclosed IF statement(s)",
                        context=str(diff),
                        suggestion="Add missing END_IF statement(s)",
                    )
                )
            else:
                violations.append(
                    self._create_violation(
                        message=f"Block '{block.name}' has {-diff} extra END_IF statement(s)",
                        context=str(-diff),
                        suggestion="Remove extra END_IF statement(s)",
                    )
                )

        return violations


@register_rule
class UnbalancedCaseRule(Rule):
    """S003: Missing END_CASE for CASE.

    This rule checks that every CASE has a matching END_CASE.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="S003",
            name="unbalanced-case",
            description="Every CASE must have a matching END_CASE",
            severity=Severity.ERROR,
            category=RuleCategory.STRUCTURE,
            rationale="Unbalanced CASE statements cause syntax errors.",
            examples_bad=["CASE #state OF\\n(branches without END_CASE)"],
            examples_good=["CASE #state OF\\n(branches)\\nEND_CASE"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check for balanced CASE/END_CASE.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Single violation if CASEs are unbalanced.
        """
        violations = []

        # Gather all content
        all_content = []
        for network in block.networks:
            all_content.append(network.content)
            for region in network.regions:
                all_content.append(region.content)

        content = "\n".join(all_content)

        # Strip comments before counting to avoid false positives
        content = _strip_comments(content)

        opens = _count_matches(CASE_OPEN, content)
        closes = _count_matches(CASE_CLOSE, content)

        if opens != closes:
            diff = opens - closes
            if diff > 0:
                violations.append(
                    self._create_violation(
                        message=f"Block '{block.name}' has {diff} unclosed CASE statement(s)",
                        context=str(diff),
                        suggestion="Add missing END_CASE statement(s)",
                    )
                )
            else:
                violations.append(
                    self._create_violation(
                        message=f"Block '{block.name}' has {-diff} extra END_CASE statement(s)",
                        context=str(-diff),
                        suggestion="Remove extra END_CASE statement(s)",
                    )
                )

        return violations


@register_rule
class MissingNetworkRule(Rule):
    """S004: Block missing NETWORK section.

    This rule checks that blocks have at least one NETWORK section
    containing executable code.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="S004",
            name="missing-network",
            description="Block should have at least one NETWORK section",
            severity=Severity.WARNING,
            category=RuleCategory.STRUCTURE,
            rationale="NETWORK sections contain the executable code. "
            "A block without networks has no logic.",
            examples_bad=["FUNCTION_BLOCK without NETWORK"],
            examples_good=["FUNCTION_BLOCK with NETWORK containing code"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check for presence of NETWORK section.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Single violation if no networks present.
        """
        violations: list[Violation] = []

        # TYPE blocks don't need networks
        if block.block_type == "TYPE":
            return violations

        if not block.networks:
            violations.append(
                self._create_violation(
                    message=f"Block '{block.name}' has no NETWORK section",
                    context=block.name,
                    suggestion="Add a NETWORK section with executable code",
                )
            )

        return violations


@register_rule
class EmptyVarSectionRule(Rule):
    """S005: Variable section is empty.

    This rule detects variable sections that are declared but
    contain no variables.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="S005",
            name="empty-var-section",
            description="Variable sections should not be empty",
            severity=Severity.INFO,
            category=RuleCategory.STRUCTURE,
            rationale="Empty variable sections add clutter. " "Remove them if not needed.",
            examples_bad=["VAR_INPUT\\nEND_VAR (with no variables)"],
            examples_good=["VAR_INPUT\\ninput1 : Bool;\\nEND_VAR"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check for empty variable sections.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            Violations for each empty variable section.
        """
        violations = []

        for section in block.variable_sections:
            if not section.variables:
                violations.append(
                    self._create_violation(
                        message=f"Block '{block.name}' has empty {section.section_type} section",
                        context=section.section_type,
                        suggestion="Add variables or remove the section",
                    )
                )

        return violations


__all__ = [
    "UnbalancedRegionRule",
    "UnbalancedIfRule",
    "UnbalancedCaseRule",
    "MissingNetworkRule",
    "EmptyVarSectionRule",
]
