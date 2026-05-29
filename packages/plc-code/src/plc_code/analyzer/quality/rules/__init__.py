"""Rule registry and exports for quality rules.

This module provides the central registry of all available quality rules
and exports for convenient importing.

Examples
--------
>>> from plc_code.analyzer.quality.rules import ALL_RULES, get_all_rules
>>>
>>> # Get all rule classes
>>> rules = get_all_rules()
>>>
>>> # Instantiate and use
>>> for rule_class in rules:
...     rule = rule_class()
...     print(f"{rule.info.code}: {rule.info.name}")
"""

from typing import TYPE_CHECKING

from plc_code.analyzer.quality.rules.base import Rule

if TYPE_CHECKING:
    pass

# Rule registry - populated as rules are implemented
# Each entry is a Rule subclass (not instance)
ALL_RULES: list[type[Rule]] = []


def get_all_rules() -> list[type[Rule]]:
    """Get all registered rule classes.

    Returns
    -------
    list[type[Rule]]
        List of all rule classes.
    """
    return ALL_RULES.copy()


def register_rule(rule_class: type[Rule]) -> type[Rule]:
    """Decorator to register a rule class.

    Parameters
    ----------
    rule_class : type[Rule]
        The rule class to register.

    Returns
    -------
    type[Rule]
        The same rule class (for decorator chaining).

    Examples
    --------
    >>> @register_rule
    ... class MyRule(Rule):
    ...     pass
    """
    ALL_RULES.append(rule_class)
    return rule_class


# Import rule modules to register them
# Each module uses @register_rule decorator to add rules to ALL_RULES
from plc_code.analyzer.quality.rules import (  # noqa: E402
    best_practices,  # noqa: F401
    complexity,  # noqa: F401
    documentation,  # noqa: F401
    naming,  # noqa: F401
    structure,  # noqa: F401
)

__all__ = [
    "Rule",
    "ALL_RULES",
    "get_all_rules",
    "register_rule",
]
