"""Naming convention rules for SCL code quality.

This module implements rules for enforcing naming conventions
on variables, blocks, constants, and types.

Naming Conventions
------------------
- Variables: camelCase (e.g., activeState, armIndex)
- Types (UDT): camelCase with 'type' prefix (e.g., typeUnitInput)
- Blocks: PascalCase (e.g., MotorStarter, ProcessController)
- Constants: SCREAMING_SNAKE_CASE (e.g., NO_ALARM, MAX_VALUE)
"""

import re

from plc_code.analyzer.quality.models import RuleCategory, RuleInfo, Severity, Violation
from plc_code.analyzer.quality.rules import Rule, register_rule
from plc_code.parser.models import Block

# Regex patterns for naming conventions
CAMEL_CASE_PATTERN = re.compile(r"^[a-z][a-zA-Z0-9]*$")
PASCAL_CASE_PATTERN = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
TYPE_PREFIX_PATTERN = re.compile(r"^type[A-Z][a-zA-Z0-9]*$")
SCREAMING_SNAKE_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")


def to_camel_case(name: str) -> str:
    """Convert a name to camelCase suggestion.

    Parameters
    ----------
    name : str
        Original name.

    Returns
    -------
    str
        Suggested camelCase version.
    """
    # Handle SCREAMING_SNAKE_CASE
    if "_" in name and name.isupper():
        parts = name.lower().split("_")
        return parts[0] + "".join(p.capitalize() for p in parts[1:])
    # Handle PascalCase
    if name and name[0].isupper():
        return name[0].lower() + name[1:]
    # Handle snake_case
    if "_" in name:
        parts = name.lower().split("_")
        return parts[0] + "".join(p.capitalize() for p in parts[1:])
    return name


def to_pascal_case(name: str) -> str:
    """Convert a name to PascalCase suggestion.

    Parameters
    ----------
    name : str
        Original name.

    Returns
    -------
    str
        Suggested PascalCase version.
    """
    # Handle snake_case or SCREAMING_SNAKE_CASE
    if "_" in name:
        parts = name.lower().split("_")
        return "".join(p.capitalize() for p in parts)
    # Handle camelCase
    if name and name[0].islower():
        return name[0].upper() + name[1:]
    return name


def to_screaming_snake(name: str) -> str:
    """Convert a name to SCREAMING_SNAKE_CASE suggestion.

    Parameters
    ----------
    name : str
        Original name.

    Returns
    -------
    str
        Suggested SCREAMING_SNAKE_CASE version.
    """
    # Insert underscore before uppercase letters (for camelCase/PascalCase)
    result = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    return result.upper()


@register_rule
class VariableCamelCaseRule(Rule):
    """N001: Variables must use camelCase.

    This rule checks that non-constant variables use camelCase naming,
    starting with a lowercase letter.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="N001",
            name="variable-camel-case",
            description="Variable names must use camelCase (starting with lowercase)",
            severity=Severity.WARNING,
            category=RuleCategory.NAMING,
            rationale="Consistent naming improves code readability and maintainability",
            examples_bad=["ActiveState", "active_state", "ACTIVESTATE"],
            examples_good=["activeState", "armIndex", "plcCycle"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check all non-constant variables for camelCase naming.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            List of violations for variables not using camelCase.
        """
        violations = []

        for section in block.variable_sections:
            # Skip constant sections - they have different naming rules
            if section.is_constant or section.section_type == "VAR_CONSTANT":
                continue

            for var in section.variables:
                if not CAMEL_CASE_PATTERN.match(var.name):
                    violations.append(
                        self._create_violation(
                            message=f"Variable '{var.name}' should use camelCase",
                            context=var.name,
                            suggestion=to_camel_case(var.name),
                        )
                    )

        return violations


@register_rule
class TypePrefixRule(Rule):
    """N002: UDT names must start with 'type' prefix and use camelCase.

    This rule ensures User Data Types follow the naming convention
    of starting with 'type' followed by PascalCase (e.g., typeUnitInput).
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="N002",
            name="type-prefix",
            description="User Data Type names must start with 'type' prefix (e.g., typeUnitInput)",
            severity=Severity.WARNING,
            category=RuleCategory.NAMING,
            rationale="Type prefix makes it easy to identify UDTs in code and prevents "
            "naming collisions with variables",
            examples_bad=["ArmInput", "armInput", "TYPE_ARM_INPUT"],
            examples_good=["typeUnitInput", "typeUnitStatus", "typeProcessData"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check TYPE blocks for proper naming convention.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            List of violations for improperly named types.
        """
        violations: list[Violation] = []

        # Only check TYPE blocks
        if block.block_type != "TYPE":
            return violations

        if not TYPE_PREFIX_PATTERN.match(block.name):
            suggested = block.name
            # Add 'type' prefix if missing
            if not block.name.lower().startswith("type"):
                suggested = "type" + to_pascal_case(block.name)
            else:
                # Fix casing if prefix exists but wrong case
                suggested = "type" + to_pascal_case(block.name[4:])

            violations.append(
                self._create_violation(
                    message=f"Type '{block.name}' should use 'type' prefix with camelCase",
                    context=block.name,
                    suggestion=suggested,
                )
            )

        return violations


@register_rule
class BlockPascalCaseRule(Rule):
    """N003: Function Blocks and Functions must use PascalCase.

    This rule ensures block names start with an uppercase letter
    and use PascalCase naming convention.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="N003",
            name="block-pascal-case",
            description="Function Block and Function names must use PascalCase",
            severity=Severity.WARNING,
            category=RuleCategory.NAMING,
            rationale="PascalCase for blocks distinguishes them from variables and "
            "follows common programming conventions",
            examples_bad=["pumpControl", "pump_control", "PUMP_CONTROL"],
            examples_good=["MotorStarter", "ProcessController", "SafetyMonitor"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check block name for PascalCase.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            List of violations if block name doesn't use PascalCase.
        """
        violations: list[Violation] = []

        # Only check FUNCTION and FUNCTION_BLOCK
        if block.block_type not in ("FUNCTION", "FUNCTION_BLOCK"):
            return violations

        if not PASCAL_CASE_PATTERN.match(block.name):
            violations.append(
                self._create_violation(
                    message=f"Block '{block.name}' should use PascalCase",
                    context=block.name,
                    suggestion=to_pascal_case(block.name),
                )
            )

        return violations


@register_rule
class ConstantScreamingSnakeRule(Rule):
    """N004: Constants must use SCREAMING_SNAKE_CASE.

    This rule ensures constant variables are named using all uppercase
    letters with underscores separating words.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="N004",
            name="constant-screaming-snake",
            description="Constants must use SCREAMING_SNAKE_CASE",
            severity=Severity.WARNING,
            category=RuleCategory.NAMING,
            rationale="SCREAMING_SNAKE_CASE makes constants visually distinct "
            "and immediately recognizable in code",
            examples_bad=["noAlarm", "NoAlarm", "no_alarm"],
            examples_good=["NO_ALARM", "MAX_VALUE", "ALARM_ACKNOWLEDGE"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check constant variables for SCREAMING_SNAKE_CASE naming.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            List of violations for constants not using SCREAMING_SNAKE_CASE.
        """
        violations = []

        for section in block.variable_sections:
            # Only check constant sections
            if not (section.is_constant or section.section_type == "VAR_CONSTANT"):
                continue

            for var in section.variables:
                if not SCREAMING_SNAKE_PATTERN.match(var.name):
                    violations.append(
                        self._create_violation(
                            message=f"Constant '{var.name}' should use SCREAMING_SNAKE_CASE",
                            context=var.name,
                            suggestion=to_screaming_snake(var.name),
                        )
                    )

        return violations


@register_rule
class InstanceCamelCaseRule(Rule):
    """N005: Instance variable names must use camelCase.

    This rule specifically checks static instance variables (VAR section)
    that reference other function blocks, ensuring they use camelCase.
    """

    @property
    def info(self) -> RuleInfo:
        """Return rule metadata."""
        return RuleInfo(
            code="N005",
            name="instance-camel-case",
            description="Instance variable names (function block instances) must use camelCase",
            severity=Severity.WARNING,
            category=RuleCategory.NAMING,
            rationale="Instance variables should follow the same camelCase convention "
            "as regular variables for consistency",
            examples_bad=["MyBlock", "my_block", "MY_BLOCK"],
            examples_good=["controller", "safetyMonitor", "retractionTimer"],
        )

    def check(self, block: Block) -> list[Violation]:
        """Check instance variables in VAR section for camelCase.

        Parameters
        ----------
        block : Block
            The parsed block to check.

        Returns
        -------
        list[Violation]
            List of violations for instance variables not using camelCase.
        """
        violations = []

        # Instance variables are typically in VAR (static) section
        for section in block.variable_sections:
            if section.section_type != "VAR":
                continue

            for var in section.variables:
                # Check if this looks like a function block instance
                # (type starts with uppercase or is a library type like _.TypeName)
                is_fb_instance = (
                    var.data_type
                    and (
                        var.data_type[0].isupper()
                        or var.data_type.startswith("_.")
                        or "Array" in var.data_type
                    )
                    # Exclude primitive types
                    and var.data_type
                    not in (
                        "Bool",
                        "Int",
                        "UInt",
                        "SInt",
                        "USInt",
                        "DInt",
                        "UDInt",
                        "LInt",
                        "ULInt",
                        "Real",
                        "LReal",
                        "String",
                        "WString",
                        "Char",
                        "WChar",
                        "Byte",
                        "Word",
                        "DWord",
                        "LWord",
                        "Time",
                        "Date",
                        "Date_And_Time",
                        "Time_Of_Day",
                    )
                )

                if is_fb_instance and not CAMEL_CASE_PATTERN.match(var.name):
                    violations.append(
                        self._create_violation(
                            message=f"Instance '{var.name}' should use camelCase",
                            context=var.name,
                            suggestion=to_camel_case(var.name),
                        )
                    )

        return violations


__all__ = [
    "VariableCamelCaseRule",
    "TypePrefixRule",
    "BlockPascalCaseRule",
    "ConstantScreamingSnakeRule",
    "InstanceCamelCaseRule",
    "CAMEL_CASE_PATTERN",
    "PASCAL_CASE_PATTERN",
    "TYPE_PREFIX_PATTERN",
    "SCREAMING_SNAKE_PATTERN",
    "to_camel_case",
    "to_pascal_case",
    "to_screaming_snake",
]
