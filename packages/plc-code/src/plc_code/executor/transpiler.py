"""SCL to Python transpiler.

This module provides the main transpilation functionality, converting
parsed SCL blocks into executable Python classes.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from plc_code.executor.arguments import SignatureResolver
from plc_code.executor.codegen import CodeGenContext
from plc_code.executor.generator import UnsupportedStatement, generate_statements
from plc_code.executor.models import (
    CompileResult,
    TranspileOptions,
    TranspileProblem,
    TranspileResult,
    identifier_collisions,
    python_class_name,
    python_identifier,
)
from plc_code.executor.renderer import UnsupportedExpression
from plc_code.executor.timers import system_fb_class_name, timer_class_name
from plc_code.executor.types import ArrayTypeInfo, SCLType, TypeInfo, TypeMapper
from plc_code.parser.lexer import Token
from plc_code.parser.models import Block, Network, Region, VariableDeclaration
from plc_code.parser.statement_parser import parse_statements, verify_no_silent_loss


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
    fb_type_resolver: Callable[[str], bool] | None = None
    signature_resolver: SignatureResolver | None = None
    _lines: list[str] = field(default_factory=list, repr=False)
    _ctx: CodeGenContext = field(default_factory=CodeGenContext, repr=False)
    _problems: list[TranspileProblem] = field(default_factory=list, repr=False)
    _warnings: list[str] = field(default_factory=list, repr=False)
    _fb_members: list[tuple[str, str]] = field(default_factory=list, repr=False)

    def transpile(self) -> TranspileResult:
        """Transpile the block to Python code.

        Returns
        -------
        TranspileResult
            The transpilation result containing the generated code.
        """
        self._lines = []
        self._problems = []
        self._warnings = []
        self._ctx = CodeGenContext()
        self._fb_members = []

        try:
            # Two SCL names that compile to one Python attribute would share it silently.
            declared = [var.name for section in self.block.variable_sections for var in section.variables]
            for first, second, identifier in identifier_collisions(declared):
                self._problems.append(
                    TranspileProblem(
                        f"variables {first!r} and {second!r} both compile to the attribute "
                        f"{identifier!r}; rename one"
                    )
                )
            if self._problems:
                return TranspileResult(
                    success=False,
                    python_code="",
                    class_name=python_class_name(self.block.name),
                    problems=self._problems,
                    warnings=self._warnings,
                )

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
                success=not self._problems,
                python_code=python_code,
                class_name=python_class_name(self.block.name),
                problems=self._problems,
                warnings=self._warnings,
            )
        except Exception as e:
            # generator.UnsupportedStatement and renderer.UnsupportedExpression both
            # know the source line they were raised for -- carried through here so a
            # located TRANSPILE diagnostic (see diagnostics.py) can report it, rather
            # than falling back to None the way every other exception still must.
            source_line = e.line if isinstance(e, UnsupportedExpression | UnsupportedStatement) else None
            self._problems.append(TranspileProblem(f"Transpilation error: {e}", source_line))
            return TranspileResult(
                success=False,
                python_code="",
                class_name=python_class_name(self.block.name),
                problems=self._problems,
                warnings=self._warnings,
            )

    def _emit(self, line: str) -> None:
        """Emit a line of code with current indentation."""
        if line:
            self._lines.append(f"{self._ctx.indent()}{line}")
        else:
            self._lines.append("")

    def _type_is_udt(self, data_type: str) -> bool:
        """Return True if ``data_type`` is a scalar UDT or a UDT-element array.

        Detects scalar UDTs (``_.Foo``) and arrays whose ELEMENT type is a UDT
        (``Array[..] of _.Foo``). Uses the same parsed-type UDT determination as
        :meth:`_get_array_default`, so a symbolic array bound (e.g.
        ``Array[0.._.AXIS_NUM] of Real``) is NOT mistaken for a UDT just because
        the string contains ``_.``.
        """
        parsed = self.type_mapper.parse_type(data_type)
        if isinstance(parsed, ArrayTypeInfo):
            elem = self.type_mapper.parse_type(parsed.element_type)
            return isinstance(elem, TypeInfo) and elem.scl_type == SCLType.UDT
        return parsed.scl_type == SCLType.UDT

    def _has_udt_variables(self) -> bool:
        """Return True if any variable uses a _.TypeName UDT type.

        Detects both scalar UDTs (``_.Foo``) and arrays whose element type is a
        UDT (``Array[..] of _.Foo``), so that ``_AutoStruct`` / ``Any`` are
        imported for either form.
        """
        for section in self.block.variable_sections:
            for var in section.variables:
                if self._type_is_udt(var.data_type):
                    return True
                if (
                    self._get_python_type_hint(var.data_type) == "Any"
                    and system_fb_class_name(var.data_type) is None
                ):
                    return True  # a system struct type, emitted as _AutoStruct
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

        # _clone_value backs the generated __call__ (S7 VAR_INPUT copy-in
        # semantics); FUNCTION_BLOCKs always get a __call__, so import it there.
        runtime_imports = ["PLCRuntime", "_bit_slice", "_with_bit_slice"]
        if self.block.block_type == "FUNCTION_BLOCK":
            runtime_imports.append("_clone_value")
        # Import _AutoStruct and Any when UDT variables are present
        if self._has_udt_variables():
            self._emit("from typing import Any")
            self._emit("")
            runtime_imports.append("_AutoStruct")
        self._emit("from plc_code.executor.runtime import " + ", ".join(sorted(runtime_imports)))

        # Check if we need timer imports
        timer_types = set()
        for section in self.block.variable_sections:
            for var in section.variables:
                timer_name = system_fb_class_name(var.data_type)
                if timer_name is not None:
                    timer_types.add(timer_name)

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
        self._emit(f"class {python_class_name(self.block.name)}:")

        self._ctx = self._ctx.push()
        class_body_ctx = self._ctx

        # Docstring
        if self.options.include_docstrings and self.block.header_info.comment:
            self._emit(f'"""{self.block.header_info.comment}"""')
            self._emit("")

        # Runtime reference
        self._emit("_runtime: PLCRuntime = field(repr=False)")
        self._emit("")

        # Generate variable sections
        self._generate_variables()

        # Generate metadata
        self._generate_metadata()

        # Generate execute method
        self._generate_execute_method()

        # Generate __call__ for FUNCTION_BLOCKs so instances are callable
        # (timer-style protocol): inst(**inputs) sets inputs then runs execute().
        # Restore the class-body indentation level first, since
        # _generate_execute_method leaves the context inside the method body.
        if self.block.block_type == "FUNCTION_BLOCK":
            self._ctx = class_body_ctx
            self._generate_call_method()

        # Generate __post_init__ to instantiate persistent nested FB members once.
        # Restore class-body indentation first (prior method emission leaves the
        # context inside a method body).
        if self._fb_members:
            self._ctx = class_body_ctx
            self._generate_post_init_method()

    def emit_fields_and_metadata(self) -> str:
        """Generate the field declarations and ``_inputs``/``_outputs``/``_in_outs``
        metadata at class-body indentation, returned as a source string.

        This is the public seam shared with the F-LAD (ladder) compile path
        (``plc_code.executor.ladder.compile``): both paths obtain byte-identical
        fields and metadata for the same VAR sections through this method,
        instead of the ladder path reaching into private emit state.

        Returns
        -------
        str
            The generated field and metadata lines, newline-joined, indented one
            level (i.e. ready to drop into a ``class`` body).
        """
        self._lines = []
        self._ctx = CodeGenContext().push()
        self._generate_variables()
        self._generate_metadata()
        return "\n".join(self._lines)

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
        name = python_identifier(var.name)

        # UDT types (_.TypeName) are initialised as _AutoStruct() so that
        # attribute and index access works without needing to resolve the actual
        # UDT class at compile time.
        if var.data_type.startswith("_."):
            type_name = var.data_type[2:].strip()
            # If the member's type is itself a FUNCTION_BLOCK (per the resolver),
            # it needs a persistent runtime-bound instance instead of an
            # _AutoStruct, so that the child's VAR state survives across cycles.
            # The instance is created once in __post_init__; the field defaults to
            # None here.  Scalar members only — arrays of _.X go through the
            # _get_array_default path, never this branch.
            if self.fb_type_resolver is not None and self.fb_type_resolver(type_name):
                self._fb_members.append((name, type_name))
                self._emit(f"{name}: Any = field(default=None)")
                return
            self._emit(f"{name}: Any = field(default_factory=_AutoStruct)")
            return

        type_hint = self._get_python_type_hint(var.data_type)
        default = self._get_default_value(var)

        # For timers and complex types, use field(default_factory=...)
        timer_name = system_fb_class_name(var.data_type)
        if timer_name is not None:
            self._emit(f"{name}: {timer_name} = field(default_factory={timer_name})")
        elif default == "{}" and type_hint == "Any":
            # A system struct type the runtime has no model for (`DTL`, `HW_IO`):
            # an attribute-addressable struct, since the code reads `#dtl.YEAR`.
            self._emit(f"{name}: Any = field(default_factory=_AutoStruct)")
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

        # UDT element arrays: each slot needs its own _AutoStruct (mirrors the
        # scalar UDT default). Use a comprehension so the instances are distinct
        # (``[_AutoStruct()] * N`` would alias a single shared object) and so
        # attribute/index access works at runtime instead of a bare dict.
        elem = self.type_mapper.parse_type(type_info.element_type)
        element_is_udt = isinstance(elem, TypeInfo) and elem.scl_type == SCLType.UDT

        if len(type_info.dimensions) == 1:
            if element_is_udt:
                return f"[_AutoStruct() for _ in range({alloc_size})]"
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
        inputs = [python_identifier(var.name) for var in self.block.inputs]
        self._emit(f"_inputs: tuple[str, ...] = field(default={tuple(inputs)!r}, repr=False)")

        # Output names
        outputs = [python_identifier(var.name) for var in self.block.outputs]
        self._emit(f"_outputs: tuple[str, ...] = field(default={tuple(outputs)!r}, repr=False)")

        # In-out names
        in_outs = [python_identifier(var.name) for var in self.block.in_outs]
        self._emit(f"_in_outs: tuple[str, ...] = field(default={tuple(in_outs)!r}, repr=False)")

        # Python attribute -> SCL name, for every variable whose name changed
        scl_names = {
            python_identifier(var.name): var.name
            for section in self.block.variable_sections
            for var in section.variables
            if python_identifier(var.name) != var.name
        }
        self._emit(f"_scl_names: dict[str, str] = field(default_factory=lambda: {scl_names!r}, repr=False)")

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

    def _generate_call_method(self) -> None:
        """Generate the __call__() method (timer-style callable protocol).

        Calling an instance with keyword arguments sets each as an attribute
        (inputs), then runs one cycle via execute(). This lets a nested member
        FB be driven as ``self.member(in=x)`` followed by reading
        ``self.member.out`` with no codegen change.
        """
        self._emit("")
        self._emit("def __call__(self, **kwargs):")
        method_ctx = self._ctx.push()
        self._ctx = method_ctx
        self._emit("for _name, _value in kwargs.items():")
        self._ctx = method_ctx.push()
        # S7 VAR_INPUT copy-in semantics: a UDT / array passed into the callee is
        # copied by value, so a later mutation of the caller's struct is not
        # aliased into the callee's retained state (e.g. an internal
        # ``prevInput := input`` snapshot used for change detection).
        self._emit("setattr(self, _name, _clone_value(_value))")
        self._ctx = method_ctx
        self._emit("self.execute()")

    def _generate_post_init_method(self) -> None:
        """Generate __post_init__ to create persistent nested FB members once.

        Each nested FUNCTION_BLOCK member is instantiated a single time via the
        runtime (``self._runtime.create_fb_instance("Name")``) so that the
        child's VAR state survives across the parent's ``execute()`` cycles.
        Runs after dataclass init, so ``self._runtime`` is already populated.
        """
        self._emit("")
        self._emit("def __post_init__(self):")
        method_ctx = self._ctx.push()
        self._ctx = method_ctx
        for attr_name, type_name in self._fb_members:
            self._emit(f'self.{attr_name} = self._runtime.create_fb_instance("{type_name}")')

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
        if network.tokens:
            content_lines = self._translate_scl_code(network.tokens)
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

        # region.tokens already carries the parser's flattening of nested-region
        # content into the parent region (mirrors region.content, see its
        # docstring), so nested regions need no separate collection here.
        if region.tokens:
            content_lines = self._translate_scl_code(region.tokens)
            lines.extend(content_lines)

        return lines

    def _translate_scl_code(self, tokens: list[Token]) -> list[str]:
        """Translate a token slice to Python statements via the statement AST.

        A unit whose tokens the statement parser cannot read produces a located
        error appended to ``self._problems`` (making ``TranspileResult.success``
        False) rather than falling back to any other translation: a transpiler
        that cannot read its input must say so, not silently emit Python that
        means something else.

        A ``ParseError`` is not the only way a unit can go unread: a body
        loop's last-resort recovery can swallow a token — typically a stray
        block-ender keyword nested inside a body it does not close — without
        recording it as a statement, an error or a separator.
        ``ParseResult.unattributed_spans`` names those tokens; per its own
        docstring it is "never a legitimate no-op ... always a defect when
        non-empty", so it is treated as failure here too, via
        :func:`verify_no_silent_loss` rather than a second hand-rolled check.

        Parameters
        ----------
        tokens : list[Token]
            The token slice for one network or region, as ``Network.tokens`` /
            ``Region.tokens`` carry it.

        Returns
        -------
        list[str]
            List of Python statements.
        """
        result = parse_statements(tokens)
        problems = verify_no_silent_loss(tokens, result)
        if result.errors or problems:
            for error in result.errors:
                self._problems.append(TranspileProblem(error.message, error.line))
            for problem in problems:
                self._problems.append(TranspileProblem(problem))
            return []
        return generate_statements(
            result.statements,
            signature_resolver=self.signature_resolver,
            timer_instances=self._timer_instances(),
        )

    def _timer_instances(self) -> frozenset[str]:
        """Names of this block's variables declared with an IEC timer type.

        What the generator uses to decide which ``#instance(...)`` calls get the
        ``clock=`` argument a timer's ``__call__`` requires -- by declared type,
        not by anything in the instance's name.
        """
        return frozenset(
            var.name
            for section in self.block.variable_sections
            for var in section.variables
            if timer_class_name(var.data_type) is not None
        )


def build_runtime_globals() -> dict[str, Any]:
    """Build the namespace that generated block code is executed in.

    This is the single definition of "what a generated module may reference
    without importing it". :func:`compile_block` execs into it, and
    :mod:`plc_code.executor.diagnostics` subtracts its keys when looking for
    names nothing provides — deriving both from here is what stops the check
    from drifting into false positives as the runtime surface grows.

    Names the generated module imports for itself (``math``, the runtime
    helpers, the timer types) are not in here; they bind at module scope when
    the generated code runs its own import lines.

    Returns
    -------
    dict[str, Any]
        A fresh namespace. Callers may mutate their copy.
    """
    runtime_mod = __import__("plc_code.executor.runtime", fromlist=["PLCRuntime", "_AutoStruct"])
    globals_: dict[str, Any] = {
        "dataclass": __import__("dataclasses").dataclass,
        "field": __import__("dataclasses").field,
        "PLCRuntime": runtime_mod.PLCRuntime,
        "_AutoStruct": runtime_mod._AutoStruct,
        "_bit_slice": runtime_mod._bit_slice,
        "_with_bit_slice": runtime_mod._with_bit_slice,
        "Any": __import__("typing").Any,
    }

    # Timers are optional: a build without them still compiles blocks that
    # never reference a timer type.
    try:
        timers = __import__("plc_code.executor.timers", fromlist=["TON_TIME"])
        for class_name in set(timers.SYSTEM_FB_NAMES.values()):
            globals_[class_name] = getattr(timers, class_name)
    except ImportError:
        pass

    return globals_


def transpile_block(
    block: Block,
    options: TranspileOptions | None = None,
    type_mapper: TypeMapper | None = None,
    fb_type_resolver: Callable[[str], bool] | None = None,
    signature_resolver: SignatureResolver | None = None,
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
    fb_type_resolver : Callable[[str], bool] | None
        Optional predicate returning True when a ``_.Name`` member type names a
        FUNCTION_BLOCK (rather than a UDT/TYPE).  When supplied, scalar FB
        members are emitted as persistent runtime-bound instances.  When None,
        every ``_.`` member keeps the legacy ``_AutoStruct`` behaviour.
    signature_resolver : SignatureResolver | None
        Resolves a called block's name to its input parameter names in declaration
        order, so a positional argument (``"Block"(#a, #b)``) binds to a parameter.
        ``PLCRuntime.block_signature`` is the production one. When None, any
        positional argument to a named block fails the transpile rather than being
        dropped (see :mod:`plc_code.executor.arguments`).

    Returns
    -------
    TranspileResult
        The transpilation result.
    """
    transpiler = SCLTranspiler(
        block=block,
        options=options or TranspileOptions(),
        type_mapper=type_mapper or TypeMapper(),
        fb_type_resolver=fb_type_resolver,
        signature_resolver=signature_resolver,
    )
    return transpiler.transpile()


def compile_block(
    block: Block,
    options: TranspileOptions | None = None,
    type_mapper: TypeMapper | None = None,
    extra_globals: dict[str, Any] | None = None,
    fb_type_resolver: Callable[[str], bool] | None = None,
    signature_resolver: SignatureResolver | None = None,
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
    fb_type_resolver : Callable[[str], bool] | None
        Optional predicate identifying which ``_.Name`` member types are
        FUNCTION_BLOCKs (forwarded to :func:`transpile_block`).  When None,
        legacy ``_AutoStruct`` behaviour is preserved for every ``_.`` member.
    signature_resolver : SignatureResolver | None
        Resolves a called block's name to its input parameter names in declaration
        order, so a positional argument (``"Block"(#a, #b)``) binds to a parameter.
        ``PLCRuntime.block_signature`` is the production one. When None, any
        positional argument to a named block fails the transpile rather than being
        dropped (forwarded to :func:`transpile_block`).

    Returns
    -------
    CompileResult
        The compilation result containing the class.
    """
    if block.is_ladder:
        from plc_code.executor.ladder.compile import compile_ladder_block  # noqa: PLC0415

        return compile_ladder_block(block)

    # First transpile
    transpile_result = transpile_block(block, options, type_mapper, fb_type_resolver, signature_resolver)

    if not transpile_result.success:
        return CompileResult(
            success=False,
            fb_class=None,
            transpile_result=transpile_result,
            compile_error="Transpilation failed",
        )

    # Set up compilation globals
    compile_globals = build_runtime_globals()

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

    except SyntaxError as e:
        # Generated Python that does not parse is a transpiler defect; report it
        # with the offending generated line so `--check` and a caller see which.
        generated = (e.text or "").strip()
        transpile_result.problems.append(
            TranspileProblem(
                f"generated Python does not parse: {e.msg} at generated line {e.lineno}: {generated}"
            )
        )
        transpile_result.success = False
        return CompileResult(
            success=False,
            fb_class=None,
            transpile_result=transpile_result,
            compile_error=str(e),
        )
    except Exception as e:
        return CompileResult(
            success=False,
            fb_class=None,
            transpile_result=transpile_result,
            compile_error=str(e),
        )
