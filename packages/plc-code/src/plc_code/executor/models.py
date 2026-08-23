"""Data models for SCL execution and transpilation.

This module defines the data structures used by the executor module
for transpiling SCL code to Python and executing it.
"""

import keyword
from collections.abc import Iterable
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


@dataclass(frozen=True)
class TranspileProblem:
    """One reason a transpile failed, with where in the SCL source it was found.

    Attributes
    ----------
    message : str
        Human-readable description.
    source_line : int | None
        The 1-based SCL source line the message points at, or ``None`` when it
        has no single line to point at (e.g. an unaccounted-for token range, or an
        exception raised outside any statement).
    """

    message: str
    source_line: int | None = None


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
    problems : list[TranspileProblem]
        Why transpilation failed, each with its SCL source line. Empty on success.
    warnings : list[str]
        List of warning messages (non-fatal issues).
    """

    success: bool
    python_code: str
    class_name: str = ""
    problems: list[TranspileProblem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[str]:
        """The problem messages alone, for a caller that only prints them."""
        return [problem.message for problem in self.problems]


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


def python_identifier(name: str) -> str:
    """The Python identifier a TIA name compiles to.

    A TIA block or variable name may hold spaces or other characters Python
    identifiers cannot (``"Main Loop"``, ``1X02-01``): each run of them becomes
    one ``_``, and a leading digit is prefixed with ``_``. A name that already is
    an identifier is returned unchanged, so every existing attribute keeps its
    spelling. The TIA name stays as is everywhere else -- only the generated
    Python (class, attributes, ``_inputs``/``_outputs`` tuples) uses this.
    """
    cleaned = name
    if not name.isidentifier():
        cleaned = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in name)
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        cleaned = cleaned.strip("_") or "Block"
        if cleaned[0].isdigit():
            cleaned = f"_{cleaned}"
    if keyword.iskeyword(cleaned) or not cleaned.isidentifier():
        cleaned = f"_{cleaned}"  # `class`, or a name only `isidentifier` rejects
    return cleaned


def identifier_collisions(names: Iterable[str]) -> list[tuple[str, str, str]]:
    """``(first, second, identifier)`` for every pair of names compiling to one identifier.

    :func:`python_identifier` is not injective (``a-b`` and ``a_b`` both give
    ``a_b``); a block declaring both would compile to one attribute, silently.
    The transpiler refuses such a block with a located problem.
    """
    seen: dict[str, str] = {}
    collisions: list[tuple[str, str, str]] = []
    for name in names:
        identifier = python_identifier(name)
        if identifier in seen and seen[identifier] != name:
            collisions.append((seen[identifier], name, identifier))
        seen.setdefault(identifier, name)
    return collisions


def python_class_name(block_name: str) -> str:
    """The Python class a block compiles to; see :func:`python_identifier`."""
    return python_identifier(block_name)
