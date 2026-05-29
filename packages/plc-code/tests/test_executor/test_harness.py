"""Tests for FBTestHarness and test utilities."""

from pathlib import Path

import pytest

from plc_code.executor.harness import (
    FBTestHarness,
    Step,
    StepResult,
    create_harness,
)
from plc_code.executor.runtime import PLCRuntime
from plc_code.parser import parse_scl_file

# Test fixtures directory
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestStepDataclass:
    """Tests for Step dataclass."""

    def test_default_values(self) -> None:
        """Test default Step values."""
        step = Step()
        assert step.inputs == {}
        assert step.advance_time == 0.0
        assert step.expected_outputs is None
        assert step.description == ""

    def test_with_inputs(self) -> None:
        """Test Step with inputs."""
        step = Step(inputs={"a": True, "b": 42})
        assert step.inputs == {"a": True, "b": 42}

    def test_with_advance_time(self) -> None:
        """Test Step with advance_time."""
        step = Step(advance_time=0.150)
        assert step.advance_time == 0.150

    def test_with_expected_outputs(self) -> None:
        """Test Step with expected outputs."""
        step = Step(expected_outputs={"output": True})
        assert step.expected_outputs == {"output": True}


class TestStepResult:
    """Tests for StepResult dataclass."""

    def test_default_values(self) -> None:
        """Test default StepResult values."""
        result = StepResult(
            step_index=0,
            inputs={},
            outputs={},
            time_before=0.0,
            time_after=0.0,
        )
        assert result.assertions_passed is True
        assert result.assertion_errors == []

    def test_with_assertion_errors(self) -> None:
        """Test StepResult with assertion errors."""
        result = StepResult(
            step_index=0,
            inputs={},
            outputs={"x": 1},
            time_before=0.0,
            time_after=0.1,
            assertions_passed=False,
            assertion_errors=["Output 'x': expected 2, got 1"],
        )
        assert result.assertions_passed is False
        assert len(result.assertion_errors) == 1


class TestFBTestHarness:
    """Tests for FBTestHarness class."""

    @pytest.fixture
    def simple_fb_class(self) -> type:
        """Create a simple FB class for testing."""
        from dataclasses import dataclass, field

        from plc_code.executor.runtime import PLCRuntime

        @dataclass
        class SimpleFB:
            _runtime: PLCRuntime = field(repr=False)

            # VAR_INPUT
            input_a: bool = False
            input_b: int = 0

            # VAR_OUTPUT
            output_x: bool = False
            output_y: int = 0

            _inputs: tuple[str, ...] = field(default=("input_a", "input_b"), repr=False)
            _outputs: tuple[str, ...] = field(default=("output_x", "output_y"), repr=False)
            _in_outs: tuple[str, ...] = field(default=(), repr=False)

            def execute(self) -> None:
                self.output_x = self.input_a
                self.output_y = self.input_b * 2

        return SimpleFB

    def test_init_creates_runtime(self, simple_fb_class: type) -> None:
        """Test that harness creates runtime if not provided."""
        harness = FBTestHarness(simple_fb_class)
        assert harness.runtime is not None
        assert isinstance(harness.runtime, PLCRuntime)

    def test_init_uses_provided_runtime(self, simple_fb_class: type) -> None:
        """Test that harness uses provided runtime."""
        runtime = PLCRuntime()
        harness = FBTestHarness(simple_fb_class, runtime=runtime)
        assert harness.runtime is runtime

    def test_set_inputs(self, simple_fb_class: type) -> None:
        """Test setting inputs."""
        harness = FBTestHarness(simple_fb_class)
        harness.set_inputs(input_a=True, input_b=42)

        assert harness.instance.input_a is True
        assert harness.instance.input_b == 42

    def test_set_inputs_invalid_name(self, simple_fb_class: type) -> None:
        """Test setting invalid input raises error."""
        harness = FBTestHarness(simple_fb_class)
        with pytest.raises(AttributeError, match="no input 'nonexistent'"):
            harness.set_inputs(nonexistent=True)

    def test_set_var(self, simple_fb_class: type) -> None:
        """Test setting any variable."""
        harness = FBTestHarness(simple_fb_class)
        harness.set_var("output_x", True)
        assert harness.instance.output_x is True

    def test_get_output(self, simple_fb_class: type) -> None:
        """Test getting a single output."""
        harness = FBTestHarness(simple_fb_class)
        harness.instance.output_x = True
        assert harness.get_output("output_x") is True

    def test_get_outputs(self, simple_fb_class: type) -> None:
        """Test getting all outputs."""
        harness = FBTestHarness(simple_fb_class)
        harness.instance.output_x = True
        harness.instance.output_y = 10

        outputs = harness.get_outputs()
        assert outputs == {"output_x": True, "output_y": 10}

    def test_get_var(self, simple_fb_class: type) -> None:
        """Test getting any variable."""
        harness = FBTestHarness(simple_fb_class)
        harness.instance.input_a = True
        assert harness.get_var("input_a") is True

    def test_execute(self, simple_fb_class: type) -> None:
        """Test executing one cycle."""
        harness = FBTestHarness(simple_fb_class)
        harness.set_inputs(input_a=True, input_b=5)
        harness.execute()

        assert harness.get_output("output_x") is True
        assert harness.get_output("output_y") == 10

    def test_execute_cycles(self, simple_fb_class: type) -> None:
        """Test executing multiple cycles."""
        harness = FBTestHarness(simple_fb_class)
        harness.set_inputs(input_a=True, input_b=3)
        harness.execute_cycles(3)

        # After 3 cycles, should have executed 3 times
        assert harness.get_output("output_x") is True
        assert harness.get_output("output_y") == 6

    def test_advance_time(self, simple_fb_class: type) -> None:
        """Test advancing simulation time."""
        harness = FBTestHarness(simple_fb_class)
        harness.advance_time(1.5)
        assert harness.runtime.current_time == 1.5

    def test_advance_time_ms(self, simple_fb_class: type) -> None:
        """Test advancing simulation time in milliseconds."""
        harness = FBTestHarness(simple_fb_class)
        harness.advance_time_ms(150)
        assert harness.runtime.current_time == 0.150

    def test_reset(self, simple_fb_class: type) -> None:
        """Test resetting harness state."""
        harness = FBTestHarness(simple_fb_class)
        harness.set_inputs(input_a=True, input_b=5)
        harness.execute()
        harness.advance_time(1.0)

        harness.reset()

        assert harness.runtime.current_time == 0.0
        assert harness.instance.input_a is False
        assert harness.instance.input_b == 0
        assert harness.instance.output_x is False

    def test_run_step_basic(self, simple_fb_class: type) -> None:
        """Test running a single step."""
        harness = FBTestHarness(simple_fb_class)
        step = Step(inputs={"input_a": True, "input_b": 5})
        result = harness.run_step(step)

        assert result.inputs == {"input_a": True, "input_b": 5}
        assert result.outputs == {"output_x": True, "output_y": 10}
        assert result.assertions_passed is True

    def test_run_step_with_time_advance(self, simple_fb_class: type) -> None:
        """Test running a step with time advance."""
        harness = FBTestHarness(simple_fb_class)
        step = Step(inputs={"input_a": True}, advance_time=0.5)
        result = harness.run_step(step)

        assert result.time_before == 0.0
        assert result.time_after == 0.5

    def test_run_step_with_expected_outputs_pass(self, simple_fb_class: type) -> None:
        """Test step assertions pass when outputs match."""
        harness = FBTestHarness(simple_fb_class)
        step = Step(
            inputs={"input_a": True, "input_b": 5},
            expected_outputs={"output_x": True, "output_y": 10},
        )
        result = harness.run_step(step)

        assert result.assertions_passed is True
        assert result.assertion_errors == []

    def test_run_step_with_expected_outputs_fail(self, simple_fb_class: type) -> None:
        """Test step assertions fail when outputs don't match."""
        harness = FBTestHarness(simple_fb_class)
        step = Step(
            inputs={"input_a": True, "input_b": 5},
            expected_outputs={"output_x": False, "output_y": 99},
        )
        result = harness.run_step(step)

        assert result.assertions_passed is False
        assert len(result.assertion_errors) == 2
        assert "output_x" in result.assertion_errors[0]
        assert "output_y" in result.assertion_errors[1]

    def test_run_sequence(self, simple_fb_class: type) -> None:
        """Test running a sequence of steps."""
        harness = FBTestHarness(simple_fb_class)
        steps = [
            Step(inputs={"input_a": False, "input_b": 1}),
            Step(inputs={"input_a": True, "input_b": 2}),
            Step(inputs={"input_a": True, "input_b": 3}),
        ]
        results = harness.run_sequence(steps)

        assert len(results) == 3
        assert results[0].step_index == 0
        assert results[1].step_index == 1
        assert results[2].step_index == 2
        assert results[0].outputs["output_x"] is False
        assert results[1].outputs["output_x"] is True
        assert results[2].outputs["output_y"] == 6

    def test_assert_outputs_pass(self, simple_fb_class: type) -> None:
        """Test assert_outputs passes when outputs match."""
        harness = FBTestHarness(simple_fb_class)
        harness.set_inputs(input_a=True, input_b=5)
        harness.execute()

        # Should not raise
        harness.assert_outputs(output_x=True, output_y=10)

    def test_assert_outputs_fail(self, simple_fb_class: type) -> None:
        """Test assert_outputs raises when outputs don't match."""
        harness = FBTestHarness(simple_fb_class)
        harness.set_inputs(input_a=True, input_b=5)
        harness.execute()

        with pytest.raises(AssertionError, match="output_y"):
            harness.assert_outputs(output_y=99)

    def test_assert_var_pass(self, simple_fb_class: type) -> None:
        """Test assert_var passes when variable matches."""
        harness = FBTestHarness(simple_fb_class)
        harness.instance.input_a = True

        # Should not raise
        harness.assert_var("input_a", True)

    def test_assert_var_fail(self, simple_fb_class: type) -> None:
        """Test assert_var raises when variable doesn't match."""
        harness = FBTestHarness(simple_fb_class)
        harness.instance.input_a = False

        with pytest.raises(AssertionError, match="input_a"):
            harness.assert_var("input_a", True)


class TestSetInputsArrayConversion:
    """Tests for set_inputs dict-to-list conversion for array-type variables."""

    @pytest.fixture
    def array_fb_class(self) -> type:
        """FB with a list input (Array[0..3])."""
        from dataclasses import dataclass, field

        from plc_code.executor.runtime import PLCRuntime

        @dataclass
        class ArrayFB:
            _runtime: PLCRuntime = field(repr=False)

            # VAR_INPUT - array of 4 floats (like angles[0..3])
            angles: list = field(default_factory=lambda: [0.0] * 4)

            # VAR_OUTPUT
            sum_out: float = 0.0

            _inputs: tuple[str, ...] = field(default=("angles",), repr=False)
            _outputs: tuple[str, ...] = field(default=("sum_out",), repr=False)
            _in_outs: tuple[str, ...] = field(default=(), repr=False)

            def execute(self) -> None:
                self.sum_out = self.angles[0] + self.angles[1] + self.angles[2] + self.angles[3]

        return ArrayFB

    def test_set_inputs_int_keyed_dict_for_list(self, array_fb_class: type) -> None:
        """Integer-keyed dict can be used to set a list-type array input."""
        harness = FBTestHarness(array_fb_class)
        harness.set_inputs(angles={0: 1.0, 1: 2.0, 2: 3.0, 3: 4.0})
        harness.execute()
        assert harness.get_output("sum_out") == pytest.approx(10.0)

    def test_set_inputs_string_keyed_dict_for_list(self, array_fb_class: type) -> None:
        """String-keyed dict in insertion order populates a list-type array input."""
        harness = FBTestHarness(array_fb_class)
        # String keys (named constants like SLEWING_AXIS etc.) should be
        # converted to list by insertion order: 0→1.0, 1→2.0, 2→3.0, 3→4.0
        harness.set_inputs(
            angles={"SLEWING_AXIS": 1.0, "INBOARD_AXIS": 2.0, "OUTBOARD_AXIS": 3.0, "ST80_AXIS": 4.0}
        )
        harness.execute()
        assert harness.get_output("sum_out") == pytest.approx(10.0)


class TestCreateHarness:
    """Tests for create_harness factory function."""

    @pytest.fixture
    def simple_fb_class(self) -> type:
        """Create a simple FB class for testing."""
        from dataclasses import dataclass, field

        from plc_code.executor.runtime import PLCRuntime

        @dataclass
        class TestFB:
            _runtime: PLCRuntime = field(repr=False)
            input_val: bool = False
            output_val: bool = False
            _inputs: tuple[str, ...] = field(default=("input_val",), repr=False)
            _outputs: tuple[str, ...] = field(default=("output_val",), repr=False)
            _in_outs: tuple[str, ...] = field(default=(), repr=False)

            def execute(self) -> None:
                self.output_val = self.input_val

        return TestFB

    def test_create_from_class(self, simple_fb_class: type) -> None:
        """Test creating harness from compiled class."""
        harness = create_harness(simple_fb_class)

        assert isinstance(harness, FBTestHarness)
        harness.set_inputs(input_val=True)
        harness.execute()
        assert harness.get_output("output_val") is True

    def test_create_from_class_with_runtime(self, simple_fb_class: type) -> None:
        """Test creating harness from class with custom runtime."""
        runtime = PLCRuntime()
        harness = create_harness(simple_fb_class, runtime=runtime)

        assert harness.runtime is runtime


class TestHarnessWithRealSCL:
    """Integration tests using real SCL files."""

    @pytest.fixture
    def signal_debounce_path(self) -> Path:
        """Path to SignalDebounce.s7dcl fixture."""
        fixtures_path = FIXTURES_DIR / "SignalDebounce.s7dcl"
        if fixtures_path.exists():
            return fixtures_path

        pytest.skip("SignalDebounce.s7dcl not found")
        return Path()  # Unreachable but satisfies type checker

    def test_from_scl_file(self, signal_debounce_path: Path) -> None:
        """Test creating harness from SCL file."""
        harness = FBTestHarness.from_scl_file(signal_debounce_path)

        assert harness.fb_class is not None
        assert harness.instance is not None
        assert "input" in harness.instance._inputs
        assert "output" in harness.instance._outputs

    def test_from_block(self, signal_debounce_path: Path) -> None:
        """Test creating harness from parsed Block."""
        block = parse_scl_file(signal_debounce_path)
        harness = FBTestHarness.from_block(block)

        assert harness.fb_class is not None

    def test_create_harness_from_path(self, signal_debounce_path: Path) -> None:
        """Test create_harness with file path."""
        harness = create_harness(signal_debounce_path)

        assert isinstance(harness, FBTestHarness)

    def test_create_harness_from_block(self, signal_debounce_path: Path) -> None:
        """Test create_harness with Block."""
        block = parse_scl_file(signal_debounce_path)
        harness = create_harness(block)

        assert isinstance(harness, FBTestHarness)

    def test_signal_debounce_filters_short_pulse(self, signal_debounce_path: Path) -> None:
        """Test that SignalDebounce filters short pulses."""
        harness = create_harness(signal_debounce_path)

        # Turn on input
        harness.set_inputs(input=True)
        harness.execute()
        assert harness.get_output("output") is False

        # Advance 100ms (< 150ms threshold)
        harness.advance_time_ms(100)
        harness.execute()
        assert harness.get_output("output") is False

    def test_signal_debounce_passes_long_pulse(self, signal_debounce_path: Path) -> None:
        """Test that SignalDebounce passes long pulses."""
        harness = create_harness(signal_debounce_path)

        # Test with sequence
        steps = [
            Step(inputs={"input": True}),
            Step(inputs={"input": True}, advance_time=0.160),  # > 150ms
        ]
        results = harness.run_sequence(steps)

        assert results[0].outputs["output"] is False
        assert results[1].outputs["output"] is True

    def test_signal_debounce_with_expected_outputs(self, signal_debounce_path: Path) -> None:
        """Test SignalDebounce with expected outputs verification."""
        harness = create_harness(signal_debounce_path)

        steps = [
            Step(
                inputs={"input": True},
                expected_outputs={"output": False},
            ),
            Step(
                inputs={"input": True},
                advance_time=0.160,
                expected_outputs={"output": True},
            ),
        ]
        results = harness.run_sequence(steps)

        assert all(r.assertions_passed for r in results)
