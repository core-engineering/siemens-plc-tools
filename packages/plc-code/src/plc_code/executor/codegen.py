"""Code generation utilities for SCL to Python transpilation.

This module provides utilities for generating Python code from SCL
constructs, including expression translation and statement generation.
"""

import re
from dataclasses import dataclass, field


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
    """Translates SCL expressions to Python expressions.

    This class handles the conversion of SCL syntax to equivalent
    Python syntax, including variable references, operators, and
    function calls.
    """

    # Patterns for SCL constructs
    INSTANCE_VAR_PATTERN = re.compile(r"#(\w+)")
    GLOBAL_DB_PATTERN = re.compile(r'"(\w+)"\.(.+)')
    LIBRARY_TYPE_PATTERN = re.compile(r"_\.(\w+)")
    ARRAY_ACCESS_PATTERN = re.compile(r"\[([^\]]+)\]")
    STRING_KEY_PATTERN = re.compile(r'\["([^"]+)"\]')

    # SCL to Python operator mappings
    OPERATOR_MAP: dict[str, str] = field(
        default_factory=lambda: {
            ":=": "=",
            "<>": "!=",
            "AND": "and",
            "OR": "or",
            "NOT": "not",
            "MOD": "%",
            "DIV": "//",
        }
    )

    # SCL built-in function mappings
    BUILTIN_MAP: dict[str, str] = field(
        default_factory=lambda: {
            "INT_TO_REAL": "float",
            "REAL_TO_INT": "int",
            "INT_TO_USINT": "lambda x: x & 0xFF",
            "INT_TO_UINT": "lambda x: x & 0xFFFF",
            "INT_TO_DINT": "int",
            "DINT_TO_INT": "int",
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
            "LN": "math.log",
            "EXP": "math.exp",
            "LOWER_BOUND": "lambda arr, dim: 0",
            "UPPER_BOUND": (
                "lambda arr, dim: (len(arr[0]) - 1 if dim == 2 and arr "
                "and isinstance(arr[0], (list, tuple)) else len(arr) - 1)"
            ),
        }
    )

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

        # Normalize spaced instance variable references: "# var" -> "#var"
        # The parser may insert a space between '#' and the identifier.
        result = re.sub(r"#\s+(\w)", r"#\1", result)

        # Replace instance variables (#var -> self.var)
        result = self.INSTANCE_VAR_PATTERN.sub(r"self.\1", result)

        # Replace global DB access ("DB".member -> self._runtime.global_dbs["DB"].member)
        result = self._translate_global_db(result)

        # Translate SCL hex literals (16#XXXX -> 0xXXXX)
        result = self._translate_hex_literals(result)

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

        return result

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
        return re.sub(
            r"\b16#([0-9A-Fa-f]+)\b",
            lambda m: hex(int(m.group(1), 16)),
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
