"""Test harness for SCL function block testing.

This module provides utilities for testing transpiled SCL function blocks
with pytest, including sequence testing and assertion helpers.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from plc_code.executor.runtime import PLCRuntime, _auto_struct_to_dict, _AutoStruct, _dict_to_auto_struct
from plc_code.executor.transpiler import compile_block
from plc_code.parser import parse_scl_file
from plc_code.parser.models import Block


@dataclass
class Step:
    """A single step in a test sequence.

    Attributes
    ----------
    inputs : dict[str, Any]
        Input values to set before execution.
    advance_time : float
        Time to advance (in seconds) before execution.
    expected_outputs : dict[str, Any] | None
        Expected output values after execution (optional).
    description : str
        Description of this test step (for debugging).
    """

    inputs: dict[str, Any] = field(default_factory=dict)
    advance_time: float = 0.0
    expected_outputs: dict[str, Any] | None = None
    description: str = ""


@dataclass
class StepResult:
    """Result of executing a test step.

    Attributes
    ----------
    step_index : int
        Index of the step in the sequence.
    inputs : dict[str, Any]
        Inputs that were set.
    outputs : dict[str, Any]
        Outputs after execution.
    time_before : float
        Simulation time before the step.
    time_after : float
        Simulation time after the step.
    assertions_passed : bool
        Whether all expected outputs matched.
    assertion_errors : list[str]
        List of assertion error messages.
    """

    step_index: int
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    time_before: float
    time_after: float
    assertions_passed: bool = True
    assertion_errors: list[str] = field(default_factory=list)


class FBTestHarness:
    """Test harness for function block testing.

    This class provides a convenient interface for testing transpiled
    SCL function blocks with pytest.

    Attributes
    ----------
    runtime : PLCRuntime
        The PLC runtime for this harness.
    instance : Any
        The function block instance.
    fb_class : type
        The function block class.

    Examples
    --------
    Basic usage:

    >>> harness = FBTestHarness(SignalDebounce)
    >>> harness.set_inputs(input=True)
    >>> harness.execute()
    >>> assert harness.get_output("output") == False

    Sequence testing:

    >>> steps = [
    ...     Step(inputs={"input": True}),
    ...     Step(inputs={"input": True}, advance_time=0.160),
    ... ]
    >>> results = harness.run_sequence(steps)
    >>> assert results[-1].outputs["output"] == True
    """

    def __init__(
        self,
        fb_class: type,
        runtime: PLCRuntime | None = None,
    ) -> None:
        """Initialize the test harness.

        Parameters
        ----------
        fb_class : type
            The function block class to test.
        runtime : PLCRuntime | None
            Optional runtime to use. If None, a new one is created.
        """
        self.runtime = runtime or PLCRuntime()
        self.fb_class = fb_class
        self.instance = fb_class(_runtime=self.runtime)

    @classmethod
    def from_scl_file(
        cls,
        file_path: str | Path,
        runtime: PLCRuntime | None = None,
    ) -> "FBTestHarness":
        """Create a test harness from an SCL file.

        The directory containing the SCL file is automatically registered as a
        block search path in the runtime, so that ``"BlockName"(...)`` sub-block
        calls can be resolved at execution time.

        Parameters
        ----------
        file_path : str | Path
            Path to the .s7dcl file.
        runtime : PLCRuntime | None
            Optional runtime to use.

        Returns
        -------
        FBTestHarness
            A test harness for the compiled block.

        Raises
        ------
        ValueError
            If compilation fails.
        """
        resolved = Path(file_path).resolve()
        block = parse_scl_file(resolved)

        # Ensure the runtime knows where to find sibling sub-blocks
        if runtime is None:
            runtime = PLCRuntime()
        block_dir = resolved.parent
        if block_dir not in runtime.block_search_paths:
            runtime.block_search_paths.append(block_dir)

        return cls.from_block(block, runtime)

    @classmethod
    def from_block(
        cls,
        block: Block,
        runtime: PLCRuntime | None = None,
    ) -> "FBTestHarness":
        """Create a test harness from a parsed Block.

        Parameters
        ----------
        block : Block
            The parsed SCL block.
        runtime : PLCRuntime | None
            Optional runtime to use.

        Returns
        -------
        FBTestHarness
            A test harness for the compiled block.

        Raises
        ------
        ValueError
            If compilation fails.
        """
        result = compile_block(block)
        if not result.success:
            raise ValueError(
                f"Failed to compile block: {result.compile_error}\n"
                f"Transpilation errors: {result.transpile_result.errors}"
            )
        return cls(result.fb_class, runtime)  # type: ignore[arg-type]

    def set_inputs(self, **inputs: Any) -> None:
        """Set input values on the function block.

        If a dict is passed for a variable whose current value is an
        :class:`_AutoStruct` (i.e. a UDT input), it is automatically
        converted to an ``_AutoStruct`` so that attribute-style access
        (``self.armGeom.brWidth``) works inside ``execute()``.

        Parameters
        ----------
        **inputs : Any
            Input name-value pairs.
        """
        for name, value in inputs.items():
            if hasattr(self.instance, name):
                # Convert plain dicts to _AutoStruct for UDT variables
                current = getattr(self.instance, name)
                if isinstance(value, dict) and isinstance(current, _AutoStruct):
                    value = _dict_to_auto_struct(value)
                elif isinstance(value, dict) and isinstance(current, list):
                    # Convert a dict to a list for array-type variables.
                    # Integer-keyed dicts: place values at their integer key positions.
                    # String-keyed dicts (named constants like SLEWING_AXIS=0): use
                    # insertion order so {"SLEWING_AXIS": v0, "INBOARD_AXIS": v1, ...}
                    # maps to [v0, v1, ...] — preserving dict insertion order (Python 3.7+).
                    if all(isinstance(k, int) for k in value):
                        size = max(len(current), max(value.keys()) + 1) if value else len(current)
                        result_list = list(current[:size]) + [0] * max(0, size - len(current))
                        for k, v in value.items():
                            result_list[k] = v
                        value = result_list
                    else:
                        # String keys: convert by insertion order
                        value = list(value.values())
                setattr(self.instance, name, value)
            else:
                raise AttributeError(
                    f"Function block has no input '{name}'. " f"Available inputs: {self.instance._inputs}"
                )

    def set_var(self, name: str, value: Any) -> None:
        """Set any variable on the function block.

        Parameters
        ----------
        name : str
            Variable name.
        value : Any
            Value to set.
        """
        setattr(self.instance, name, value)

    def get_output(self, name: str) -> Any:
        """Get an output value from the function block.

        Parameters
        ----------
        name : str
            Output name.

        Returns
        -------
        Any
            The output value.
        """
        return getattr(self.instance, name)

    def get_outputs(self) -> dict[str, Any]:
        """Get all output values, including VAR_IN_OUT values.

        :class:`_AutoStruct` values (UDT outputs) are recursively
        converted to plain Python dicts so that callers can use
        standard ``dict[key]`` access patterns.

        Returns
        -------
        dict[str, Any]
            Dictionary of output name-value pairs (VAR_OUTPUT and VAR_IN_OUT).
        """
        result = {name: _auto_struct_to_dict(getattr(self.instance, name)) for name in self.instance._outputs}
        result.update(
            {name: _auto_struct_to_dict(getattr(self.instance, name)) for name in self.instance._in_outs}
        )
        return result

    def get_var(self, name: str) -> Any:
        """Get any variable from the function block.

        Parameters
        ----------
        name : str
            Variable name.

        Returns
        -------
        Any
            The variable value.
        """
        return getattr(self.instance, name)

    def execute(self) -> None:
        """Execute one cycle of the function block."""
        self.instance.execute()

    def execute_cycles(self, n: int) -> None:
        """Execute multiple cycles.

        Parameters
        ----------
        n : int
            Number of cycles to execute.
        """
        for _ in range(n):
            self.instance.execute()
            self.runtime.execute_cycle()

    def advance_time(self, seconds: float) -> None:
        """Advance the simulation time.

        Parameters
        ----------
        seconds : float
            Time to advance in seconds.
        """
        self.runtime.clock.advance(seconds)

    def advance_time_ms(self, milliseconds: float) -> None:
        """Advance the simulation time in milliseconds.

        Parameters
        ----------
        milliseconds : float
            Time to advance in milliseconds.
        """
        self.runtime.clock.advance_ms(milliseconds)

    def reset(self) -> None:
        """Reset the harness to initial state.

        Creates a new instance and resets the runtime.
        """
        self.runtime.reset()
        self.instance = self.fb_class(_runtime=self.runtime)

    def run_step(self, step: Step) -> StepResult:
        """Run a single test step.

        Parameters
        ----------
        step : Step
            The test step to execute.

        Returns
        -------
        StepResult
            The result of the step execution.
        """
        time_before = self.runtime.current_time

        # Advance time if specified
        if step.advance_time > 0:
            self.advance_time(step.advance_time)

        # Set inputs
        for name, value in step.inputs.items():
            if hasattr(self.instance, name):
                setattr(self.instance, name, value)

        # Execute
        self.execute()

        time_after = self.runtime.current_time
        outputs = self.get_outputs()

        # Check assertions
        assertions_passed = True
        assertion_errors: list[str] = []

        if step.expected_outputs:
            for name, expected in step.expected_outputs.items():
                actual = outputs.get(name)
                if actual != expected:
                    assertions_passed = False
                    assertion_errors.append(f"Output '{name}': expected {expected!r}, got {actual!r}")

        return StepResult(
            step_index=0,
            inputs=step.inputs.copy(),
            outputs=outputs,
            time_before=time_before,
            time_after=time_after,
            assertions_passed=assertions_passed,
            assertion_errors=assertion_errors,
        )

    def run_sequence(self, steps: list[Step]) -> list[StepResult]:
        """Run a sequence of test steps.

        Parameters
        ----------
        steps : list[Step]
            List of test steps to execute in order.

        Returns
        -------
        list[StepResult]
            Results from each step.
        """
        results: list[StepResult] = []

        for i, step in enumerate(steps):
            result = self.run_step(step)
            result.step_index = i
            results.append(result)

        return results

    def assert_outputs(self, **expected: Any) -> None:
        """Assert that outputs match expected values.

        Parameters
        ----------
        **expected : Any
            Expected output name-value pairs.

        Raises
        ------
        AssertionError
            If any output doesn't match.
        """
        outputs = self.get_outputs()
        for name, expected_value in expected.items():
            actual = outputs.get(name)
            if actual != expected_value:
                raise AssertionError(f"Output '{name}': expected {expected_value!r}, got {actual!r}")

    def assert_var(self, name: str, expected: Any) -> None:
        """Assert that a variable matches expected value.

        Parameters
        ----------
        name : str
            Variable name.
        expected : Any
            Expected value.

        Raises
        ------
        AssertionError
            If the variable doesn't match.
        """
        actual = getattr(self.instance, name)
        if actual != expected:
            raise AssertionError(f"Variable '{name}': expected {expected!r}, got {actual!r}")


def create_harness(
    source: str | Path | Block | type,
    runtime: PLCRuntime | None = None,
) -> FBTestHarness:
    """Create a test harness from various sources.

    Parameters
    ----------
    source : str | Path | Block | type
        The source - can be:
        - A file path (str or Path) to an .s7dcl file
        - A parsed Block object
        - A compiled function block class
    runtime : PLCRuntime | None
        Optional runtime to use.

    Returns
    -------
    FBTestHarness
        A test harness for the function block.

    Examples
    --------
    >>> harness = create_harness("SignalDebounce.s7dcl")
    >>> harness = create_harness(my_parsed_block)
    >>> harness = create_harness(MyCompiledClass)
    """
    if isinstance(source, type):
        return FBTestHarness(source, runtime)
    if isinstance(source, Block):
        return FBTestHarness.from_block(source, runtime)
    return FBTestHarness.from_scl_file(source, runtime)
