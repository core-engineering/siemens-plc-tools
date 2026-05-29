"""SCL to Python transpiler.

This module provides the main transpilation functionality, converting
parsed SCL blocks into executable Python classes.
"""

from dataclasses import dataclass, field
from typing import Any

from plc_code.executor.codegen import (
    CodeGenContext,
    ExpressionTranslator,
    StatementTranslator,
)
from plc_code.executor.control_flow import ControlFlowTranslator
from plc_code.executor.models import CompileResult, TranspileOptions, TranspileResult
from plc_code.executor.types import ArrayTypeInfo, TypeMapper
from plc_code.parser.models import Block, Network, Region, VariableDeclaration


@dataclass
class SCLTranspiler:
    """Transpiles parsed SCL blocks to executable Python code.

    This class takes a parsed Block from the SCL parser and generates
    equivalent Python code that can be executed for testing.

    Attributes
    ----------
    block : Block
        The parsed SCL block to transpile.
    options : TranspileOptions
        Transpilation options.
    type_mapper : TypeMapper
        Type mapper for SCL to Python type conversion.
    """

    block: Block
    options: TranspileOptions = field(default_factory=TranspileOptions)
    type_mapper: TypeMapper = field(default_factory=TypeMapper)
    _expr_translator: ExpressionTranslator = field(default_factory=ExpressionTranslator, repr=False)
    _stmt_translator: StatementTranslator = field(default_factory=StatementTranslator, repr=False)
    _cf_translator: ControlFlowTranslator = field(default_factory=ControlFlowTranslator, repr=False)
    _lines: list[str] = field(default_factory=list, repr=False)
    _ctx: CodeGenContext = field(default_factory=CodeGenContext, repr=False)
    _errors: list[str] = field(default_factory=list, repr=False)
    _warnings: list[str] = field(default_factory=list, repr=False)
    _string_constants: dict[str, int] = field(default_factory=dict, repr=False)

    def transpile(self) -> TranspileResult:
        """Transpile the block to Python code.

        Returns
        -------
        TranspileResult
            The transpilation result containing the generated code.
        """
        self._lines = []
        self._errors = []
        self._warnings = []
        self._ctx = CodeGenContext()
        self._string_constants = {}

        try:
            # Pre-scan for string constants in CASE statements
            self._collect_string_constants()

            # Generate class body first so imports can inspect translated code
            self._generate_class()
            body_lines = self._lines
            self._lines = []

            # Reset context to top-level before generating imports
            self._ctx = CodeGenContext()
            self._generate_imports(body_code="\n".join(body_lines))
            self._lines.extend(body_lines)

            python_code = "\n".join(self._lines)
            return TranspileResult(
                success=len(self._errors) == 0,
                python_code=python_code,
                class_name=self.block.name,
                errors=self._errors,
                warnings=self._warnings,
            )
        except Exception as e:
            self._errors.append(f"Transpilation error: {e}")
            return TranspileResult(
                success=False,
                python_code="",
                class_name=self.block.name,
                errors=self._errors,
                warnings=self._warnings,
            )

    def _emit(self, line: str) -> None:
        """Emit a line of code with current indentation."""
        if line:
            self._lines.append(f"{self._ctx.indent()}{line}")
        else:
            self._lines.append("")

    def _collect_string_constants(self) -> None:
        """Scan code for string constants used in CASE labels and assignments.

        This method finds quoted string constants like "USER_FREEWHEEL" used in
        CASE statements and creates a mapping to integer values. This allows
        the transpiler to replace string references with numeric constants.
        """
        import re

        all_code = ""
        for network in self.block.networks:
            for region in network.regions:
                if region.content:
                    all_code += region.content + "\n"

        # Find string constants in CASE labels: "CONSTANT_NAME":
        case_labels = re.findall(r'"([A-Z_][A-Z0-9_]*)":', all_code, re.IGNORECASE)

        # Assign sequential integer values, starting with labels in order found
        seen = set()
        value = 0
        for label in case_labels:
            upper_label = label.upper()
            if upper_label not in seen:
                self._string_constants[f'"{label}"'] = value
                seen.add(upper_label)
                value += 1

        # Also find string constants used in comparisons and assignments
        # Pattern: = "CONSTANT_NAME" or ="CONSTANT_NAME"
        # The negative lookahead excludes quoted names that are actually global DB
        # references (`"Db".member`) or sub-block calls (`"Block"(...)`) — those are
        # not enum-string comparisons and must not be mapped to integers.
        other_refs = re.findall(r'[=<>]\s*"([A-Z_][A-Z0-9_]*)"(?!\s*[.(])', all_code, re.IGNORECASE)
        for ref in other_refs:
            key = f'"{ref}"'
            if key not in self._string_constants:
                self._string_constants[key] = value
                value += 1

    def _has_udt_variables(self) -> bool:
        """Return True if any variable section uses a _.TypeName UDT type."""
        for section in self.block.variable_sections:
            for var in section.variables:
                if var.data_type.startswith("_."):
                    return True
        return False

    def _generate_imports(self, body_code: str = "") -> None:
        """Generate import statements.

        Parameters
        ----------
        body_code : str
            The already-translated body code, used to detect which stdlib
            imports (e.g. ``import math``) are required.
        """
        self._emit("from dataclasses import dataclass, field")
        self._emit("")

        # Import _AutoStruct and Any when UDT variables are present
        if self._has_udt_variables():
            self._emit("from typing import Any")
            self._emit("")
            self._emit("from plc_code.executor.runtime import PLCRuntime, _AutoStruct")
        else:
            self._emit("from plc_code.executor.runtime import PLCRuntime")

        # Check if we need timer imports
        timer_types = set()
        for section in self.block.variable_sections:
            for var in section.variables:
                if var.data_type in ("TON_TIME", "TOF_TIME", "TP_TIME"):
                    timer_types.add(var.data_type)

        if timer_types:
            timer_imports = ", ".join(sorted(timer_types))
            self._emit(f"from plc_code.executor.timers import {timer_imports}")

        if "math." in body_code:
            self._emit("import math")

        self._emit("")
        self._emit("")

    def _generate_class(self) -> None:
        """Generate the main class definition."""
        self._emit("@dataclass")
        self._emit(f"class {self.block.name}:")

        self._ctx = self._ctx.push()

        # Docstring
        if self.options.include_docstrings and self.block.header_info.comment:
            self._emit(f'"""{self.block.header_info.comment}"""')
            self._emit("")

        # Runtime reference
        self._emit("_runtime: PLCRuntime = field(repr=False)")
        self._emit("")

        # Generate string constants as class attributes (if any)
        if self._string_constants:
            self._emit("# String constants (converted to integers)")
            for const_str, const_val in self._string_constants.items():
                # Extract name from quoted string: "USER_FREEWHEEL" -> USER_FREEWHEEL
                const_name = const_str.strip('"')
                self._emit(f"{const_name}: int = {const_val}")
            self._emit("")

        # Generate variable sections
        self._generate_variables()

        # Generate metadata
        self._generate_metadata()

        # Generate execute method
        self._generate_execute_method()

    def _generate_variables(self) -> None:
        """Generate variable declarations as class attributes."""
        section_comments = {
            "VAR_INPUT": "# VAR_INPUT",
            "VAR_OUTPUT": "# VAR_OUTPUT",
            "VAR_IN_OUT": "# VAR_IN_OUT",
            "VAR": "# VAR (static)",
            "VAR_TEMP": "# VAR_TEMP",
            "VAR_CONSTANT": "# VAR CONSTANT",
        }

        for section in self.block.variable_sections:
            if not section.variables:
                continue

            comment = section_comments.get(section.section_type, f"# {section.section_type}")
            self._emit(comment)

            for var in section.variables:
                self._generate_variable(var, section.is_constant)

            self._emit("")

    def _generate_variable(self, var: VariableDeclaration, is_constant: bool) -> None:
        """Generate a single variable declaration.

        Parameters
        ----------
        var : VariableDeclaration
            The variable to generate.
        is_constant : bool
            Whether this is a constant.
        """
        name = var.name

        # UDT types (_.TypeName) are initialised as _AutoStruct() so that
        # attribute and index access works without needing to resolve the actual
        # UDT class at compile time.
        if var.data_type.startswith("_."):
            self._emit(f"{name}: Any = field(default_factory=_AutoStruct)")
            return

        type_hint = self._get_python_type_hint(var.data_type)
        default = self._get_default_value(var)

        # For timers and complex types, use field(default_factory=...)
        if var.data_type in ("TON_TIME", "TOF_TIME", "TP_TIME"):
            self._emit(f"{name}: {type_hint} = field(default_factory={var.data_type})")
        elif default.startswith("[") or default.startswith("{"):
            # List or dict literal - use default_factory
            self._emit(f"{name}: {type_hint} = field(default_factory=lambda: {default})")
        else:
            # Simple default value
            if self.options.generate_type_hints:
                self._emit(f"{name}: {type_hint} = {default}")
            else:
                self._emit(f"{name} = {default}")

    def _get_python_type_hint(self, scl_type: str) -> str:
        """Get Python type hint for an SCL type.

        Parameters
        ----------
        scl_type : str
            The SCL type string.

        Returns
        -------
        str
            Python type hint.
        """
        return self.type_mapper.get_python_type_hint(scl_type)

    def _get_default_value(self, var: VariableDeclaration) -> str:
        """Get the default value for a variable.

        Parameters
        ----------
        var : VariableDeclaration
            The variable declaration.

        Returns
        -------
        str
            Python representation of the default value.
        """
        if var.default_value:
            # Convert SCL literal to Python
            value = var.default_value.strip()

            # Handle time literals
            if value.upper().startswith("T#"):
                seconds = self.type_mapper._parse_time_literal(value)
                return str(seconds)

            # Handle boolean
            if var.data_type == "Bool":
                return "True" if value.lower() in ("true", "1") else "False"

            # Translate SCL hex literals (16#XXXX) to Python hex literals (0xXXXX)
            if value.lower().startswith("16#"):
                return hex(int(value[3:], 16))

            # Handle numeric
            if var.data_type in ("Int", "DInt", "SInt", "USInt", "UInt", "UDInt"):
                return value

            if var.data_type in ("Real", "LReal"):
                return value

            # Handle string
            if var.data_type == "String":
                if not (value.startswith('"') or value.startswith("'")):
                    return f'"{value}"'
                return value

            return value

        # No default specified - use type default
        type_info = self.type_mapper.parse_type(var.data_type)

        # Handle array types
        if isinstance(type_info, ArrayTypeInfo):
            return self._get_array_default(type_info)

        # Simple types
        default_val = self.type_mapper.create_default(var.data_type)
        if isinstance(default_val, bool):
            return "True" if default_val else "False"
        if isinstance(default_val, str):
            return f'"{default_val}"'
        return str(default_val)

    def _get_element_default(self, element_type: str) -> str:
        """Get default value for array element type.

        Parameters
        ----------
        element_type : str
            The element type string.

        Returns
        -------
        str
            Python default value representation.
        """
        default_val = self.type_mapper.create_default(element_type)
        if isinstance(default_val, bool):
            return "True" if default_val else "False"
        if isinstance(default_val, str):
            return f'"{default_val}"'
        return str(default_val)

    def _get_array_default(self, type_info: ArrayTypeInfo) -> str:
        """Build a Python literal for an array default (any number of dimensions).

        For a 1D array ``[lo..hi] of T`` this returns ``[<elem>] * N``.
        For a 2D (or higher) array it recursively builds nested list comprehensions.

        When the lower bound ``lo`` is greater than 0 (i.e. 1-based or higher),
        the outer list is allocated with ``hi + 1`` elements so that direct SCL
        index access (e.g. ``arr[1]`` through ``arr[hi]``) works without an
        offset adjustment.  The extra leading elements (indices 0..lo-1) are
        zero-initialised and simply never accessed.

        Parameters
        ----------
        type_info : ArrayTypeInfo
            Parsed array type information.

        Returns
        -------
        str
            Python expression string suitable for use as a default_factory body.
        """
        # Arrays with symbolic bounds (e.g. Array[0.._.AXIS_NUM_INDEX]) cannot have
        # a sized list default because the actual upper bound is unknown at transpile
        # time.  Use an empty dict so that string-keyed subscript access (the common
        # pattern for named-constant indexed arrays) works out of the box.
        if getattr(type_info, "symbolic_bounds", False):
            return "{}"

        lo, hi = type_info.dimensions[0]
        # Allocate hi+1 elements when lo>0 so 1-based (or higher) SCL indices
        # map directly to Python list indices without an explicit offset.
        alloc_size = hi + 1 if lo > 0 else (hi - lo + 1)

        if len(type_info.dimensions) == 1:
            # 1-D: keep the existing [elem] * size form
            element_default = self._get_element_default(type_info.element_type)
            return f"[{element_default}] * {alloc_size}"

        # Multi-dimensional: build nested list comprehension
        # e.g. [[0.0] * 4 for _ in range(4)]  for a 4x4 LReal array
        inner_dims = type_info.dimensions[1:]
        # Construct a temporary ArrayTypeInfo for the inner dimensions
        inner_lo, inner_hi = inner_dims[0]
        inner_type_info = ArrayTypeInfo(
            element_type=type_info.element_type,
            lower_bound=inner_lo,
            upper_bound=inner_hi,
            dimensions=inner_dims,
        )
        inner_expr = self._get_array_default(inner_type_info)
        return f"[{inner_expr} for _ in range({alloc_size})]"

    def _generate_metadata(self) -> None:
        """Generate metadata attributes for the class."""
        # Input names
        inputs = [var.name for var in self.block.inputs]
        self._emit(f"_inputs: tuple[str, ...] = field(default={tuple(inputs)!r}, repr=False)")

        # Output names
        outputs = [var.name for var in self.block.outputs]
        self._emit(f"_outputs: tuple[str, ...] = field(default={tuple(outputs)!r}, repr=False)")

        # In-out names
        in_outs = [var.name for var in self.block.in_outs]
        self._emit(f"_in_outs: tuple[str, ...] = field(default={tuple(in_outs)!r}, repr=False)")

        self._emit("")

    def _generate_execute_method(self) -> None:
        """Generate the execute() method."""
        self._emit("def execute(self) -> None:")

        self._ctx = self._ctx.push()
        self._emit('"""Execute one cycle of the function block."""')

        # Extract code from networks
        has_code = False
        for network in self.block.networks:
            code_lines = self._extract_network_code(network)
            if code_lines:
                has_code = True
                for line in code_lines:
                    self._emit(line)

        if not has_code:
            self._emit("pass")

    def _extract_network_code(self, network: Network) -> list[str]:
        """Extract executable code from a network.

        Parameters
        ----------
        network : Network
            The network to extract code from.

        Returns
        -------
        list[str]
            List of Python code lines.
        """
        lines: list[str] = []

        # Process regions
        for region in network.regions:
            # Skip documentation regions
            if region.name.lower() in ("block info header", "description"):
                continue

            region_lines = self._extract_region_code(region)
            lines.extend(region_lines)

        # Process direct network content
        if network.content:
            content_lines = self._translate_scl_code(network.content)
            lines.extend(content_lines)

        return lines

    def _extract_region_code(self, region: Region) -> list[str]:
        """Extract executable code from a region.

        This method combines all region content (parent + nested) into a single
        SCL code block before translation. This preserves control flow structures
        like CASE statements that span nested REGIONs.

        Parameters
        ----------
        region : Region
            The region to extract code from.

        Returns
        -------
        list[str]
            List of Python code lines.
        """
        lines: list[str] = []

        # Add region comment if not empty name
        if region.name and self.options.include_comments:
            lines.append(f"# {region.name}")

        # Collect all SCL code from region and nested regions into one block
        # This preserves CASE statement structure when bodies are in nested regions
        combined_scl = self._collect_region_scl(region)

        if combined_scl.strip():
            content_lines = self._translate_scl_code(combined_scl)
            lines.extend(content_lines)

        return lines

    def _collect_region_scl(self, region: Region) -> str:
        """Collect all SCL code from a region.

        The parser now flattens nested region content into the parent region's
        content field, so this method simply returns the region content directly.
        Nested regions are preserved for documentation purposes but their content
        is already included in the parent.

        Parameters
        ----------
        region : Region
            The region to collect code from.

        Returns
        -------
        str
            Combined SCL code.
        """
        # The parser already flattens nested region content into the parent's content
        # so we just return the content directly without re-adding nested content
        return region.content or ""

    def _translate_scl_code(self, scl_code: str) -> list[str]:
        """Translate SCL code to Python statements.

        Parameters
        ----------
        scl_code : str
            SCL code string.

        Returns
        -------
        list[str]
            List of Python statements.
        """
        import re

        # Replace string constants with appropriate values
        # For CASE labels: "STRING": -> integer value followed by :
        # For comparisons/assignments: "STRING" -> self.CONSTANT_NAME
        processed_code = scl_code

        for const_str, const_val in self._string_constants.items():
            const_name = const_str.strip('"')

            # Replace CASE labels: "STRING": -> integer:
            # Pattern matches the string followed by : (case label)
            case_label_pattern = re.escape(const_str) + r"\s*:"
            processed_code = re.sub(
                case_label_pattern,
                f"{const_val}:",
                processed_code,
            )

            # Replace remaining occurrences (comparisons, assignments)
            # Add spaces around the constant to ensure proper separation from OR/AND keywords
            processed_code = processed_code.replace(const_str, f" self.{const_name} ")

        # After constant replacement, ensure spacing around OR/AND between self.IDENTIFIER patterns
        # This handles cases like self.ESD1_ACTIVATIONORself.var -> self.ESD1_ACTIVATION OR self.var
        # Pattern: self.IDENTIFIER immediately followed by OR/AND and then self.
        processed_code = re.sub(r"(self\.\w+)(OR)(self\.)", r"\1 \2 \3", processed_code, flags=re.IGNORECASE)
        processed_code = re.sub(r"(self\.\w+)(AND)(self\.)", r"\1 \2 \3", processed_code, flags=re.IGNORECASE)
        # Also handle OR/AND followed by # (instance variable)
        processed_code = re.sub(r"(self\.\w+)(OR)(#)", r"\1 \2 \3", processed_code, flags=re.IGNORECASE)
        processed_code = re.sub(r"(self\.\w+)(AND)(#)", r"\1 \2 \3", processed_code, flags=re.IGNORECASE)
        # And handle OR/AND followed by ( for function calls/parens
        processed_code = re.sub(r"(self\.\w+)(OR)(\()", r"\1 \2 \3", processed_code, flags=re.IGNORECASE)
        processed_code = re.sub(r"(self\.\w+)(AND)(\()", r"\1 \2 \3", processed_code, flags=re.IGNORECASE)

        # Clean up excessive spaces from constant replacement
        processed_code = re.sub(r"  +", " ", processed_code)

        # Use the control flow translator which handles all statement types
        return self._cf_translator.translate_block(processed_code)


def transpile_block(
    block: Block,
    options: TranspileOptions | None = None,
    type_mapper: TypeMapper | None = None,
) -> TranspileResult:
    """Transpile an SCL block to Python code.

    Parameters
    ----------
    block : Block
        The parsed SCL block.
    options : TranspileOptions | None
        Transpilation options.
    type_mapper : TypeMapper | None
        Type mapper for SCL to Python conversion.

    Returns
    -------
    TranspileResult
        The transpilation result.
    """
    transpiler = SCLTranspiler(
        block=block,
        options=options or TranspileOptions(),
        type_mapper=type_mapper or TypeMapper(),
    )
    return transpiler.transpile()


def compile_block(
    block: Block,
    options: TranspileOptions | None = None,
    type_mapper: TypeMapper | None = None,
    extra_globals: dict[str, Any] | None = None,
) -> CompileResult:
    """Transpile and compile an SCL block to an executable Python class.

    This function transpiles the block to Python code and then compiles
    it using exec() to create an actual class that can be instantiated.

    Parameters
    ----------
    block : Block
        The parsed SCL block.
    options : TranspileOptions | None
        Transpilation options.
    type_mapper : TypeMapper | None
        Type mapper for SCL to Python conversion.
    extra_globals : dict[str, Any] | None
        Additional globals to make available during compilation.

    Returns
    -------
    CompileResult
        The compilation result containing the class.
    """
    # First transpile
    transpile_result = transpile_block(block, options, type_mapper)

    if not transpile_result.success:
        return CompileResult(
            success=False,
            fb_class=None,
            transpile_result=transpile_result,
            compile_error="Transpilation failed",
        )

    # Set up compilation globals
    _runtime_mod = __import__("plc_code.executor.runtime", fromlist=["PLCRuntime", "_AutoStruct"])
    compile_globals: dict[str, Any] = {
        "dataclass": __import__("dataclasses").dataclass,
        "field": __import__("dataclasses").field,
        "PLCRuntime": _runtime_mod.PLCRuntime,
        "_AutoStruct": _runtime_mod._AutoStruct,
        "Any": __import__("typing").Any,
    }

    # Add timer imports if needed
    try:
        timers = __import__("plc_code.executor.timers", fromlist=["TON_TIME", "TOF_TIME", "TP_TIME"])
        compile_globals["TON_TIME"] = timers.TON_TIME
        compile_globals["TOF_TIME"] = timers.TOF_TIME
        compile_globals["TP_TIME"] = timers.TP_TIME
    except ImportError:
        pass

    # Add extra globals
    if extra_globals:
        compile_globals.update(extra_globals)

    # Compile
    try:
        exec(transpile_result.python_code, compile_globals)
        fb_class = compile_globals.get(transpile_result.class_name)

        if fb_class is None:
            return CompileResult(
                success=False,
                fb_class=None,
                transpile_result=transpile_result,
                compile_error=f"Class '{transpile_result.class_name}' not found after compilation",
            )

        return CompileResult(
            success=True,
            fb_class=fb_class,
            transpile_result=transpile_result,
        )

    except Exception as e:
        return CompileResult(
            success=False,
            fb_class=None,
            transpile_result=transpile_result,
            compile_error=str(e),
        )
