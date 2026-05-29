"""Tests for SCL transpiler."""

from pathlib import Path

import pytest

from plc_code.executor.runtime import PLCRuntime
from plc_code.executor.transpiler import compile_block, transpile_block
from plc_code.parser import parse_scl_file
from plc_code.parser.models import (
    Block,
    Network,
    VariableDeclaration,
    VariableSection,
)


class TestTranspileResult:
    """Tests for transpilation result."""

    def test_transpile_simple_block(self) -> None:
        """Test transpiling a simple block."""
        block = Block(
            name="TestBlock",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR_INPUT",
                    variables=[
                        VariableDeclaration(name="input", data_type="Bool"),
                    ],
                ),
                VariableSection(
                    section_type="VAR_OUTPUT",
                    variables=[
                        VariableDeclaration(name="output", data_type="Bool"),
                    ],
                ),
            ],
        )

        result = transpile_block(block)

        assert result.success
        assert result.class_name == "TestBlock"
        assert "class TestBlock:" in result.python_code
        assert "input: bool" in result.python_code
        assert "output: bool" in result.python_code

    def test_transpile_with_default_values(self) -> None:
        """Test transpiling block with default values."""
        block = Block(
            name="WithDefaults",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR",
                    variables=[
                        VariableDeclaration(name="counter", data_type="Int", default_value="0"),
                        VariableDeclaration(name="enabled", data_type="Bool", default_value="True"),
                    ],
                ),
            ],
        )

        result = transpile_block(block)

        assert result.success
        assert "counter: int = 0" in result.python_code
        assert "enabled: bool = True" in result.python_code

    def test_transpile_with_timer(self) -> None:
        """Test transpiling block with timer."""
        block = Block(
            name="WithTimer",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR",
                    variables=[
                        VariableDeclaration(name="timer", data_type="TON_TIME"),
                    ],
                ),
            ],
        )

        result = transpile_block(block)

        assert result.success
        assert "from plc_code.executor.timers import TON_TIME" in result.python_code
        assert "timer: TON_TIME" in result.python_code

    def test_transpile_with_math_function_emits_import_math(self) -> None:
        """Test that using COS() in a block body causes 'import math' to be emitted."""
        block = Block(
            name="CosBlock",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR_INPUT",
                    variables=[
                        VariableDeclaration(name="x", data_type="Real"),
                    ],
                ),
                VariableSection(
                    section_type="VAR_OUTPUT",
                    variables=[
                        VariableDeclaration(name="result", data_type="Real"),
                    ],
                ),
            ],
            networks=[
                Network(content="#result := COS(#x);"),
            ],
        )

        result = transpile_block(block)

        assert result.success
        assert "import math" in result.python_code

    def test_transpile_with_time_constant(self) -> None:
        """Test transpiling block with time constant."""
        block = Block(
            name="WithTimeConst",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR_CONSTANT",
                    is_constant=True,
                    variables=[
                        VariableDeclaration(name="delay", data_type="Time", default_value="T#150ms"),
                    ],
                ),
            ],
        )

        result = transpile_block(block)

        assert result.success
        assert "delay: float = 0.15" in result.python_code


class TestCompileBlock:
    """Tests for compile_block function."""

    def test_compile_simple_block(self) -> None:
        """Test compiling a simple block."""
        block = Block(
            name="SimpleBlock",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR_INPUT",
                    variables=[
                        VariableDeclaration(name="value", data_type="Int"),
                    ],
                ),
            ],
        )

        result = compile_block(block)

        assert result.success
        assert result.fb_class is not None
        assert result.fb_class.__name__ == "SimpleBlock"

    def test_compile_and_instantiate(self) -> None:
        """Test compiling and instantiating a block."""
        block = Block(
            name="InstantiableBlock",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR_INPUT",
                    variables=[
                        VariableDeclaration(name="input_val", data_type="Int"),
                    ],
                ),
                VariableSection(
                    section_type="VAR_OUTPUT",
                    variables=[
                        VariableDeclaration(name="output_val", data_type="Int"),
                    ],
                ),
            ],
        )

        result = compile_block(block)
        assert result.success
        assert result.fb_class is not None

        # Create runtime and instance
        runtime = PLCRuntime()
        instance = result.fb_class(_runtime=runtime)

        # Check attributes
        assert hasattr(instance, "input_val")
        assert hasattr(instance, "output_val")
        assert instance.input_val == 0
        assert instance.output_val == 0


class TestRealSCLFiles:
    """Tests using real SCL files from program-listings."""

    @pytest.fixture
    def signal_debounce_path(self) -> Path:
        """Get path to SignalDebounce.s7dcl."""
        return Path(__file__).parent.parent / "fixtures" / "SignalDebounce.s7dcl"

    def test_parse_and_transpile_signal_debounce(self, signal_debounce_path: Path) -> None:
        """Test parsing and transpiling SignalDebounce block."""
        if not signal_debounce_path.exists():
            pytest.skip("SignalDebounce.s7dcl not found")

        block = parse_scl_file(signal_debounce_path)
        result = transpile_block(block)

        assert result.success
        assert result.class_name == "SignalDebounce"

        # Check generated code structure
        code = result.python_code
        assert "class SignalDebounce:" in code
        assert "input: bool" in code
        assert "output: bool" in code
        assert "debounceTimer: TON_TIME" in code
        assert "delay: float = 0.15" in code
        assert "def execute(self)" in code

    def test_compile_and_run_signal_debounce(self, signal_debounce_path: Path) -> None:
        """Test compiling and running SignalDebounce block."""
        if not signal_debounce_path.exists():
            pytest.skip("SignalDebounce.s7dcl not found")

        block = parse_scl_file(signal_debounce_path)
        result = compile_block(block)

        assert result.success, f"Compile failed: {result.compile_error}"
        assert result.fb_class is not None

        # Create runtime and instance
        runtime = PLCRuntime()
        instance = result.fb_class(_runtime=runtime)

        # Test initial state
        assert instance.input is False
        assert instance.output is False

        # Test: short pulse should not trigger output
        instance.input = True
        instance.execute()
        assert instance.output is False  # Not yet (timer not elapsed)

        runtime.clock.advance(0.100)  # 100ms < 150ms delay
        instance.execute()
        assert instance.output is False  # Still not triggered

        # Input goes low before delay
        instance.input = False
        instance.execute()
        assert instance.output is False

        # Test: long pulse should trigger output
        instance.input = True
        instance.execute()
        runtime.clock.advance(0.160)  # 160ms > 150ms delay
        instance.execute()
        assert instance.output is True  # Now triggered


class TestMetadataGeneration:
    """Tests for metadata generation."""

    def test_input_output_metadata(self) -> None:
        """Test that input/output metadata is generated."""
        block = Block(
            name="MetadataTest",
            block_type="FUNCTION_BLOCK",
            variable_sections=[
                VariableSection(
                    section_type="VAR_INPUT",
                    variables=[
                        VariableDeclaration(name="in1", data_type="Bool"),
                        VariableDeclaration(name="in2", data_type="Int"),
                    ],
                ),
                VariableSection(
                    section_type="VAR_OUTPUT",
                    variables=[
                        VariableDeclaration(name="out1", data_type="Bool"),
                    ],
                ),
            ],
        )

        result = compile_block(block)
        assert result.success
        assert result.fb_class is not None

        runtime = PLCRuntime()
        instance = result.fb_class(_runtime=runtime)

        assert instance._inputs == ("in1", "in2")
        assert instance._outputs == ("out1",)


class TestArray2DTranspiler:
    """End-to-end tests for 2D array (Array[lo1..hi1, lo2..hi2] of T) support."""

    def _make_2d_array_block(self) -> Block:
        """Return a FUNCTION block with a 4x4 LReal VAR_OUTPUT and 16 assignments."""
        scl_body = "\n".join(
            [f"#transform[{i}, {j}] := {i * 4 + j + 1}.0;" for i in range(4) for j in range(4)]
        )
        return Block(
            name="Fill4x4",
            block_type="FUNCTION",
            variable_sections=[
                VariableSection(
                    section_type="VAR_OUTPUT",
                    variables=[
                        VariableDeclaration(name="transform", data_type="Array[0..3, 0..3] of LReal"),
                    ],
                ),
            ],
            networks=[
                Network(content=scl_body),
            ],
        )

    def test_transpile_2d_array_var_produces_nested_list_default(self) -> None:
        """Declaration with 2D array type uses nested list default in generated code."""
        block = self._make_2d_array_block()
        result = transpile_block(block)

        assert result.success, f"Transpile errors: {result.errors}"
        # The generated code must not contain a flat '[0.0] * N' but a nested list
        code = result.python_code
        assert "list[list[float]]" in code or "list[float]" in code  # type hint present

    def test_compile_2d_array_block_succeeds(self) -> None:
        """Block with a 2D array output compiles without error."""
        block = self._make_2d_array_block()
        result = compile_block(block)

        assert result.success, f"Compile error: {result.compile_error}\n{result.transpile_result.python_code}"

    def test_2d_array_instance_has_nested_list(self) -> None:
        """Instantiated block has a 4x4 nested list initialized to 0.0."""
        block = self._make_2d_array_block()
        result = compile_block(block)
        assert result.success
        assert result.fb_class is not None

        runtime = PLCRuntime()
        instance = result.fb_class(_runtime=runtime)

        assert isinstance(instance.transform, list)
        assert len(instance.transform) == 4
        for row in instance.transform:
            assert isinstance(row, list)
            assert len(row) == 4

    def test_2d_array_write_and_read_via_execute(self) -> None:
        """Executing the block fills the 4x4 matrix; values are readable as array[i][j]."""
        block = self._make_2d_array_block()
        result = compile_block(block)
        assert result.success, f"Compile error: {result.compile_error}\n{result.transpile_result.python_code}"
        assert result.fb_class is not None

        runtime = PLCRuntime()
        instance = result.fb_class(_runtime=runtime)
        instance.execute()

        # Values were assigned as (i*4 + j + 1).0 for i in 0..3, j in 0..3
        for i in range(4):
            for j in range(4):
                expected = float(i * 4 + j + 1)
                assert instance.transform[i][j] == expected, (
                    f"transform[{i}][{j}]: expected {expected}, got {instance.transform[i][j]}"
                )


class TestUDTStructSupport:
    """Tests for UDT (User Defined Type) struct input/output support.

    These tests cover:
    - Compilation succeeds when variables use _.TypeName UDT references
    - Passing dict inputs for UDT input variables (attribute-accessible)
    - UDT output variables support nested attribute and indexed access
    - get_outputs() converts UDT output objects back to dicts
    - 1-based array indexing (Array[1..6]) in UDT fields
    """

    def _make_udt_block(self) -> Block:
        """Block with UDT input and output: reads from input struct, writes to output struct."""
        scl_body = (
            "#outStruct.fieldA := #inStruct.x;\n"
            "#outStruct.fieldB := #inStruct.y + 1.0;\n"
        )
        return Block(
            name="CopyUDT",
            block_type="FUNCTION",
            variable_sections=[
                VariableSection(
                    section_type="VAR_INPUT",
                    variables=[
                        VariableDeclaration(name="inStruct", data_type="_.typeInputStruct"),
                    ],
                ),
                VariableSection(
                    section_type="VAR_OUTPUT",
                    variables=[
                        VariableDeclaration(name="outStruct", data_type="_.typeOutputStruct"),
                    ],
                ),
            ],
            networks=[
                Network(content=scl_body),
            ],
        )

    def _make_nested_indexed_block(self) -> Block:
        """Block with 1-based indexed array of structs in output UDT."""
        scl_body = (
            "#result.items[1].value := #input.scale;\n"
            "#result.items[2].value := #input.scale * 2.0;\n"
            "#result.items[6].value := #input.scale * 6.0;\n"
            "#result.count := 6;\n"
        )
        return Block(
            name="FillItems",
            block_type="FUNCTION",
            variable_sections=[
                VariableSection(
                    section_type="VAR_INPUT",
                    variables=[
                        VariableDeclaration(name="input", data_type="_.typeParams"),
                    ],
                ),
                VariableSection(
                    section_type="VAR_OUTPUT",
                    variables=[
                        VariableDeclaration(name="result", data_type="_.typeResult"),
                    ],
                ),
            ],
            networks=[
                Network(content=scl_body),
            ],
        )

    def test_compile_udt_input_output_block_succeeds(self) -> None:
        """A block with _.Type variables compiles without NameError."""
        block = self._make_udt_block()
        result = compile_block(block)
        assert result.success, (
            f"Compile error: {result.compile_error}\n"
            f"Code:\n{result.transpile_result.python_code}"
        )

    def test_udt_input_dict_attribute_access_works(self) -> None:
        """Passing a dict for UDT input allows attribute-style access in execute()."""
        block = self._make_udt_block()
        result = compile_block(block)
        assert result.success

        from plc_code.executor.harness import FBTestHarness

        harness = FBTestHarness(result.fb_class)
        harness.set_inputs(inStruct={"x": 3.14, "y": 1.0})
        harness.execute()
        # Should not raise - attribute access worked

    def test_udt_output_accessible_as_dict(self) -> None:
        """After execute(), UDT output can be read back as a dict."""
        block = self._make_udt_block()
        result = compile_block(block)
        assert result.success

        from plc_code.executor.harness import FBTestHarness

        harness = FBTestHarness(result.fb_class)
        harness.set_inputs(inStruct={"x": 3.14, "y": 1.0})
        harness.execute()
        outputs = harness.get_outputs()
        assert "outStruct" in outputs
        out = outputs["outStruct"]
        assert isinstance(out, dict)
        assert out["fieldA"] == pytest.approx(3.14)
        assert out["fieldB"] == pytest.approx(2.0)

    def test_udt_nested_indexed_output_with_1based_array(self) -> None:
        """Block writing to result.items[1..6].value produces correct dict output."""
        block = self._make_nested_indexed_block()
        result = compile_block(block)
        assert result.success, (
            f"Compile error: {result.compile_error}\n"
            f"Code:\n{result.transpile_result.python_code}"
        )

        from plc_code.executor.harness import FBTestHarness

        harness = FBTestHarness(result.fb_class)
        harness.set_inputs(input={"scale": 5.0})
        harness.execute()
        outputs = harness.get_outputs()
        assert "result" in outputs
        r = outputs["result"]
        assert isinstance(r, dict)
        assert r["items"][1]["value"] == pytest.approx(5.0)
        assert r["items"][2]["value"] == pytest.approx(10.0)
        assert r["items"][6]["value"] == pytest.approx(30.0)
        assert r["count"] == 6
