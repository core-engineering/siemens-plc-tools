"""Data models for SCL execution and transpilation.

This module defines the data structures used by the executor module
for transpiling SCL code to Python and executing it.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TranspileOptions:
    """Configuration options for SCL transpilation.

    Attributes
    ----------
    generate_type_hints : bool
        Whether to include Python type hints in generated code.
    include_docstrings : bool
        Whether to include docstrings from block headers.
    include_comments : bool
        Whether to include inline comments in generated code.
    """

    generate_type_hints: bool = True
    include_docstrings: bool = True
    include_comments: bool = True


@dataclass
class TranspileResult:
    """Result of transpiling an SCL block to Python.

    Attributes
    ----------
    success : bool
        Whether transpilation succeeded.
    python_code : str
        The generated Python source code.
    class_name : str
        Name of the generated class.
    errors : list[str]
        List of error messages if transpilation failed.
    warnings : list[str]
        List of warning messages (non-fatal issues).
    error_lines : list[int | None]
        Parallel to ``errors``: the 1-based SCL source line each message
        points at, or ``None`` when a message has no single line to point at
        (e.g. an unaccounted-for token range). Carries the location as data,
        for a caller that wants it without re-parsing the message string.
    """

    success: bool
    python_code: str
    class_name: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error_lines: list[int | None] = field(default_factory=list)


@dataclass
class CompileResult:
    """Result of compiling transpiled Python code.

    Attributes
    ----------
    success : bool
        Whether compilation succeeded.
    fb_class : type | None
        The compiled function block class, or None if failed.
    transpile_result : TranspileResult
        The underlying transpilation result.
    compile_error : str | None
        Compilation error message if failed.
    """

    success: bool
    fb_class: type | None
    transpile_result: TranspileResult
    compile_error: str | None = None


@dataclass
class ExecutionContext:
    """Context for a single PLC execution cycle.

    Attributes
    ----------
    cycle_number : int
        Current cycle number (0-indexed).
    cycle_time : float
        Duration of one cycle in seconds.
    current_time : float
        Current simulation time in seconds.
    """

    cycle_number: int = 0
    cycle_time: float = 0.010  # 10ms default
    current_time: float = 0.0


@dataclass
class PLCValue:
    """Wrapper for a PLC value with type information.

    Attributes
    ----------
    value : Any
        The actual value.
    scl_type : str
        The SCL type string (e.g., "Bool", "Real", "Int").
    """

    value: Any
    scl_type: str
