"""Tests for SCL type system mapping."""

from plc_code.executor.types import (
    ArrayTypeInfo,
    SCLType,
    TypeInfo,
    TypeMapper,
    parse_time_literal,
)


class TestTimeLiteralParsing:
    """Tests for time literal parsing."""

    def test_parse_milliseconds(self) -> None:
        """Test parsing millisecond time literals."""
        assert parse_time_literal("T#150ms") == 0.150
        assert parse_time_literal("T#1ms") == 0.001
        assert parse_time_literal("T#1000ms") == 1.0

    def test_parse_seconds(self) -> None:
        """Test parsing second time literals."""
        assert parse_time_literal("T#1s") == 1.0
        assert parse_time_literal("T#30s") == 30.0
        assert parse_time_literal("T#0s") == 0.0

    def test_parse_minutes(self) -> None:
        """Test parsing minute time literals."""
        assert parse_time_literal("T#1m") == 60.0
        assert parse_time_literal("T#5m") == 300.0

    def test_parse_hours(self) -> None:
        """Test parsing hour time literals."""
        assert parse_time_literal("T#1h") == 3600.0
        assert parse_time_literal("T#2h") == 7200.0

    def test_parse_days(self) -> None:
        """Test parsing day time literals."""
        assert parse_time_literal("T#1d") == 86400.0

    def test_parse_combined(self) -> None:
        """Test parsing combined time literals."""
        assert parse_time_literal("T#1h30m") == 5400.0
        assert parse_time_literal("T#1m30s") == 90.0
        assert parse_time_literal("T#1s500ms") == 1.5

    def test_case_insensitive(self) -> None:
        """Test case-insensitive parsing."""
        assert parse_time_literal("t#150MS") == 0.150
        assert parse_time_literal("T#1S") == 1.0


class TestTypeMapper:
    """Tests for the TypeMapper class."""

    def test_parse_bool_type(self) -> None:
        """Test parsing Bool type."""
        mapper = TypeMapper()
        info = mapper.parse_type("Bool")

        assert isinstance(info, TypeInfo)
        assert info.scl_type == SCLType.BOOL
        assert info.python_type is bool
        assert info.type_hint == "bool"

    def test_parse_int_types(self) -> None:
        """Test parsing integer types."""
        mapper = TypeMapper()

        for type_str in ["Int", "DInt", "SInt", "LInt"]:
            info = mapper.parse_type(type_str)
            assert isinstance(info, TypeInfo)
            assert info.python_type is int
            assert info.type_hint == "int"

    def test_parse_unsigned_int_types(self) -> None:
        """Test parsing unsigned integer types."""
        mapper = TypeMapper()

        for type_str in ["USInt", "UInt", "UDInt", "ULInt"]:
            info = mapper.parse_type(type_str)
            assert isinstance(info, TypeInfo)
            assert info.python_type is int

    def test_parse_real_types(self) -> None:
        """Test parsing floating point types."""
        mapper = TypeMapper()

        info = mapper.parse_type("Real")
        assert isinstance(info, TypeInfo)
        assert info.scl_type == SCLType.REAL
        assert info.python_type is float

        info = mapper.parse_type("LReal")
        assert isinstance(info, TypeInfo)
        assert info.scl_type == SCLType.LREAL
        assert info.python_type is float

    def test_parse_string_type(self) -> None:
        """Test parsing String type."""
        mapper = TypeMapper()
        info = mapper.parse_type("String")

        assert isinstance(info, TypeInfo)
        assert info.scl_type == SCLType.STRING
        assert info.python_type is str
        assert info.type_hint == "str"

    def test_parse_time_type(self) -> None:
        """Test parsing Time type."""
        mapper = TypeMapper()
        info = mapper.parse_type("Time")

        assert isinstance(info, TypeInfo)
        assert info.scl_type == SCLType.TIME
        assert info.python_type is float  # Time stored as seconds

    def test_parse_array_type(self) -> None:
        """Test parsing array types."""
        mapper = TypeMapper()
        info = mapper.parse_type("Array[0..99] of Real")

        assert isinstance(info, ArrayTypeInfo)
        assert info.element_type == "Real"
        assert info.lower_bound == 0
        assert info.upper_bound == 99
        assert info.size == 100

    def test_parse_array_type_1_indexed(self) -> None:
        """Test parsing 1-indexed array types."""
        mapper = TypeMapper()
        info = mapper.parse_type("Array[1..10] of Int")

        assert isinstance(info, ArrayTypeInfo)
        assert info.lower_bound == 1
        assert info.upper_bound == 10
        assert info.size == 10

    def test_parse_array_with_symbolic_upper_bound(self) -> None:
        """Arrays with symbolic bounds (e.g. _.AXIS_NUM_INDEX) parse to ArrayTypeInfo.

        When the array bound is a named constant rather than an integer literal,
        parse_type must still return an ArrayTypeInfo (not an opaque TypeInfo) so
        that get_python_type_hint() yields valid Python ('list[float]') and
        the generated dataclass does not contain invalid Python type annotations.
        """
        mapper = TypeMapper()
        # 1-D symbolic upper bound
        info = mapper.parse_type("Array[0.._.AXIS_NUM_INDEX] of Real")
        assert isinstance(info, ArrayTypeInfo), (
            "Expected ArrayTypeInfo for Array with symbolic bound, got TypeInfo with "
            f"type_hint={info.type_hint!r}"
        )
        assert info.element_type == "Real"

        # Corresponding type hint must be valid Python (not the raw SCL string)
        hint = mapper.get_python_type_hint("Array[0.._.AXIS_NUM_INDEX] of Real")
        assert hint == "list[float]", f"Expected 'list[float]', got {hint!r}"

    def test_parse_2d_array_with_symbolic_bound(self) -> None:
        """2-D array with symbolic bound yields valid Python type hint."""
        mapper = TypeMapper()
        hint = mapper.get_python_type_hint("Array[0.._.AXIS_NUM_INDEX, 0.._.AXIS_NUM_INDEX] of LReal")
        assert hint == "list[list[float]]", f"Expected 'list[list[float]]', got {hint!r}"

    def test_parse_library_type(self) -> None:
        """Test parsing library type references."""
        mapper = TypeMapper()
        info = mapper.parse_type("_.typeUnitData")

        assert isinstance(info, TypeInfo)
        assert info.scl_type == SCLType.UDT
        assert info.type_hint == "typeUnitData"

    def test_parse_timer_type(self) -> None:
        """Test parsing timer types."""
        mapper = TypeMapper()

        info = mapper.parse_type("TON_TIME")
        assert isinstance(info, TypeInfo)
        assert info.scl_type == SCLType.TON_TIME

        info = mapper.parse_type("TOF_TIME")
        assert isinstance(info, TypeInfo)
        assert info.scl_type == SCLType.TOF_TIME

        info = mapper.parse_type("TP_TIME")
        assert isinstance(info, TypeInfo)
        assert info.scl_type == SCLType.TP_TIME


class TestTypeMapperDefaults:
    """Tests for default value creation."""

    def test_create_bool_default(self) -> None:
        """Test creating default Bool value."""
        mapper = TypeMapper()
        assert mapper.create_default("Bool") is False

    def test_create_int_default(self) -> None:
        """Test creating default Int value."""
        mapper = TypeMapper()
        assert mapper.create_default("Int") == 0
        assert mapper.create_default("USInt") == 0

    def test_create_real_default(self) -> None:
        """Test creating default Real value."""
        mapper = TypeMapper()
        assert mapper.create_default("Real") == 0.0

    def test_create_string_default(self) -> None:
        """Test creating default String value."""
        mapper = TypeMapper()
        assert mapper.create_default("String") == ""

    def test_create_time_default(self) -> None:
        """Test creating default Time value."""
        mapper = TypeMapper()
        assert mapper.create_default("Time") == 0.0

    def test_create_array_default(self) -> None:
        """Test creating default array value."""
        mapper = TypeMapper()
        result = mapper.create_default("Array[0..9] of Bool")

        assert isinstance(result, list)
        assert len(result) == 10
        assert all(v is False for v in result)

    def test_create_array_of_real_default(self) -> None:
        """Test creating default array of Real.

        When lo > 0 (1-based), the list is allocated with hi+1 elements so that
        SCL direct index access (arr[1]..arr[hi]) works without an explicit offset.
        Elements 0..lo-1 are zero-initialised padding that the SCL code never reads.
        """
        mapper = TypeMapper()
        result = mapper.create_default("Array[1..5] of Real")

        # hi+1 = 6 elements allocated; index 0 is unused padding
        assert len(result) == 6
        assert all(v == 0.0 for v in result)


class TestTypeMapperLiteralConversion:
    """Tests for literal value conversion."""

    def test_convert_bool_true(self) -> None:
        """Test converting Bool true literals."""
        mapper = TypeMapper()
        assert mapper.convert_literal("True", "Bool") is True
        assert mapper.convert_literal("TRUE", "Bool") is True
        assert mapper.convert_literal("true", "Bool") is True
        assert mapper.convert_literal("1", "Bool") is True

    def test_convert_bool_false(self) -> None:
        """Test converting Bool false literals."""
        mapper = TypeMapper()
        assert mapper.convert_literal("False", "Bool") is False
        assert mapper.convert_literal("FALSE", "Bool") is False
        assert mapper.convert_literal("0", "Bool") is False

    def test_convert_int_literal(self) -> None:
        """Test converting integer literals."""
        mapper = TypeMapper()
        assert mapper.convert_literal("42", "Int") == 42
        assert mapper.convert_literal("-10", "Int") == -10
        assert mapper.convert_literal("0", "USInt") == 0

    def test_convert_hex_literal(self) -> None:
        """Test converting hexadecimal literals."""
        mapper = TypeMapper()
        assert mapper.convert_literal("16#FF", "Byte") == 255
        assert mapper.convert_literal("16#10", "Word") == 16

    def test_convert_binary_literal(self) -> None:
        """Test converting binary literals."""
        mapper = TypeMapper()
        assert mapper.convert_literal("2#1010", "Byte") == 10
        assert mapper.convert_literal("2#11111111", "Byte") == 255

    def test_convert_real_literal(self) -> None:
        """Test converting Real literals."""
        mapper = TypeMapper()
        assert mapper.convert_literal("3.14", "Real") == 3.14
        assert mapper.convert_literal("-0.5", "Real") == -0.5
        assert mapper.convert_literal("0.0", "Real") == 0.0

    def test_convert_time_literal(self) -> None:
        """Test converting Time literals."""
        mapper = TypeMapper()
        assert mapper.convert_literal("T#150ms", "Time") == 0.150
        assert mapper.convert_literal("T#1s", "Time") == 1.0

    def test_convert_string_literal(self) -> None:
        """Test converting String literals."""
        mapper = TypeMapper()
        assert mapper.convert_literal("'hello'", "String") == "hello"
        assert mapper.convert_literal('"world"', "String") == "world"
        assert mapper.convert_literal("test", "String") == "test"


class TestTypeMapperTypeHints:
    """Tests for Python type hint generation."""

    def test_bool_type_hint(self) -> None:
        """Test Bool type hint."""
        mapper = TypeMapper()
        assert mapper.get_python_type_hint("Bool") == "bool"

    def test_int_type_hint(self) -> None:
        """Test Int type hint."""
        mapper = TypeMapper()
        assert mapper.get_python_type_hint("Int") == "int"
        assert mapper.get_python_type_hint("USInt") == "int"

    def test_real_type_hint(self) -> None:
        """Test Real type hint."""
        mapper = TypeMapper()
        assert mapper.get_python_type_hint("Real") == "float"

    def test_array_type_hint(self) -> None:
        """Test array type hint."""
        mapper = TypeMapper()
        assert mapper.get_python_type_hint("Array[0..9] of Bool") == "list[bool]"
        assert mapper.get_python_type_hint("Array[1..10] of Real") == "list[float]"

    def test_udt_type_hint(self) -> None:
        """A UDT or system type is hinted `Any`: its own name is not a Python name in
        the generated module, and a NameError in a hint takes the whole class down."""
        mapper = TypeMapper()
        assert mapper.get_python_type_hint("_.typeUnitData") == "Any"
        assert mapper.get_python_type_hint("HW_IO") == "Any"


class TestArray2D:
    """Tests for 2D array (multi-dimension) support."""

    def test_parse_2d_array_type(self) -> None:
        """Test parsing 2D array type produces ArrayTypeInfo with two dimensions."""
        mapper = TypeMapper()
        info = mapper.parse_type("Array[0..3, 0..3] of LReal")

        assert isinstance(info, ArrayTypeInfo)
        assert info.element_type == "LReal"
        assert info.dimensions == [(0, 3), (0, 3)]

    def test_parse_2d_array_lower_upper_bounds(self) -> None:
        """Test that lower_bound / upper_bound still return first dimension for back-compat."""
        mapper = TypeMapper()
        info = mapper.parse_type("Array[0..3, 0..3] of LReal")

        assert isinstance(info, ArrayTypeInfo)
        assert info.lower_bound == 0
        assert info.upper_bound == 3

    def test_parse_2d_array_size(self) -> None:
        """Test 2D array total size is product of dimension sizes."""
        mapper = TypeMapper()
        info = mapper.parse_type("Array[0..3, 0..3] of LReal")

        assert isinstance(info, ArrayTypeInfo)
        # size for a 2D array: product of each dimension's size
        # dim1 size = 4, dim2 size = 4 → total = 16
        assert info.size == 16

    def test_create_2d_array_default(self) -> None:
        """Test that default value for 2D array is a nested list."""
        mapper = TypeMapper()
        result = mapper.create_default("Array[0..3, 0..3] of LReal")

        assert isinstance(result, list)
        assert len(result) == 4  # 4 rows
        for row in result:
            assert isinstance(row, list)
            assert len(row) == 4  # 4 cols
            assert all(v == 0.0 for v in row)

    def test_2d_array_type_hint(self) -> None:
        """Test type hint for 2D array is list[list[float]]."""
        mapper = TypeMapper()
        hint = mapper.get_python_type_hint("Array[0..3, 0..3] of LReal")

        assert hint == "list[list[float]]"

    def test_1d_array_still_works_after_2d_support(self) -> None:
        """Regression: 1D arrays must continue to work unchanged."""
        mapper = TypeMapper()
        info = mapper.parse_type("Array[0..9] of Real")

        assert isinstance(info, ArrayTypeInfo)
        assert info.element_type == "Real"
        assert info.lower_bound == 0
        assert info.upper_bound == 9
        assert info.size == 10
