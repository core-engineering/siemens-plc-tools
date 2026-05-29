"""Tests for naming convention rules (N001-N005)."""

from typing import Literal

from plc_code.analyzer.quality.models import Severity
from plc_code.analyzer.quality.rules.naming import (
    BlockPascalCaseRule,
    ConstantScreamingSnakeRule,
    InstanceCamelCaseRule,
    TypePrefixRule,
    VariableCamelCaseRule,
)
from plc_code.parser.models import Block, VariableDeclaration, VariableSection

BlockType = Literal["FUNCTION_BLOCK", "FUNCTION", "TYPE"]
SectionType = Literal["VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR", "VAR_TEMP", "VAR_CONSTANT"]


def make_block(
    name: str = "TestBlock",
    block_type: BlockType = "FUNCTION_BLOCK",
    variables: list[tuple[str, str, SectionType]] | None = None,
) -> Block:
    """Create a test block with variable sections.

    Parameters
    ----------
    name : str
        Block name.
    block_type : str
        Block type.
    variables : list[tuple[str, str, str]] | None
        List of (name, type, section_type) tuples.
    """
    block = Block(name=name, block_type=block_type)

    if variables:
        # Group by section type
        sections: dict[SectionType, list[VariableDeclaration]] = {}
        for var_name, var_type, section_type in variables:
            if section_type not in sections:
                sections[section_type] = []
            sections[section_type].append(VariableDeclaration(name=var_name, data_type=var_type))

        for sec_type, vars in sections.items():
            is_constant = sec_type == "VAR_CONSTANT"
            block.variable_sections.append(
                VariableSection(
                    section_type=sec_type,
                    is_constant=is_constant,
                    variables=vars,
                )
            )

    return block


class TestVariableCamelCaseRule:
    """Tests for N001: Variable camelCase rule."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.rule = VariableCamelCaseRule()

    def test_rule_info(self) -> None:
        """Test rule metadata."""
        info = self.rule.info
        assert info.code == "N001"
        assert info.name == "variable-camel-case"
        assert info.severity == Severity.WARNING

    def test_valid_camel_case(self) -> None:
        """Test valid camelCase variable names."""
        block = make_block(
            variables=[
                ("activeState", "Int", "VAR"),
                ("counter", "Int", "VAR"),
                ("armIndex", "Int", "VAR"),
                ("myLongVariableName", "Bool", "VAR"),
            ]
        )
        violations = self.rule.check(block)
        assert len(violations) == 0

    def test_invalid_pascal_case(self) -> None:
        """Test PascalCase triggers violation."""
        block = make_block(
            variables=[
                ("ActiveState", "Int", "VAR"),
            ]
        )
        violations = self.rule.check(block)
        assert len(violations) == 1
        assert "ActiveState" in violations[0].message
        assert "camelcase" in violations[0].message.lower()

    def test_invalid_snake_case(self) -> None:
        """Test snake_case triggers violation."""
        block = make_block(
            variables=[
                ("active_state", "Int", "VAR"),
            ]
        )
        violations = self.rule.check(block)
        assert len(violations) == 1

    def test_skips_constants(self) -> None:
        """Test that constant sections are skipped."""
        block = make_block(
            variables=[
                ("MAX_VALUE", "Int", "VAR_CONSTANT"),
            ]
        )
        violations = self.rule.check(block)
        assert len(violations) == 0


class TestTypePrefixRule:
    """Tests for N002: Type prefix rule."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.rule = TypePrefixRule()

    def test_rule_info(self) -> None:
        """Test rule metadata."""
        info = self.rule.info
        assert info.code == "N002"
        assert info.name == "type-prefix"
        assert info.severity == Severity.WARNING

    def test_valid_type_name(self) -> None:
        """Test valid type names with 'type' prefix."""
        block = make_block(name="typeUnitInput", block_type="TYPE")
        violations = self.rule.check(block)
        assert len(violations) == 0

    def test_valid_type_name_long(self) -> None:
        """Test valid type name with longer suffix."""
        block = make_block(name="typeMyComplexStructure", block_type="TYPE")
        violations = self.rule.check(block)
        assert len(violations) == 0

    def test_invalid_missing_prefix(self) -> None:
        """Test type without 'type' prefix."""
        block = make_block(name="ArmInput", block_type="TYPE")
        violations = self.rule.check(block)
        assert len(violations) == 1
        assert "type" in violations[0].suggestion.lower()

    def test_skips_non_types(self) -> None:
        """Test that non-TYPE blocks are skipped."""
        block = make_block(name="SomeBlock", block_type="FUNCTION_BLOCK")
        violations = self.rule.check(block)
        assert len(violations) == 0


class TestBlockPascalCaseRule:
    """Tests for N003: Block PascalCase rule."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.rule = BlockPascalCaseRule()

    def test_rule_info(self) -> None:
        """Test rule metadata."""
        info = self.rule.info
        assert info.code == "N003"
        assert info.name == "block-pascal-case"
        assert info.severity == Severity.WARNING

    def test_valid_pascal_case(self) -> None:
        """Test valid PascalCase block names."""
        block = make_block(name="MotorStarter", block_type="FUNCTION_BLOCK")
        violations = self.rule.check(block)
        assert len(violations) == 0

    def test_invalid_camel_case(self) -> None:
        """Test camelCase triggers violation."""
        block = make_block(name="motorStarter", block_type="FUNCTION_BLOCK")
        violations = self.rule.check(block)
        assert len(violations) == 1
        assert "PascalCase" in violations[0].message

    def test_invalid_snake_case(self) -> None:
        """Test snake_case triggers violation."""
        block = make_block(name="acknowledge_alarm", block_type="FUNCTION_BLOCK")
        violations = self.rule.check(block)
        assert len(violations) == 1

    def test_skips_types(self) -> None:
        """Test that TYPE blocks are skipped (checked by N002)."""
        block = make_block(name="myType", block_type="TYPE")
        violations = self.rule.check(block)
        assert len(violations) == 0


class TestConstantScreamingSnakeRule:
    """Tests for N004: Constant SCREAMING_SNAKE_CASE rule."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.rule = ConstantScreamingSnakeRule()

    def test_rule_info(self) -> None:
        """Test rule metadata."""
        info = self.rule.info
        assert info.code == "N004"
        assert info.name == "constant-screaming-snake"
        assert info.severity == Severity.WARNING

    def test_valid_screaming_snake(self) -> None:
        """Test valid SCREAMING_SNAKE_CASE constants."""
        block = make_block(
            variables=[
                ("MAX_VALUE", "Int", "VAR_CONSTANT"),
                ("NO_ALARM", "Int", "VAR_CONSTANT"),
                ("API_TIMEOUT_MS", "Int", "VAR_CONSTANT"),
            ]
        )
        violations = self.rule.check(block)
        assert len(violations) == 0

    def test_invalid_camel_case_constant(self) -> None:
        """Test camelCase constant triggers violation."""
        block = make_block(
            variables=[
                ("maxValue", "Int", "VAR_CONSTANT"),
            ]
        )
        violations = self.rule.check(block)
        assert len(violations) == 1
        assert "SCREAMING_SNAKE_CASE" in violations[0].message

    def test_skips_non_constants(self) -> None:
        """Test that non-constant sections are skipped."""
        block = make_block(
            variables=[
                ("myVariable", "Int", "VAR"),
            ]
        )
        violations = self.rule.check(block)
        assert len(violations) == 0


class TestInstanceCamelCaseRule:
    """Tests for N005: Instance camelCase rule (FB instances in VAR section)."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.rule = InstanceCamelCaseRule()

    def test_rule_info(self) -> None:
        """Test rule metadata."""
        info = self.rule.info
        assert info.code == "N005"
        assert info.name == "instance-camel-case"
        assert info.severity == Severity.WARNING

    def test_valid_camel_case_instance(self) -> None:
        """Test valid camelCase FB instance names."""
        block = make_block(
            variables=[
                ("pumpControl", "PumpControl", "VAR"),
                ("safetyMonitor", "SafetyMonitor", "VAR"),
            ]
        )
        violations = self.rule.check(block)
        assert len(violations) == 0

    def test_invalid_pascal_case_instance(self) -> None:
        """Test PascalCase FB instance triggers violation."""
        block = make_block(
            variables=[
                ("PumpControl", "PumpControl", "VAR"),  # FB instance with wrong naming
            ]
        )
        violations = self.rule.check(block)
        assert len(violations) == 1
        assert "PumpControl" in violations[0].message

    def test_skips_primitive_types(self) -> None:
        """Test that primitive type variables are skipped (checked by N001)."""
        block = make_block(
            variables=[
                ("ActiveState", "Int", "VAR"),
            ]
        )
        violations = self.rule.check(block)
        # N005 only checks FB instances, not primitive types
        assert len(violations) == 0

    def test_skips_non_var_sections(self) -> None:
        """Test that VAR_INPUT/OUTPUT sections are skipped."""
        block = make_block(
            variables=[
                ("PumpControl", "PumpControl", "VAR_INPUT"),
            ]
        )
        violations = self.rule.check(block)
        # N005 only checks VAR section
        assert len(violations) == 0
