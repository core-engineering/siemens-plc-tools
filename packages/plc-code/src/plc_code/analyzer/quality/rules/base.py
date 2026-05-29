"""Base classes for quality rules.

This module defines the abstract base class that all quality rules must implement,
providing a consistent interface for rule checking and metadata.
"""

from abc import ABC, abstractmethod

from plc_code.analyzer.quality.models import RuleInfo, Violation
from plc_code.parser.models import Block


class Rule(ABC):
    """Abstract base class for all quality rules.

    All rules must implement the `info` property to provide metadata
    and the `check` method to perform the actual analysis.

    Examples
    --------
    >>> class MyRule(Rule):
    ...     @property
    ...     def info(self) -> RuleInfo:
    ...         return RuleInfo(
    ...             code="X001",
    ...             name="my-rule",
    ...             description="My custom rule",
    ...             severity=Severity.WARNING,
    ...             category=RuleCategory.NAMING,
    ...         )
    ...
    ...     def check(self, block: Block) -> list[Violation]:
    ...         violations = []
    ...         # Perform checks...
    ...         return violations
    """

    @property
    @abstractmethod
    def info(self) -> RuleInfo:
        """Return rule metadata.

        Returns
        -------
        RuleInfo
            Metadata about this rule including code, name, description,
            severity, and category.
        """
        pass

    @abstractmethod
    def check(self, block: Block) -> list[Violation]:
        """Check a block for violations of this rule.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            List of violations found. Empty list if block is compliant.
        """
        pass

    def _create_violation(
        self,
        message: str,
        line_number: int = 0,
        column: int = 0,
        context: str = "",
        suggestion: str = "",
    ) -> Violation:
        """Helper to create a violation with rule info pre-filled.

        Parameters
        ----------
        message : str
            Human-readable description of the violation.
        line_number : int, optional
            Line number where violation occurs (default: 0).
        column : int, optional
            Column number (default: 0).
        context : str, optional
            Additional context (default: "").
        suggestion : str, optional
            Suggested fix or correction (default: "").

        Returns
        -------
        Violation
            A violation instance with rule code and severity from this rule.
        """
        return Violation(
            rule_code=self.info.code,
            message=message,
            severity=self.info.severity,
            line_number=line_number,
            column=column,
            context=context,
            suggestion=suggestion,
        )
