"""Compile an F-LAD :class:`Block` into an interpreter-backed dataclass.

The generated class mirrors the shape produced by the SCL compile path
(:func:`plc_code.executor.transpiler.compile_block`): a ``_runtime`` field, one
field per VAR-section variable with type-correct defaults, and the
``_inputs``/``_outputs``/``_in_outs`` metadata tuples the test harness reads to
drive ``set_inputs``/``get_output``.

Field and metadata source is generated through the public seam
``SCLTranspiler.emit_fields_and_metadata`` the SCL path also feeds from, so
defaults and metadata stay byte-for-byte identical. Only the ``execute()`` body
diverges: instead of inlined SCL it delegates to a :class:`LadderInterpreter`
built once per class from the flattened ladder program.
"""

from __future__ import annotations

from typing import Any

from plc_code.executor.models import CompileResult, TranspileOptions, TranspileResult, python_class_name
from plc_code.executor.transpiler import SCLTranspiler
from plc_code.executor.types import TypeMapper
from plc_code.parser.ladder_builder import build_ladder_program
from plc_code.parser.models import Block


def _generate_fields_source(block: Block) -> str:
    """Emit the field + metadata lines for *block* at class-body indentation.

    Delegates to :meth:`SCLTranspiler.emit_fields_and_metadata` so the generated
    fields and metadata tuples are identical to those the SCL path produces for
    the same VAR sections.
    """
    return SCLTranspiler(
        block=block,
        options=TranspileOptions(),
        type_mapper=TypeMapper(),
    ).emit_fields_and_metadata()


def compile_ladder_block(block: Block, **_: Any) -> CompileResult:
    """Compile an F-LAD :class:`Block` to an interpreter-backed dataclass.

    Parameters
    ----------
    block : Block
        A parsed ladder block (``block.is_ladder`` is expected to be true).
    **_ : Any
        Ignored. Accepts the same keyword arguments as the SCL ``compile_block``
        (``options``, ``type_mapper``, ``extra_globals``, ``fb_type_resolver``)
        so it is a drop-in target for the routing branch.

    Returns
    -------
    CompileResult
        A successful result whose ``fb_class`` is a ``@dataclass`` exposing the
        same fields/metadata as the SCL path and an ``execute()`` that runs the
        ladder interpreter.
    """
    program = build_ladder_program(block)

    fields_source = _generate_fields_source(block)

    lines = [
        "@dataclass",
        f"class {python_class_name(block.name)}:",
        "    _runtime: PLCRuntime = field(repr=False)",
        "",
    ]
    lines.extend(fields_source.split("\n"))
    lines.extend(
        [
            "    # Built once per class from the flattened ladder program.",
            "    _interpreter = _LadderInterpreter(_program)",
            "",
            "    def execute(self) -> None:",
            '        """Execute one cycle of the ladder block."""',
            "        self._interpreter.run(self, self._runtime)",
        ]
    )
    source = "\n".join(lines)

    runtime_mod = __import__("plc_code.executor.runtime", fromlist=["PLCRuntime", "_AutoStruct"])
    interpreter_mod = __import__("plc_code.executor.ladder.interpreter", fromlist=["LadderInterpreter"])
    compile_globals: dict[str, Any] = {
        "dataclass": __import__("dataclasses").dataclass,
        "field": __import__("dataclasses").field,
        "PLCRuntime": runtime_mod.PLCRuntime,
        "_AutoStruct": runtime_mod._AutoStruct,
        "Any": __import__("typing").Any,
        "_LadderInterpreter": interpreter_mod.LadderInterpreter,
        "_program": program,
    }

    transpile_result = TranspileResult(
        success=True,
        python_code=source,
        class_name=python_class_name(block.name),
    )

    try:
        exec(source, compile_globals)  # noqa: S102
        fb_class = compile_globals.get(block.name)
        if fb_class is None:
            return CompileResult(
                success=False,
                fb_class=None,
                transpile_result=transpile_result,
                compile_error=(f"Class '{block.name}' not found after ladder compilation"),
            )
        return CompileResult(
            success=True,
            fb_class=fb_class,
            transpile_result=transpile_result,
        )
    except Exception as exc:  # noqa: BLE001
        return CompileResult(
            success=False,
            fb_class=None,
            transpile_result=transpile_result,
            compile_error=f"Ladder compilation error: {exc}",
        )
