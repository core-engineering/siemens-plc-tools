"""Tests for UDT generation and compilation."""

from pathlib import Path

import pytest

from plc_code.executor.udt import (
    UDTGenerationResult,
    UDTGenerator,
    UDTRegistry,
    compile_udt,
    compile_udt_directory,
    generate_udt,
)
from plc_code.parser import parse_scl_file
from plc_code.parser.models import Block, StructField, UserDataType

# Test fixtures directory
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
DATA_TYPES_DIR = Path("program-listings/PLC data types")


class TestUDTGenerationResult:
    """Tests for UDTGenerationResult dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        result = UDTGenerationResult(
            success=True,
            python_code="class Test: pass",
            class_name="Test",
        )
        assert result.dependencies == []
        assert result.errors == []

    def test_with_dependencies(self) -> None:
        """Test with dependencies."""
        result = UDTGenerationResult(
            success=True,
            python_code="class Test: pass",
            class_name="Test",
            dependencies=["TypeA", "TypeB"],
        )
        assert result.dependencies == ["TypeA", "TypeB"]


class TestUDTGenerator:
    """Tests for UDTGenerator class."""

    def test_generate_simple_udt(self) -> None:
        """Test generating a simple UDT."""
        udt = UserDataType(
            name="SimpleType",
            fields=[
                StructField(name="flag", data_type="Bool"),
                StructField(name="count", data_type="Int"),
                StructField(name="value", data_type="Real"),
            ],
        )

        block = Block(
            name="SimpleType",
            block_type="TYPE",
            user_data_type=udt,
        )

        generator = UDTGenerator()
        result = generator.generate(block)

        assert result.success
        assert result.class_name == "SimpleType"
        assert "class SimpleType:" in result.python_code
        assert "flag: bool = False" in result.python_code
        assert "count: int = 0" in result.python_code
        assert "value: float = 0.0" in result.python_code

    def test_generate_udt_with_nested_type(self) -> None:
        """Test generating UDT with nested type reference."""
        udt = UserDataType(
            name="ParentType",
            fields=[
                StructField(name="child", data_type="_.ChildType"),
            ],
        )

        block = Block(
            name="ParentType",
            block_type="TYPE",
            user_data_type=udt,
        )

        generator = UDTGenerator()
        result = generator.generate(block)

        assert result.success
        assert "ChildType" in result.dependencies
        assert "child: ChildType = field(default_factory=ChildType)" in result.python_code

    def test_generate_udt_with_array(self) -> None:
        """Test generating UDT with array field."""
        udt = UserDataType(
            name="ArrayType",
            fields=[
                StructField(name="values", data_type="Array[0..9] of Real"),
            ],
        )

        block = Block(
            name="ArrayType",
            block_type="TYPE",
            user_data_type=udt,
        )

        generator = UDTGenerator()
        result = generator.generate(block)

        assert result.success
        assert "list[float]" in result.python_code

    def test_generate_non_type_block_fails(self) -> None:
        """Test that generating from non-TYPE block fails."""
        block = Block(
            name="SomeBlock",
            block_type="FUNCTION_BLOCK",
        )

        generator = UDTGenerator()
        result = generator.generate(block)

        assert not result.success
        assert "not a TYPE block" in result.errors[0]

    def test_generate_empty_udt(self) -> None:
        """Test generating UDT with no fields."""
        udt = UserDataType(name="EmptyType", fields=[])

        block = Block(
            name="EmptyType",
            block_type="TYPE",
            user_data_type=udt,
        )

        generator = UDTGenerator()
        result = generator.generate(block)

        assert result.success
        assert "pass" in result.python_code


class TestUDTCompilation:
    """Tests for UDT compilation."""

    def test_compile_simple_udt(self) -> None:
        """Test compiling a simple UDT."""
        udt = UserDataType(
            name="TestUDT",
            fields=[
                StructField(name="active", data_type="Bool"),
                StructField(name="value", data_type="Int"),
            ],
        )

        block = Block(
            name="TestUDT",
            block_type="TYPE",
            user_data_type=udt,
        )

        result = compile_udt(block)

        assert result.success
        assert result.udt_class is not None

        # Create instance and verify defaults
        instance = result.udt_class()
        assert instance.active is False
        assert instance.value == 0

    def test_compile_udt_with_registry(self) -> None:
        """Test compiling UDT with dependency from registry."""
        # First compile child type
        child_udt = UserDataType(
            name="ChildUDT",
            fields=[StructField(name="data", data_type="Int")],
        )
        child_block = Block(
            name="ChildUDT",
            block_type="TYPE",
            user_data_type=child_udt,
        )
        child_result = compile_udt(child_block)
        assert child_result.success
        assert child_result.udt_class is not None

        # Create registry with child
        registry = UDTRegistry()
        registry.register("ChildUDT", child_result.udt_class)

        # Now compile parent that references child
        parent_udt = UserDataType(
            name="ParentUDT",
            fields=[StructField(name="child", data_type="_.ChildUDT")],
        )
        parent_block = Block(
            name="ParentUDT",
            block_type="TYPE",
            user_data_type=parent_udt,
        )

        parent_result = compile_udt(parent_block, registry=registry)

        assert parent_result.success
        assert parent_result.udt_class is not None

        # Create instance and verify nested structure
        instance = parent_result.udt_class()
        assert hasattr(instance, "child")
        assert instance.child.data == 0

    def test_compile_fails_missing_dependency(self) -> None:
        """Test that compilation fails with missing dependency."""
        udt = UserDataType(
            name="DepType",
            fields=[StructField(name="ref", data_type="_.NonExistent")],
        )
        block = Block(
            name="DepType",
            block_type="TYPE",
            user_data_type=udt,
        )

        result = compile_udt(block)

        assert not result.success
        assert "NonExistent" in str(result.compile_error)


class TestUDTRegistry:
    """Tests for UDTRegistry class."""

    def test_register_and_get(self) -> None:
        """Test registering and retrieving types."""
        registry = UDTRegistry()

        # Create a simple class
        from dataclasses import dataclass

        @dataclass
        class TestType:
            value: int = 0

        registry.register("TestType", TestType)

        assert registry.has("TestType")
        assert registry.get("TestType") is TestType

    def test_get_with_prefix(self) -> None:
        """Test getting type with _.prefix."""
        registry = UDTRegistry()

        from dataclasses import dataclass

        @dataclass
        class MyType:
            pass

        registry.register("MyType", MyType)

        assert registry.get("_.MyType") is MyType

    def test_create_instance(self) -> None:
        """Test creating instance from registry."""
        registry = UDTRegistry()

        from dataclasses import dataclass

        @dataclass
        class InstanceType:
            x: int = 42

        registry.register("InstanceType", InstanceType)

        instance = registry.create_instance("InstanceType")
        assert instance.x == 42

    def test_create_instance_not_found(self) -> None:
        """Test creating instance for unknown type raises error."""
        registry = UDTRegistry()

        with pytest.raises(KeyError):
            registry.create_instance("Unknown")

    def test_compile_pending(self) -> None:
        """Test compiling pending blocks."""
        registry = UDTRegistry()

        # Create simple UDT block
        udt = UserDataType(
            name="PendingType",
            fields=[StructField(name="val", data_type="Bool")],
        )
        block = Block(
            name="PendingType",
            block_type="TYPE",
            user_data_type=udt,
        )

        registry.add_pending("PendingType", block)
        errors = registry.compile_pending()

        assert len(errors) == 0
        assert registry.has("PendingType")


class TestRealUDTFiles:
    """Integration tests with real UDT files."""

    @pytest.fixture
    def arm_input_path(self) -> Path:
        """Path to typeUnitInput.s7dcl."""
        path = DATA_TYPES_DIR / "10 - Data" / "typeUnitInput.s7dcl"
        if not path.exists():
            pytest.skip("typeUnitInput.s7dcl not found")
        return path

    @pytest.fixture
    def arm_data_path(self) -> Path:
        """Path to typeUnitData.s7dcl."""
        path = DATA_TYPES_DIR / "10 - Data" / "typeUnitData.s7dcl"
        if not path.exists():
            pytest.skip("typeUnitData.s7dcl not found")
        return path

    def test_generate_arm_input(self, arm_input_path: Path) -> None:
        """Test generating typeUnitInput."""
        block = parse_scl_file(arm_input_path)
        result = generate_udt(block)

        assert result.success
        assert result.class_name == "typeUnitInput"
        assert "percCollarSwitch: bool" in result.python_code
        assert len(result.dependencies) == 0  # No UDT dependencies

    def test_compile_arm_input(self, arm_input_path: Path) -> None:
        """Test compiling typeUnitInput."""
        block = parse_scl_file(arm_input_path)
        result = compile_udt(block)

        assert result.success
        assert result.udt_class is not None

        # Create instance
        instance = result.udt_class()
        assert hasattr(instance, "percCollarSwitch")
        assert instance.percCollarSwitch is False

    def test_generate_arm_data_shows_dependencies(self, arm_data_path: Path) -> None:
        """Test that typeUnitData shows its dependencies."""
        block = parse_scl_file(arm_data_path)
        result = generate_udt(block)

        assert result.success
        assert "typeUnitInput" in result.dependencies
        assert "typeUnitStatus" in result.dependencies


class TestCompileUDTDirectory:
    """Tests for compile_udt_directory function."""

    def test_compile_data_directory(self) -> None:
        """Test compiling all UDTs in data directory."""
        data_dir = DATA_TYPES_DIR / "10 - Data"
        if not data_dir.exists():
            pytest.skip("Data types directory not found")

        registry, errors = compile_udt_directory(data_dir)

        # Should have compiled several types
        assert len(registry.types) > 0

        # typeUnitInput should be compiled (no dependencies)
        assert registry.has("typeUnitInput")

        # Can create instances
        arm_input = registry.create_instance("typeUnitInput")
        assert hasattr(arm_input, "percCollarSwitch")
