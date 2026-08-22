"""SCL execution and transpilation module.

This module provides tools for transpiling TIA Portal SCL code to
executable Python classes and running them for unit testing.

Key Components
--------------
- TypeMapper: Maps SCL types to Python types
- PLCRuntime: Simulates PLC cyclic execution
- MockClock: Controllable clock for testing
- TON_TIME, TOF_TIME, TP_TIME: Timer implementations
- SCLTranspiler: Transpiles SCL blocks to Python
- compile_block: Transpile and compile to executable class
- FBTestHarness: Test harness for pytest integration
- create_harness: Factory function for easy harness creation

Example Usage
-------------
```python
from plc_code.executor import create_harness, Step

# Create harness from SCL file
harness = create_harness("SignalDebounce.s7dcl")

# Test with sequence
steps = [
    Step(inputs={"input": True}),
    Step(inputs={"input": True}, advance_time=0.160),
]
results = harness.run_sequence(steps)

assert results[0].outputs["output"] == False
assert results[1].outputs["output"] == True
```

Alternative low-level usage:

```python
from plc_code.parser import parse_scl_file
from plc_code.executor import compile_block, PLCRuntime

# Parse and compile an SCL block
block = parse_scl_file("SignalDebounce.s7dcl")
result = compile_block(block)
fb_class = result.fb_class

# Create runtime and instance
runtime = PLCRuntime()
instance = fb_class(_runtime=runtime)

# Execute and test
instance.input = True
instance.execute()
runtime.clock.advance(0.160)
instance.execute()
assert instance.output == True
```
"""

from plc_code.executor.codegen import (
    CodeGenContext,
    ExpressionTranslator,
    StatementTranslator,
)
from plc_code.executor.diagnostics import (
    CODE_SYNTAX,
    CODE_TRANSPILE,
    CODE_UNDEFINED_NAME,
    Diagnostic,
    check_block,
)
from plc_code.executor.external import (
    DependencyRegistry,
    MockDataBlock,
    NestedMockDB,
    create_mock_db,
    create_nested_mock_db,
    create_stub_from_spec,
    create_stub_type,
)
from plc_code.executor.harness import (
    FBTestHarness,
    Step,
    StepResult,
    create_harness,
)
from plc_code.executor.models import (
    CompileResult,
    ExecutionContext,
    PLCValue,
    TranspileOptions,
    TranspileResult,
)
from plc_code.executor.runtime import MockClock, PLCRuntime
from plc_code.executor.timers import TOF_TIME, TON_TIME, TP_TIME
from plc_code.executor.transpiler import (
    SCLTranspiler,
    build_runtime_globals,
    compile_block,
    transpile_block,
)
from plc_code.executor.types import (
    ArrayTypeInfo,
    SCLType,
    TypeInfo,
    TypeMapper,
    default_type_mapper,
    parse_time_literal,
)
from plc_code.executor.udt import (
    UDTCompileResult,
    UDTGenerationResult,
    UDTGenerator,
    UDTRegistry,
    compile_udt,
    compile_udt_directory,
    generate_udt,
)

# Backwards compatibility alias
TestStep = Step

__all__ = [
    # Models
    "TranspileOptions",
    "TranspileResult",
    "CompileResult",
    "ExecutionContext",
    "PLCValue",
    # Types
    "SCLType",
    "TypeInfo",
    "ArrayTypeInfo",
    "TypeMapper",
    "default_type_mapper",
    "parse_time_literal",
    # Runtime
    "PLCRuntime",
    "MockClock",
    # Timers
    "TON_TIME",
    "TOF_TIME",
    "TP_TIME",
    # Transpiler
    "SCLTranspiler",
    "transpile_block",
    "compile_block",
    "build_runtime_globals",
    # Diagnostics
    "check_block",
    "Diagnostic",
    "CODE_TRANSPILE",
    "CODE_SYNTAX",
    "CODE_UNDEFINED_NAME",
    # Code generation
    "CodeGenContext",
    "ExpressionTranslator",
    "StatementTranslator",
    # Test harness
    "FBTestHarness",
    "Step",
    "TestStep",  # Backwards compatibility alias for Step
    "StepResult",
    "create_harness",
    # UDT generation
    "UDTGenerationResult",
    "UDTCompileResult",
    "UDTGenerator",
    "UDTRegistry",
    "generate_udt",
    "compile_udt",
    "compile_udt_directory",
    # External dependencies
    "DependencyRegistry",
    "MockDataBlock",
    "NestedMockDB",
    "create_stub_type",
    "create_stub_from_spec",
    "create_mock_db",
    "create_nested_mock_db",
]
