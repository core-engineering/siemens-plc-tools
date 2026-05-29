"""Tests for external dependencies handling."""

import pytest

from plc_code.executor.external import (
    DependencyRegistry,
    MockDataBlock,
    NestedMockDB,
    create_mock_db,
    create_nested_mock_db,
    create_stub_from_spec,
    create_stub_type,
)
from plc_code.executor.runtime import PLCRuntime


class TestCreateStubType:
    """Tests for create_stub_type function."""

    def test_create_empty_stub(self) -> None:
        """Test creating stub with no fields."""
        StubType = create_stub_type("EmptyStub")
        instance = StubType()
        assert instance is not None

    def test_create_stub_with_fields(self) -> None:
        """Test creating stub with typed fields."""
        StubType = create_stub_type(
            "TestStub",
            fields={"active": bool, "count": int, "value": float},
        )

        instance = StubType()
        assert instance.active is False
        assert instance.count == 0
        assert instance.value == 0

    def test_create_stub_with_defaults(self) -> None:
        """Test creating stub with custom defaults."""
        StubType = create_stub_type(
            "TestStub",
            fields={"enabled": bool, "threshold": float},
            defaults={"enabled": True, "threshold": 0.5},
        )

        instance = StubType()
        assert instance.enabled is True
        assert instance.threshold == 0.5

    def test_create_stub_with_string_field(self) -> None:
        """Test creating stub with string field."""
        StubType = create_stub_type(
            "TestStub",
            fields={"name": str},
            defaults={"name": "default"},
        )

        instance = StubType()
        assert instance.name == "default"


class TestCreateStubFromSpec:
    """Tests for create_stub_from_spec function."""

    def test_create_from_spec(self) -> None:
        """Test creating stub from type specification."""
        StubType = create_stub_from_spec(
            "typeUnitInput",
            {
                "percCollarSwitch": "bool",
                "value": "Real",
                "index": "Int",
            },
        )

        instance = StubType()
        assert instance.percCollarSwitch is False
        assert instance.value == 0
        assert instance.index == 0

    def test_spec_type_aliases(self) -> None:
        """Test that SCL type names work."""
        StubType = create_stub_from_spec(
            "TestType",
            {
                "flag": "Bool",
                "counter": "DInt",
                "position": "LReal",
                "message": "String",
            },
        )

        instance = StubType()
        assert isinstance(instance.flag, bool)
        assert isinstance(instance.counter, int)
        assert isinstance(instance.position, (int, float))
        assert isinstance(instance.message, str)


class TestMockDataBlock:
    """Tests for MockDataBlock class."""

    def test_create_empty_mock(self) -> None:
        """Test creating empty mock DB."""
        mock = MockDataBlock(_name="TestDB")
        assert mock._name == "TestDB"

    def test_set_and_get_field(self) -> None:
        """Test setting and getting fields."""
        mock = MockDataBlock(_name="TestDB")
        mock.value = 42
        mock.active = True

        assert mock.value == 42
        assert mock.active is True

    def test_get_nonexistent_field_raises(self) -> None:
        """Test that accessing missing field raises."""
        mock = MockDataBlock(_name="TestDB")

        with pytest.raises(AttributeError, match="has no field"):
            _ = mock.nonexistent

    def test_repr(self) -> None:
        """Test string representation."""
        mock = MockDataBlock(_name="TestDB", _data={"x": 1})
        assert "TestDB" in repr(mock)


class TestCreateMockDb:
    """Tests for create_mock_db function."""

    def test_create_with_structure(self) -> None:
        """Test creating mock with initial structure."""
        mock = create_mock_db(
            "ProcessData",
            {
                "armCount": 4,
                "maxPressure": 100.0,
            },
        )

        assert mock.armCount == 4
        assert mock.maxPressure == 100.0

    def test_modify_structure(self) -> None:
        """Test modifying mock after creation."""
        mock = create_mock_db("TestDB", {"initial": 0})
        mock.initial = 10
        mock.added = "new"

        assert mock.initial == 10
        assert mock.added == "new"


class TestNestedMockDB:
    """Tests for NestedMockDB class."""

    def test_nested_access(self) -> None:
        """Test nested attribute access."""
        mock = NestedMockDB(_name="TestDB")
        mock.arm.position = 45.0

        assert mock.arm.position == 45.0

    def test_array_access(self) -> None:
        """Test array indexing."""
        mock = NestedMockDB(_name="TestDB")
        mock[0].value = 10
        mock[1].value = 20

        assert mock[0].value == 10
        assert mock[1].value == 20

    def test_deep_nested_access(self) -> None:
        """Test deeply nested access."""
        mock = create_nested_mock_db("ArmData")
        mock.arm.parameters.threshold.value = 0.5

        assert mock.arm.parameters.threshold.value == 0.5


class TestDependencyRegistry:
    """Tests for DependencyRegistry class."""

    def test_register_type(self) -> None:
        """Test registering a type."""
        registry = DependencyRegistry()

        from dataclasses import dataclass

        @dataclass
        class TestType:
            value: int = 0

        registry.register_type("TestType", TestType)

        assert registry.has_type("TestType")
        assert registry.get_type("TestType") is TestType

    def test_register_type_with_prefix(self) -> None:
        """Test that _.prefix is stripped."""
        registry = DependencyRegistry()

        from dataclasses import dataclass

        @dataclass
        class TestType:
            pass

        registry.register_type("_.TestType", TestType)

        assert registry.has_type("TestType")
        assert registry.has_type("_.TestType")

    def test_register_stub(self) -> None:
        """Test creating and registering stub."""
        registry = DependencyRegistry()

        StubClass = registry.register_stub(
            "typeUnitInput",
            fields={"active": bool, "value": float},
            defaults={"active": False, "value": 0.0},
        )

        assert registry.has_type("typeUnitInput")
        instance = StubClass()
        assert instance.active is False
        assert instance.value == 0.0

    def test_register_db(self) -> None:
        """Test registering data block."""
        registry = DependencyRegistry()

        mock = create_mock_db("TestDB", {"x": 1})
        registry.register_db("TestDB", mock)

        assert registry.get_db("TestDB") is mock

    def test_create_mock_db(self) -> None:
        """Test creating mock DB through registry."""
        registry = DependencyRegistry()

        mock = registry.create_mock_db("ProcessData", {"armCount": 4})

        assert mock.armCount == 4
        assert registry.get_db("ProcessData") is mock

    def test_create_nested_mock_db(self) -> None:
        """Test creating nested mock through registry."""
        registry = DependencyRegistry()

        mock = registry.create_mock_db("ArmData", nested=True)
        mock.arm.position = 45.0

        assert mock.arm.position == 45.0

    def test_get_db_not_found(self) -> None:
        """Test that missing DB raises KeyError."""
        registry = DependencyRegistry()

        with pytest.raises(KeyError, match="not registered"):
            registry.get_db("NonExistent")

    def test_apply_to_runtime(self) -> None:
        """Test applying registry to runtime."""
        registry = DependencyRegistry()
        registry.create_mock_db("DB1", {"a": 1})
        registry.create_mock_db("DB2", {"b": 2})

        runtime = PLCRuntime()
        registry.apply_to_runtime(runtime)

        assert runtime.get_db("DB1").a == 1
        assert runtime.get_db("DB2").b == 2

    def test_get_compile_globals(self) -> None:
        """Test getting globals for compilation."""
        registry = DependencyRegistry()

        from dataclasses import dataclass

        @dataclass
        class TypeA:
            pass

        @dataclass
        class TypeB:
            pass

        registry.register_type("TypeA", TypeA)
        registry.register_type("TypeB", TypeB)

        globals_dict = registry.get_compile_globals()

        assert globals_dict["TypeA"] is TypeA
        assert globals_dict["TypeB"] is TypeB


class TestIntegration:
    """Integration tests for external dependencies."""

    def test_compile_with_external_type(self) -> None:
        """Test compiling UDT that references external type."""
        from plc_code.executor.udt import UDTRegistry, compile_udt
        from plc_code.parser.models import Block, StructField, UserDataType

        # Create external type stub
        dep_registry = DependencyRegistry()
        ChildType = dep_registry.register_stub(
            "ChildType",
            fields={"data": int},
            defaults={"data": 0},
        )

        # Create UDT registry with the external type
        udt_registry = UDTRegistry()
        udt_registry.register("ChildType", ChildType)

        # Create UDT that references external type
        parent_udt = UserDataType(
            name="ParentType",
            fields=[StructField(name="child", data_type="_.ChildType")],
        )
        parent_block = Block(
            name="ParentType",
            block_type="TYPE",
            user_data_type=parent_udt,
        )

        # Compile
        result = compile_udt(parent_block, registry=udt_registry)

        assert result.success
        assert result.udt_class is not None
        instance = result.udt_class()
        assert instance.child.data == 0

    def test_runtime_with_mock_dbs(self) -> None:
        """Test runtime with mock data blocks."""
        from plc_code.executor.runtime import PLCRuntime

        # Setup
        dep_registry = DependencyRegistry()
        dep_registry.create_mock_db(
            "ProcessData",
            {"armCount": 4, "maxPressure": 150.0},
        )

        runtime = PLCRuntime()
        dep_registry.apply_to_runtime(runtime)

        # Access
        process_db = runtime.get_db("ProcessData")
        assert process_db.armCount == 4
        assert process_db.maxPressure == 150.0

        # Modify
        process_db.armCount = 6
        assert runtime.get_db("ProcessData").armCount == 6
