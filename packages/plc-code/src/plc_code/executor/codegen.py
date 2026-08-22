"""Code generation utilities for SCL to Python transpilation.

This module provides utilities for generating Python code from SCL
constructs, including expression translation and statement generation.
"""

import re
from dataclasses import dataclass, field

from plc_code.executor.types import parse_time_literal


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
    "SQRT": "math.sqrt",
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
class ExpressionTranslator:
    """Translates SCL expressions to Python expressions.

    This class handles the conversion of SCL syntax to equivalent
    Python syntax, including variable references, operators, and
    function calls.
    """

    # Patterns for SCL constructs
    INSTANCE_VAR_PATTERN = re.compile(r"#(\w+)")
    # ``"DbName".member`` — the parser joins tokens with spaces, so tolerate
    # whitespace around the dot (e.g. ``"dbConst" . RESULT_WORKING``).
    GLOBAL_DB_PATTERN = re.compile(r'"(\w+)"\s*\.\s*(.+)')
    LIBRARY_TYPE_PATTERN = re.compile(r"_\.(\w+)")
    ARRAY_ACCESS_PATTERN = re.compile(r"\[([^\]]+)\]")
    STRING_KEY_PATTERN = re.compile(r'\["([^"]+)"\]')

    # SCL to Python operator mappings -- module-level constant, see :data:`OPERATOR_MAP`.
    OPERATOR_MAP: dict[str, str] = field(default_factory=lambda: OPERATOR_MAP)

    # SCL built-in function mappings -- module-level constant, see :data:`BUILTIN_MAP`.
    BUILTIN_MAP: dict[str, str] = field(default_factory=lambda: BUILTIN_MAP)

    def translate(self, scl_expr: str) -> str:
        """Translate an SCL expression to Python.

        Parameters
        ----------
        scl_expr : str
            The SCL expression to translate.

        Returns
        -------
        str
            The equivalent Python expression.
        """
        result = scl_expr.strip()

        # Handle empty expression
        if not result:
            return result

        # Protect SCL string literals FIRST: every pass below rewrites the raw
        # text, so a literal would be translated as if it were code
        # (``'CASE#1'`` -> ``'CASEself.1'``, ``'a = b'`` -> ``'a == b'``,
        # ``'TRUE'`` -> ``'True'``).  The block still compiles, so the damage is
        # silent — only the string content is wrong.  Same placeholder trick the
        # named-call extraction below uses.
        result, string_literals = self._extract_string_literals(result)

        # Normalize spaced instance variable references: "# var" -> "#var"
        # The parser may insert a space between '#' and the identifier.
        result = re.sub(r"#\s+(\w)", r"#\1", result)

        # Extract quoted-name sub-block calls used in expression position
        # (e.g. inside an IF condition or on the RHS of an assignment) and protect
        # them as placeholders.  Each call is fully translated here, so the operator
        # translation below cannot mangle the ``:=`` of its parameters.
        result, named_call_placeholders = self._extract_named_calls(result)

        # Translate SCL hex literals (16#XXXX -> 0xXXXX) BEFORE instance variables:
        # otherwise the ``#`` of ``16#8201`` is mistaken for an instance-variable
        # prefix and ``#8201`` becomes ``self.8201``.
        result = self._translate_hex_literals(result)

        # Translate SCL duration literals (T#5s -> 5.0) for the same reason: the ``#``
        # of ``T#5s`` would otherwise be taken for an instance-variable prefix and
        # ``T#0s`` would become ``T self.0 s``, which is not valid Python.
        result = self._translate_time_literals(result)

        # Replace instance variables (#var -> self.var)
        result = self.INSTANCE_VAR_PATTERN.sub(r"self.\1", result)

        # Replace global DB access ("DB".member -> self._runtime.global_dbs["DB"].member)
        result = self._translate_global_db(result)

        # Rewrite LOWER_BOUND/UPPER_BOUND named-param calls before operator translation
        # so that ARR := and DIM := are still intact
        result = self._translate_array_bounds(result)

        # Replace operators
        result = self._translate_operators(result)

        # Replace built-in functions
        result = self._translate_builtins(result)

        # Handle boolean literals
        result = self._translate_booleans(result)

        # Translate multi-index array access: arr[i, j] -> arr[i][j]
        result = self._translate_multi_index(result)

        # Restore protected sub-block calls (already fully translated Python).
        for placeholder, code in named_call_placeholders.items():
            result = result.replace(placeholder, code)

        # Restore string literals last: a protected sub-block call may carry one
        # in its arguments, so its restored Python can still hold a placeholder.
        for placeholder, literal in string_literals.items():
            result = result.replace(placeholder, literal)

        return result

    def _extract_string_literals(self, expr: str) -> tuple[str, dict[str, str]]:
        """Replace single-quoted SCL string literals with inert placeholders.

        SCL escapes a quote by doubling it (``'it''s'``), so the scan cannot stop
        at the first closing quote.  Double-quoted spans are *symbol names*, not
        literals: they are copied through untouched because the passes that
        follow (global-DB access, named sub-block calls) still need to see them.

        Parameters
        ----------
        expr : str
            The raw SCL expression.

        Returns
        -------
        tuple[str, dict[str, str]]
            The expression with each literal replaced by a ``__SLIT<n>__``
            placeholder, plus a mapping of placeholder -> original literal.
            Placeholders contain only word characters, so none of the
            regex-based passes that run afterwards can match inside them.
        """
        placeholders: dict[str, str] = {}
        out: list[str] = []
        i = 0
        length = len(expr)
        while i < length:
            ch = expr[i]
            if ch not in "'\"":
                out.append(ch)
                i += 1
                continue
            # Walk to the closing delimiter, honouring the doubled-quote escape.
            end = i + 1
            while end < length:
                if expr[end] == ch:
                    if end + 1 < length and expr[end + 1] == ch:
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            span = expr[i:end]
            if ch == "'":
                key = f"__SLIT{len(placeholders)}__"
                placeholders[key] = span
                out.append(key)
            else:
                out.append(span)
            i = end
        return "".join(out), placeholders

    # Opening of a quoted-name block call: "BlockName"(
    _NAMED_CALL_OPEN = re.compile(r'"([^"]+)"\s*\(')

    def _extract_named_calls(self, expr: str) -> tuple[str, dict[str, str]]:
        """Replace ``"Block"(args)`` calls with placeholders, fully translating each.

        Parameters
        ----------
        expr : str
            The (instance-variable-normalised) SCL expression.

        Returns
        -------
        tuple[str, dict[str, str]]
            The expression with each call replaced by a ``__NCALL<n>__``
            placeholder, plus a mapping of placeholder -> Python call expression.
            Placeholders contain only word characters, so the regex-based operator
            translation that runs afterwards leaves them untouched.
        """
        placeholders: dict[str, str] = {}
        out: list[str] = []
        i = 0
        n = len(expr)
        while i < n:
            match = self._NAMED_CALL_OPEN.match(expr, i)
            if match:
                # Find the matching closing parenthesis of the argument list.
                depth = 1
                j = match.end()
                while j < n and depth > 0:
                    if expr[j] == "(":
                        depth += 1
                    elif expr[j] == ")":
                        depth -= 1
                    j += 1
                if depth == 0:
                    params_str = expr[match.end() : j - 1]
                    placeholder = f"__NCALL{len(placeholders)}__"
                    arguments = self._translate_named_call_arguments(params_str)
                    placeholders[placeholder] = self._build_named_call(match.group(1), arguments)
                    out.append(placeholder)
                    i = j
                    continue
            out.append(expr[i])
            i += 1
        return "".join(out), placeholders

    def _translate_named_call_arguments(self, params_str: str) -> list[tuple[str, str]]:
        """Parse and translate a raw ``:=`` argument list's *input* parameters.

        The text-carving half of what ``_build_named_call`` used to do in one step,
        kept apart from it so that function can be a pure formatter -- see its own
        docstring. Only ``:=`` (input) parameters are kept, matching
        ``_build_named_call``'s pre-existing filter: an unnamed or ``=>`` (output)
        parameter contributes nothing to a quoted call used in expression position,
        since that position can only return one value.

        Parameters
        ----------
        params_str : str
            The raw argument list between the outer parentheses.

        Returns
        -------
        list[tuple[str, str]]
            One ``(name, translated_value)`` pair per ``:=`` parameter, in source
            order. ``name`` is the raw stripped text before ``:=`` -- including its
            own quote characters when the parameter name itself was written quoted
            (``"x" := #a``), so :func:`_build_named_call`'s single re-wrap of it
            reproduces that shape's pre-existing double-quoting exactly as before.
        """
        arguments: list[tuple[str, str]] = []
        for param in self._split_top_level_commas(params_str):
            param = param.strip()
            if not param:
                continue
            param = re.sub(r":\s*=", ":=", param)
            if ":=" in param:
                name, value = param.split(":=", 1)
                # Recursively translate the argument value (handles #vars, operators...).
                arguments.append((name.strip(), self.translate(value.strip())))
        return arguments

    def _build_named_call(self, block_name: str, arguments: list[tuple[str, str]]) -> str:
        """Build a ``call_named_block(...)`` expression returning the FUNCTION's value.

        A pure formatter: every argument value must already be rendered Python text
        by the time it reaches here. Neither this function nor ``_emit_named_call``
        below call ``translate`` or carve a raw parameter-list string -- the text
        path's own caller (:func:`_extract_named_calls`, via
        :func:`_translate_named_call_arguments`) does that translation itself before
        calling this; the tree path's caller
        (``plc_code.executor.renderer._render_named_call``) calls
        ``plc_code.executor.renderer.render`` instead. This split is what lets the
        renderer hand this function already-rendered argument text directly, with no
        placeholder-and-substitute step in between (see that function's own
        docstring for what the placeholder step used to guard against).

        Parameters
        ----------
        block_name : str
            The sub-block name (without quotes).
        arguments : list[tuple[str, str]]
            One ``(name, rendered_value)`` pair per ``:=`` (input) parameter to bind,
            in source order -- see :func:`_translate_named_call_arguments` for how
            the text path builds this list.

        Returns
        -------
        str
            A Python expression that calls the sub-block and evaluates to its
            return value.
        """
        inputs = [f'"{name}": {value}' for name, value in arguments]
        inputs_dict = "{" + ", ".join(inputs) + "}"
        return f'self._runtime.call_named_block("{block_name}", {inputs_dict}, {{}})["{block_name}"]'

    @staticmethod
    def _split_top_level_commas(text: str) -> list[str]:
        """Split ``text`` on commas that are not nested inside ``()`` or ``[]``."""
        parts: list[str] = []
        depth = 0
        current = ""
        for ch in text:
            if ch in "([":
                depth += 1
                current += ch
            elif ch in ")]":
                depth -= 1
                current += ch
            elif ch == "," and depth == 0:
                parts.append(current)
                current = ""
            else:
                current += ch
        if current.strip():
            parts.append(current)
        return parts

    def _translate_global_db(self, expr: str) -> str:
        """Translate global data block access.

        Parameters
        ----------
        expr : str
            Expression containing DB access.

        Returns
        -------
        str
            Translated expression.
        """

        def replace_db(match: re.Match[str]) -> str:
            db_name = match.group(1)
            member = match.group(2)
            # Recursively translate the member access
            translated_member = self.translate(member)
            return f'self._runtime.global_dbs["{db_name}"].{translated_member}'

        return self.GLOBAL_DB_PATTERN.sub(replace_db, expr)

    def _translate_hex_literals(self, expr: str) -> str:
        """Translate SCL hex literals (16#XXXX) to Python hex literals (0xXXXX).

        Parameters
        ----------
        expr : str
            Expression potentially containing SCL hex literals.

        Returns
        -------
        str
            Expression with hex literals in Python format.
        """
        # Tolerate whitespace around ``#`` — the parser joins ``16``, ``#`` and the
        # digits into ``16 # 8201`` when a hex literal appears in code (rather than
        # as a variable default, which is parsed verbatim).
        return re.sub(
            r"\b16\s*#\s*([0-9A-Fa-f]+)\b",
            lambda m: hex(int(m.group(1), 16)),
            expr,
        )

    # A duration literal: a TIME prefix, ``#``, then one or more ``<number><unit>``
    # components.  Region-content reconstruction spaces the tokens out, so
    # ``T#150ms`` also arrives as ``T # 150 ms`` and ``T#1h30m`` as ``T # 1 h30m``.
    _TIME_LITERAL_PATTERN = re.compile(
        r"\b(?:LTIME|TIME|LT|T)\s*#\s*((?:\d+\s*(?:ms|s|m|h|d)\s*)+)",
        re.IGNORECASE,
    )

    def _translate_time_literals(self, expr: str) -> str:
        """Translate SCL duration literals (T#5s) to seconds as a float.

        The harness stores a ``Time`` value as a float number of seconds, which is
        what ``parse_time_literal`` returns, so the literal is replaced by its value.
        Date and time-of-day literals (``D#``, ``TOD#``, ``DT#``) are not durations
        and are left untouched.

        Parameters
        ----------
        expr : str
            Expression potentially containing SCL duration literals.

        Returns
        -------
        str
            Expression with duration literals replaced by their value in seconds.
        """
        return self._TIME_LITERAL_PATTERN.sub(
            lambda m: repr(parse_time_literal("T#" + re.sub(r"\s+", "", m.group(1)))),
            expr,
        )

    def _translate_operators(self, expr: str) -> str:
        """Translate SCL operators to Python.

        Parameters
        ----------
        expr : str
            Expression containing operators.

        Returns
        -------
        str
            Expression with translated operators.
        """
        result = expr

        # Ensure proper spacing around keyword operators AND/OR.
        # Use word boundaries to avoid splitting variable names that contain "or"/"and"
        # as a substring (e.g. "error", "forward"). The \b boundary ensures we only
        # match OR/AND when it stands alone as a token, not embedded in an identifier.
        result = re.sub(r"\b(AND)\b", r" \1 ", result, flags=re.IGNORECASE)
        result = re.sub(r"\b(OR)\b", r" \1 ", result, flags=re.IGNORECASE)

        # Add space after NOT if followed by non-space (except for !=)
        result = re.sub(r"\b(NOT)([^\s=])", r"\1 \2", result, flags=re.IGNORECASE)

        # Normalize spaced forms of multi-char operators produced by the TIA Portal
        # lexer/parser, which emits comparison operators with internal spaces:
        #   "< >"  →  "<>"   (not-equal)
        #   "< ="  →  "<="   (less-or-equal)
        #   "> ="  →  ">="   (greater-or-equal)
        # These must be collapsed BEFORE the standalone-'=' rule runs, otherwise
        # "< =" becomes "< ==" (incorrect Python).
        result = re.sub(r"<\s+>", "<>", result)
        result = re.sub(r"<\s+=", "<=", result)
        result = re.sub(r">\s+=", ">=", result)

        # Replace operators (case-insensitive for keywords)
        for scl_op, py_op in self.OPERATOR_MAP.items():
            # Use word boundaries for keyword operators
            if scl_op.isalpha():
                pattern = re.compile(rf"\b{scl_op}\b", re.IGNORECASE)
                result = pattern.sub(py_op, result)
            else:
                result = result.replace(scl_op, py_op)

        # Handle standalone = as == for comparison (not := or => or == or !=)
        # Match = that is not preceded by : or = or > or ! or followed by > or =
        result = re.sub(r"(?<![:<>=!])=(?![>=])", " == ", result)

        # Clean up any double spaces
        result = re.sub(r"  +", " ", result)

        return result

    # Pattern matching LOWER_BOUND/UPPER_BOUND with named params:
    # LOWER_BOUND(ARR := expr, DIM := expr)  or  UPPER_BOUND(ARR := expr, DIM := dimexpr)
    # Captured groups: (1) func name, (2) ARR value, (3) DIM value
    _ARRAY_BOUND_PATTERN = re.compile(
        r"\b(LOWER_BOUND|UPPER_BOUND)\s*\(\s*ARR\s*:=\s*((?:[^,()]|\((?:[^()]|\([^()]*\))*\))+?)\s*"
        r",\s*DIM\s*:=\s*((?:[^()]|\((?:[^()]|\([^()]*\))*\))*?)\s*\)",
        re.IGNORECASE,
    )

    def _translate_array_bounds(self, expr: str) -> str:
        """Rewrite LOWER_BOUND/UPPER_BOUND named-parameter calls to Python lambda invocations.

        Transforms ``LOWER_BOUND(ARR := arr, DIM := dim)`` into the positional
        lambda call form used by the BUILTIN_MAP entries.

        Parameters
        ----------
        expr : str
            SCL expression potentially containing LOWER_BOUND/UPPER_BOUND calls.

        Returns
        -------
        str
            Expression with array-bound calls rewritten.
        """

        def _replace(match: re.Match[str]) -> str:
            func_name = match.group(1).upper()
            arr_expr = match.group(2).strip()
            dim_expr = match.group(3).strip()
            py_func = self.BUILTIN_MAP[func_name]
            return f"({py_func})({arr_expr}, {dim_expr})"

        return self._ARRAY_BOUND_PATTERN.sub(_replace, expr)

    def _translate_builtins(self, expr: str) -> str:
        """Translate SCL built-in functions to Python.

        Parameters
        ----------
        expr : str
            Expression containing built-in function calls.

        Returns
        -------
        str
            Expression with translated functions.
        """
        result = expr

        for scl_func, py_func in self.BUILTIN_MAP.items():
            # Skip LOWER_BOUND/UPPER_BOUND — handled earlier in _translate_array_bounds
            if scl_func in ("LOWER_BOUND", "UPPER_BOUND"):
                continue
            # Match function calls: FUNC_NAME(...)
            pattern = re.compile(rf"\b{scl_func}\s*\(", re.IGNORECASE)
            result = pattern.sub(f"{py_func}(", result)

        return result

    def _translate_booleans(self, expr: str) -> str:
        """Translate SCL boolean literals to Python.

        Parameters
        ----------
        expr : str
            Expression containing boolean literals.

        Returns
        -------
        str
            Expression with Python booleans.
        """
        # Replace TRUE/FALSE with True/False (case-insensitive, word boundary)
        result = re.sub(r"\bTRUE\b", "True", expr, flags=re.IGNORECASE)
        result = re.sub(r"\bFALSE\b", "False", result, flags=re.IGNORECASE)
        return result

    def _translate_multi_index(self, expr: str) -> str:
        """Translate multi-dimensional SCL array access to Python chained indexing.

        SCL supports ``arr[i, j]`` (comma-separated indices) for 2D arrays, but
        Python lists-of-lists require ``arr[i][j]``.  Any ``[a, b]`` subscript
        found in the expression is rewritten as ``[a][b]``.

        String literals and single-index accesses are left unchanged.

        Parameters
        ----------
        expr : str
            Expression potentially containing multi-index subscripts.

        Returns
        -------
        str
            Expression with multi-index subscripts rewritten.
        """

        def _rewrite_bracket(match: re.Match[str]) -> str:
            content = match.group(1)
            # Only rewrite if there is a comma that is NOT inside quotes or parens
            # Simple heuristic: split on top-level commas
            parts: list[str] = []
            current = ""
            depth = 0
            for ch in content:
                if ch in "([":
                    depth += 1
                    current += ch
                elif ch in ")]":
                    depth -= 1
                    current += ch
                elif ch == "," and depth == 0:
                    parts.append(current.strip())
                    current = ""
                else:
                    current += ch
            if current.strip():
                parts.append(current.strip())

            if len(parts) <= 1:
                # Single index — no change
                return f"[{content}]"

            # Multi-index — chain: [a][b][c]...
            return "".join(f"[{p}]" for p in parts)

        return re.sub(r"\[([^\[\]]*)\]", _rewrite_bracket, expr)


@dataclass
class StatementTranslator:
    """Translates SCL statements to Python statements.

    This class handles control flow statements like IF, CASE, WHILE,
    FOR, and function/FB calls.
    """

    expr_translator: ExpressionTranslator = field(default_factory=ExpressionTranslator)

    def translate_assignment(self, scl_stmt: str) -> str:
        """Translate an SCL assignment statement.

        Parameters
        ----------
        scl_stmt : str
            SCL assignment statement (e.g., "#var := value;").

        Returns
        -------
        str
            Python assignment statement.
        """
        # Remove trailing semicolon
        stmt = scl_stmt.rstrip(";").strip()

        # Split on := and translate both sides
        if ":=" in stmt:
            parts = stmt.split(":=", 1)
            lhs = self.expr_translator.translate(parts[0].strip())
            rhs = self.expr_translator.translate(parts[1].strip())
            return f"{lhs} = {rhs}"

        return self.expr_translator.translate(stmt)

    def translate_if_condition(self, condition: str) -> str:
        """Translate an IF condition.

        Parameters
        ----------
        condition : str
            SCL IF condition.

        Returns
        -------
        str
            Python if condition.
        """
        return self.expr_translator.translate(condition)

    def translate_fb_call(self, scl_call: str) -> list[str]:
        """Translate an FB instance call to Python statements.

        SCL FB calls use := for input params and => for output params:
        #timer(IN := #input, PT := #delay, Q => #output);

        Parameters
        ----------
        scl_call : str
            SCL FB call statement.

        Returns
        -------
        list[str]
            List of Python statements (call + output assignments).
        """
        # Remove trailing semicolon and normalize spaces
        call = scl_call.rstrip(";").strip()

        # Normalize: "# name" -> "#name", "= >" -> "=>"
        call = re.sub(r"#\s+", "#", call)
        call = re.sub(r"=\s*>", "=>", call)
        call = re.sub(r":\s*=", ":=", call)

        # Parse: #instance(param1 := val1, param2 => var2)
        match = re.match(r"#(\w+)\s*\(([^)]*)\)", call)
        if not match:
            # Not an FB call, return as translated expression
            return [self.expr_translator.translate(call)]

        instance_name = match.group(1)
        params_str = match.group(2)

        # Parse parameters
        input_params: list[str] = []
        output_assignments: list[str] = []

        if params_str.strip():
            # Split by comma, but be careful with nested parentheses
            params = self._split_params(params_str)

            for param in params:
                param = param.strip()
                if ":=" in param:
                    # Input parameter
                    name, value = param.split(":=", 1)
                    name = name.strip()
                    value = self.expr_translator.translate(value.strip())
                    input_params.append(f"{name}={value}")
                elif "=>" in param:
                    # Output parameter
                    name, target = param.split("=>", 1)
                    name = name.strip()
                    target = self.expr_translator.translate(target.strip())
                    output_assignments.append(f"{target} = self.{instance_name}.{name}")

        # Build the call
        result = []
        call_params = ", ".join(input_params)

        # For timers, add clock parameter
        if any(timer_type in instance_name.lower() for timer_type in ["timer", "ton", "tof", "tp"]):
            if call_params:
                call_params += ", clock=self._runtime.clock"
            else:
                call_params = "clock=self._runtime.clock"

        result.append(f"self.{instance_name}({call_params})")

        # Add output assignments
        result.extend(output_assignments)

        return result

    def _split_params(self, params_str: str) -> list[str]:
        """Split parameter string by commas, respecting parentheses.

        Parameters
        ----------
        params_str : str
            Parameter string from FB call.

        Returns
        -------
        list[str]
            List of individual parameters.
        """
        params = []
        current = ""
        depth = 0

        for char in params_str:
            if char == "(":
                depth += 1
                current += char
            elif char == ")":
                depth -= 1
                current += char
            elif char == "," and depth == 0:
                params.append(current)
                current = ""
            else:
                current += char

        if current.strip():
            params.append(current)

        return params

    def _translate_named_block_call(self, line: str) -> list[str] | None:
        """Translate a ``"BlockName"(param := val, ...)`` call to Python.

        This handles SCL FUNCTION/FUNCTION_BLOCK calls using the quoted-name
        syntax, dispatching to ``self._runtime.call_named_block()``.

        Parameters
        ----------
        line : str
            The SCL statement line.

        Returns
        -------
        list[str] | None
            Translated Python statements, or ``None`` if the line is not a
            quoted-name block call.
        """
        # Quick rejection: must start with a double-quote
        stripped = line.strip()
        if not stripped.startswith('"'):
            return None

        # Try to match "BlockName"(...)
        # We need to handle the full parameter list which may contain nested parens
        # Step 1: find the closing paren of the argument list
        match = re.match(r'^"([^"]+)"\s*\(', stripped)
        if not match:
            return None

        block_name = match.group(1)
        paren_start = match.end()  # position just after the opening '('

        # Find matching closing paren
        depth = 1
        pos = paren_start
        while pos < len(stripped) and depth > 0:
            if stripped[pos] == "(":
                depth += 1
            elif stripped[pos] == ")":
                depth -= 1
            pos += 1

        if depth != 0:
            return None  # unbalanced parens - not a valid call

        params_str = stripped[paren_start : pos - 1]  # content between outer parens

        return self._emit_named_call(block_name, self._translate_named_call_bindings(params_str))[0]

    def _translate_named_call_bindings(self, params_str: str) -> list[tuple[str, str, bool, bool]]:
        """Parse and translate a raw ``:=``/``=>`` argument list into bound-argument tuples.

        The text-carving half of what ``_emit_named_call`` used to do in one step, kept
        apart from it so that function can be a pure formatter -- see its own docstring.
        This includes the in-out write-back decision, computed here from the *translated*
        value text exactly as ``_emit_named_call`` used to compute it internally (see
        ``write_back`` below) -- moved here, not dropped, because it is itself a piece of
        text-carving no pure formatter should still do.

        Parameters
        ----------
        params_str : str
            The raw argument list between the outer parentheses.

        Returns
        -------
        list[tuple[str, str, bool, bool]]
            One ``(name, translated_value, is_output, write_back)`` tuple per
            ``:=``/``=>`` parameter, in source order -- ``is_output`` True for ``=>``,
            False for ``:=``; ``write_back`` (only meaningful when ``is_output`` is
            False) True when the translated value is a bare ``self.``-rooted,
            space-free reference, the same in-out candidate test
            ``_emit_named_call`` used to apply to its own translated text. An
            unnamed (positional) parameter is dropped, matching the pre-existing
            behaviour: a bare value satisfies neither the ``":=" in param`` nor the
            ``"=>" in param`` check.
        """
        bindings: list[tuple[str, str, bool, bool]] = []
        for param in self._split_params(params_str):
            param = param.strip()
            if not param:
                continue

            # Normalize `:=` and `=>`
            param = re.sub(r":\s*=", ":=", param)
            param = re.sub(r"=\s*>", "=>", param)

            if ":=" in param:
                name, value = param.split(":=", 1)
                translated = self.expr_translator.translate(value.strip())
                write_back = translated.startswith("self.") and " " not in translated.strip()
                bindings.append((name.strip(), translated, False, write_back))
            elif "=>" in param:
                name, target = param.split("=>", 1)
                bindings.append((name.strip(), self.expr_translator.translate(target.strip()), True, False))
        return bindings

    def _emit_named_call(
        self, block_name: str, arguments: list[tuple[str, str, bool, bool]]
    ) -> tuple[list[str], str]:
        """Emit the Python statements for a ``"BlockName"(...)`` call.

        A pure formatter: every argument value must already be rendered Python text, and
        the in-out write-back decision already made, by the time either reaches here --
        see :func:`ExpressionTranslator._build_named_call`'s docstring, which this
        mirrors. This function no longer inspects a value's own text to decide whether to
        emit a write-back line (a form of string-carving a pure formatter should not do,
        and one that a rendered value's text cannot always answer correctly -- see
        :func:`_translate_named_call_bindings` and
        ``plc_code.executor.generator._is_write_back_candidate`` for why the tree-based
        and text-based verdicts can legitimately disagree for the same argument, e.g. a
        global-DB member access whose DB name contains a character
        ``GLOBAL_DB_PATTERN`` cannot match). Shared by the standalone-call path and the
        return-value-assignment path so both wire ``=>`` outputs (and ``:=`` in-out
        write-back) identically.

        Parameters
        ----------
        block_name : str
            The sub-block name (without quotes).
        arguments : list[tuple[str, str, bool, bool]]
            One ``(name, rendered_value, is_output, write_back)`` tuple per bound
            parameter, in source order -- ``write_back`` is only consulted when
            ``is_output`` is False; see :func:`_translate_named_call_bindings` for how
            the text path builds this list.

        Returns
        -------
        tuple[list[str], str]
            The call + output-assignment statements, and the result-dict
            variable name (so the caller can also read the return value).
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

    def _translate_named_call_assignment(
        self, target_expr: str, block_name: str, params_str: str
    ) -> list[str]:
        """Translate ``<target> := "BlockName"(... out => var ...)``.

        A FUNCTION whose return value is consumed in an assignment may ALSO bind
        ``=>`` outputs. The expression path can only return the value (it cannot
        emit the output-assignment statements), so this routes such a call
        through the multi-statement form and assigns the return value last.
        """
        bindings = self._translate_named_call_bindings(params_str)
        result_lines, result_var = self._emit_named_call(block_name, bindings)
        result_lines.append(f'{target_expr} = {result_var}["{block_name}"]')
        return result_lines

    def _match_named_call_with_outputs(self, rhs: str) -> tuple[str, str] | None:
        """Return ``(block_name, params_str)`` if ``rhs`` is exactly one
        ``"BlockName"(...)`` call that binds at least one ``=>`` output.

        Returns ``None`` for anything else (plain return-value calls, mixed
        expressions, no outputs) so those keep the existing expression path.
        """
        rhs = rhs.strip().rstrip(";").strip()
        match = re.match(r'^"([^"]+)"\s*\(', rhs)
        if not match:
            return None
        # Find the matching close paren of the argument list.
        depth = 1
        pos = match.end()
        while pos < len(rhs) and depth > 0:
            if rhs[pos] == "(":
                depth += 1
            elif rhs[pos] == ")":
                depth -= 1
            pos += 1
        # The call must span the ENTIRE rhs (no trailing operators / operands).
        if depth != 0 or pos != len(rhs):
            return None
        params_str = rhs[match.end() : pos - 1]
        normalized_params = re.sub(r"=\s*>", "=>", params_str)
        if "=>" not in normalized_params:
            return None
        return match.group(1), params_str

    def translate_simple_statement(self, line: str) -> list[str]:
        """Translate a simple (non-control-flow) statement.

        This is the statement-level dispatcher for every non-control-flow
        construct the AST-driven generator (``plc_code.executor.generator``)
        produces: each ``Assignment``, ``Call``, ``Return`` and ``Exit`` node is
        rebuilt back into an SCL line before being handed here, where RETURN/EXIT,
        the quoted-name block call, compound assignment, the named-call-with-outputs
        special case, the ``#name(...)`` FB call and the bare-expression fallback
        are actually dispatched, in that order.

        Parameters
        ----------
        line : str
            Single statement line.

        Returns
        -------
        list[str]
            Translated Python statements.
        """
        # Normalize spaces
        normalized = re.sub(r"#\s+", "#", line)
        normalized = re.sub(r"=\s*>", "=>", normalized)
        normalized = re.sub(r":\s*=", ":=", normalized)

        # Handle RETURN statement
        if normalized.strip().rstrip(";").strip().upper() == "RETURN":
            return ["return"]

        # Handle EXIT statement (SCL's loop-break, used inside FOR/WHILE/REPEAT).
        # Falling through to the generic expression path below would emit the
        # bare word "EXIT" as a standalone Python statement, raising a NameError
        # at execute() time the first time the branch is actually taken.
        if normalized.strip().rstrip(";").strip().upper() == "EXIT":
            return ["break"]

        # Handle quoted-name block call: "BlockName"(params...)
        # Must be checked before assignment detection since these lines start with "
        named_block_result = self._translate_named_block_call(normalized)
        if named_block_result is not None:
            return named_block_result

        # Handle compound assignment (+=, -=, etc.)
        compound_match = re.match(r"(.+?)\s*(\+|-|\*|/)=\s*(.+);?", normalized)
        if compound_match:
            target = self.expr_translator.translate(compound_match.group(1).strip())
            op = compound_match.group(2)
            value = self.expr_translator.translate(compound_match.group(3).strip().rstrip(";"))
            return [f"{target} {op}= {value}"]

        # Assignment: `:=` must appear BEFORE the first `(` in the statement.
        # This distinguishes:
        #   - `#ca := COS(#alpha);`  → assignment (`:=` before first `(`)
        #   - `#timer(IN := #x, ...);` → FB call (first `(` before `:=`)
        assign_pos = normalized.find(":=")
        paren_pos = normalized.find("(")
        is_assignment = assign_pos != -1 and (paren_pos == -1 or assign_pos < paren_pos)
        if is_assignment:
            # Special case: RHS is a single named-block call that ALSO binds `=>`
            # outputs (e.g. `#ret := "Foo"(x := #a, out => #b)`). The expression
            # path can only return the value and silently drops the `=>` outputs,
            # so route it through the multi-statement call form instead.
            lhs, rhs = normalized.split(":=", 1)
            named_out = self._match_named_call_with_outputs(rhs)
            if named_out is not None:
                call_block_name, call_params = named_out
                target_expr = self.expr_translator.translate(lhs.strip())
                return self._translate_named_call_assignment(target_expr, call_block_name, call_params)
            # Use `normalized` (with `# var` collapsed to `#var`) so that the
            # expression translator's INSTANCE_VAR_PATTERN (#\w+) matches.
            return [self.translate_assignment(normalized)]

        # FB call pattern: #name(...);
        if normalized.startswith("#") and "(" in normalized and ")" in normalized:
            return self.translate_fb_call(normalized)

        # Other expression
        translated = self.expr_translator.translate(normalized.rstrip(";"))
        if translated:
            return [translated]

        return []


# Default translator instances
default_expr_translator = ExpressionTranslator()
default_stmt_translator = StatementTranslator()


def translate_expression(scl_expr: str) -> str:
    """Translate an SCL expression to Python.

    Parameters
    ----------
    scl_expr : str
        The SCL expression.

    Returns
    -------
    str
        The Python expression.
    """
    return default_expr_translator.translate(scl_expr)


def translate_assignment(scl_stmt: str) -> str:
    """Translate an SCL assignment to Python.

    Parameters
    ----------
    scl_stmt : str
        The SCL assignment statement.

    Returns
    -------
    str
        The Python assignment statement.
    """
    return default_stmt_translator.translate_assignment(scl_stmt)


def translate_fb_call(scl_call: str) -> list[str]:
    """Translate an SCL FB call to Python statements.

    Parameters
    ----------
    scl_call : str
        The SCL FB call statement.

    Returns
    -------
    list[str]
        The Python statements.
    """
    return default_stmt_translator.translate_fb_call(scl_call)
