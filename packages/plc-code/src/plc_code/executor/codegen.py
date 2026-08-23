"""Code generation utilities for SCL to Python transpilation.

Generation is native from the AST now (see ``plc_code.executor.renderer`` for
expressions and ``plc_code.executor.generator`` for statements). This module keeps
only what those two still depend on: :class:`CodeGenContext` (indentation
bookkeeping), the module-level operator/builtin lookup tables, and the two pure
formatters -- :meth:`ExpressionTranslator._build_named_call` and
:meth:`StatementTranslator._emit_named_call` -- that turn an already-rendered
``"Block"(...)`` call's arguments into the runtime's ``call_named_block(...)`` call
and output-assignment lines. Everything that used to rewrite SCL as text --
:meth:`ExpressionTranslator.translate`'s twelve ordered regex passes and the
statement-level dispatcher built on top of it -- is gone (Task 9): two corpus-wide
differentials proved the tree-driven renderer and generator equivalent to it first.
"""

from dataclasses import dataclass

#: SCL to Python operator mappings. Module-level (not a class field) so a caller who
#: needs the table itself -- rather than a full :class:`ExpressionTranslator` -- can
#: import it directly instead of instantiating the class just to read an attribute
#: that never varies between instances.
OPERATOR_MAP: dict[str, str] = {
    ":=": "=",
    "<>": "!=",
    "AND": "and",
    "OR": "or",
    "NOT": "not",
    "MOD": "%",
    "DIV": "//",
}

#: SCL built-in function mappings. Module-level for the same reason as
#: :data:`OPERATOR_MAP`.
BUILTIN_MAP: dict[str, str] = {
    "INT_TO_REAL": "float",
    "REAL_TO_INT": "int",
    "REAL_TO_DINT": "int",
    "INT_TO_USINT": "lambda x: x & 0xFF",
    "INT_TO_UINT": "lambda x: x & 0xFFFF",
    "INT_TO_DINT": "int",
    "DINT_TO_INT": "int",
    "UINT_TO_UDINT": "int",
    "UDINT_TO_INT": "int",
    "DINT_TO_REAL": "float",
    "BOOL_TO_INT": "int",
    # LReal / Real conversions — in Python float covers both
    "REAL_TO_LREAL": "float",
    "LREAL_TO_REAL": "float",
    "INT_TO_LREAL": "float",
    "DINT_TO_LREAL": "float",
    "LREAL_TO_INT": "int",
    "LREAL_TO_DINT": "int",
    "ABS": "abs",
    "SQR": "lambda x: x * x",
    "SQRT": "math.sqrt",
    "TRUNC": "math.trunc",
    # A duration is a float in seconds in the generated code; SCL's TIME is ms.
    "TIME_TO_DINT": "lambda t: int(round(t * 1000))",
    "DINT_TO_TIME": "lambda ms: ms / 1000.0",
    "DINT_TO_WORD": "lambda x: x & 0xFFFF",
    "INT_TO_WORD": "lambda x: x & 0xFFFF",
    "WORD_TO_INT": "lambda x: x - 0x10000 if x & 0x8000 else x",
    "BYTE_TO_SINT": "lambda x: x - 0x100 if x & 0x80 else x",
    "BYTE_TO_INT": "int",
    "SWAP_WORD": "lambda x: ((x & 0xFF) << 8) | ((x >> 8) & 0xFF)",
    "BCD16_TO_INT": "lambda x: int(format(x, 'x'))",
    # Interrupt control: nothing to disable in the harness; the status is 0 (ok).
    "DIS_AIRT": "lambda: 0",
    "EN_AIRT": "lambda: 0",
    "SIN": "math.sin",
    "COS": "math.cos",
    "TAN": "math.tan",
    "ASIN": "math.asin",
    "ACOS": "math.acos",
    "ATAN": "math.atan",
    "ATAN2": "math.atan2",
    "LN": "math.log",
    "EXP": "math.exp",
    "LOWER_BOUND": "lambda arr, dim: 0",
    "UPPER_BOUND": (
        "lambda arr, dim: (len(arr[0]) - 1 if dim == 2 and arr "
        "and isinstance(arr[0], (list, tuple)) else len(arr) - 1)"
    ),
}


@dataclass
class CodeGenContext:
    """Context for code generation.

    Attributes
    ----------
    indent_level : int
        Current indentation level.
    indent_str : str
        String to use for one indentation level.
    """

    indent_level: int = 0
    indent_str: str = "    "

    def indent(self) -> str:
        """Get the current indentation string."""
        return self.indent_str * self.indent_level

    def push(self) -> "CodeGenContext":
        """Create a new context with increased indentation."""
        return CodeGenContext(
            indent_level=self.indent_level + 1,
            indent_str=self.indent_str,
        )


@dataclass
class ExpressionTranslator:
    """Builds the one runtime call form ``plc_code.executor.renderer`` cannot build alone.

    Everything this class used to do -- rewriting a whole SCL expression as Python text
    through ordered regex passes -- is now done natively by
    ``plc_code.executor.renderer.render``, which has its own visitor for every
    expression node. The one shape ``render`` still routes through this class is a
    quoted block call used in expression position (``"Scaling"(input := #x)``): see
    :meth:`_build_named_call` and ``renderer._render_named_call``, which calls it with
    every argument already rendered.
    """

    def _build_named_call(self, block_name: str, arguments: list[tuple[str, str]]) -> str:
        """Build a ``call_named_block(...)`` expression returning the FUNCTION's value.

        A pure formatter: every argument value must already be rendered Python text by
        the time it reaches here -- neither this method nor
        :meth:`StatementTranslator._emit_named_call` call anything that reads or rewrites
        SCL text; the caller (``plc_code.executor.renderer._render_named_call``) renders
        each argument through ``render`` first.

        Parameters
        ----------
        block_name : str
            The sub-block name (without quotes).
        arguments : list[tuple[str, str]]
            One ``(name, rendered_value)`` pair per ``:=`` (input) parameter to bind, in
            source order. An argument written ``name => value`` (output-bound) is not
            included here -- the caller filters it out before calling this, since an
            expression-position call can only return one value; an argument with no
            name arrives already bound to its declared parameter name.

        Returns
        -------
        str
            A Python expression that calls the sub-block and evaluates to its return
            value.
        """
        inputs = [f'"{name}": {value}' for name, value in arguments]
        inputs_dict = "{" + ", ".join(inputs) + "}"
        return f'self._runtime.call_named_block("{block_name}", {inputs_dict}, {{}})["{block_name}"]'


@dataclass
class StatementTranslator:
    """Builds the one runtime call form ``plc_code.executor.generator`` cannot build alone.

    Everything this class used to do -- rewriting a rebuilt SCL statement line as Python
    text, dispatching between assignment/FB-call/quoted-call/control-flow shapes by
    regular expression -- is now done natively by
    ``plc_code.executor.generator.generate_statements``, which reads each statement's own
    parsed tree instead. The one shape the generator still routes through this class is a
    quoted block call (``"Block"(x := #a, out => #b);``, whether a standalone statement or
    the right-hand side of an assignment): see :meth:`_emit_named_call`, called by
    ``generator._generate_named_call_statement`` and
    ``generator._generate_named_call_assignment`` with every argument already rendered.
    """

    def _emit_named_call(
        self, block_name: str, arguments: list[tuple[str, str, bool, bool]]
    ) -> tuple[list[str], str]:
        """Emit the Python statements for a ``"BlockName"(...)`` call.

        A pure formatter: every argument value must already be rendered Python text, and
        the in-out write-back decision already made, by the time either reaches here --
        see :meth:`ExpressionTranslator._build_named_call`'s docstring, which this
        mirrors. This does not inspect a value's own text to decide whether to emit a
        write-back line: a rendered value's text cannot always answer that correctly (a
        global-DB member access whose DB name contains a character the old
        ``GLOBAL_DB_PATTERN`` regex could never match renders identically to a plain
        local reference under ``render``, but must not be treated as an in-out
        candidate the way a plain local reference is) -- the caller
        (``generator._is_write_back_candidate``) makes that decision from the tree and
        passes it in as ``write_back``. Shared by the standalone-call path and the
        return-value-assignment path so both wire ``=>`` outputs (and ``:=`` in-out
        write-back) identically.

        Parameters
        ----------
        block_name : str
            The sub-block name (without quotes).
        arguments : list[tuple[str, str, bool, bool]]
            One ``(name, rendered_value, is_output, write_back)`` tuple per bound
            parameter, in source order -- ``write_back`` is only consulted when
            ``is_output`` is False.

        Returns
        -------
        tuple[list[str], str]
            The call + output-assignment statements, and the result-dict variable name
            (so the caller can also read the return value).
        """
        # Categorise parameters:
        #   :=  ->  input (or in-out passed in)
        #   =>  ->  output assignment
        input_params: dict[str, tuple[str, bool]] = {}  # name -> (rendered value expr, write_back)
        output_params: list[tuple[str, str]] = []  # (block_output_name, target_var_expr)

        for name, value_expr, is_output, write_back in arguments:
            if is_output:
                output_params.append((name, value_expr))
            else:
                input_params[name] = (value_expr, write_back)

        # Build Python statements
        # 1. Call the sub-block and capture its result dict
        result_var = f"_sub_{block_name.replace(' ', '_')}_result"
        inputs_dict = "{" + ", ".join(f'"{k}": {v}' for k, (v, _) in input_params.items()) + "}"
        call_line = f"{result_var} = self._runtime.call_named_block(" f'"{block_name}", {inputs_dict}, {{}})'
        result_lines = [call_line]

        # 2. Assign output parameters from result dict
        for out_name, target_expr in output_params:
            result_lines.append(f'{target_expr} = {result_var}["{out_name}"]')

        # 3. For `:=` params that are also outputs (i.e. in-out params),
        #    we read them back from the result dict if they appear there.
        #    The `:=` in-out semantics: value goes in, updated value comes out.
        #    We handle this by updating the target variable if the param appears in result.
        for in_name, (value_expr, write_back) in input_params.items():
            if write_back:
                # This param may be an in-out: write back if present in result
                result_lines.append(
                    f'if "{in_name}" in {result_var}: {value_expr} = {result_var}["{in_name}"]'
                )

        return result_lines, result_var
