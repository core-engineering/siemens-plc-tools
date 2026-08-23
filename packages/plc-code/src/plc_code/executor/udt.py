"""UDT (User Data Type) generation for SCL execution.

This module provides generation of Python dataclasses from TIA Portal
User Data Types (UDTs), enabling execution of SCL code that uses complex
data structures.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from plc_code.executor.models import python_class_name
from plc_code.executor.types import TypeMapper
from plc_code.parser.models import Block, StructField, UserDataType


@dataclass
class UDTGenerationResult:
    """Result of UDT generation.

    Attributes
    ----------
    success : bool
        Whether generation succeeded.
    python_code : str
        Generated Python code.
    class_name : str
        Name of the generated class.
    dependencies : list[str]
        List of UDT names this type depends on.
    errors : list[str]
        Any errors that occurred.
    """

    success: bool
    python_code: str
    class_name: str
    dependencies: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class UDTCompileResult:
    """Result of UDT compilation.

    Attributes
    ----------
    success : bool
        Whether compilation succeeded.
    udt_class : type | None
        The compiled dataclass, or None if failed.
    generation_result : UDTGenerationResult
        The generation result.
    compile_error : str | None
        Any compilation error message.
    """

    success: bool
    udt_class: type | None
    generation_result: UDTGenerationResult
    compile_error: str | None = None


class UDTRegistry:
    """Registry of compiled UDT classes.

    This class manages a collection of compiled UDT classes, handling
    dependencies and providing factory functions for instantiation.

    Attributes
    ----------
    types : dict[str, type]
        Mapping of type names to compiled classes.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._types: dict[str, type] = {}
        self._pending: dict[str, Block] = {}

    @property
    def types(self) -> dict[str, type]:
        """Get all registered types."""
        return self._types.copy()

    def register(self, name: str, udt_class: type) -> None:
        """Register a compiled UDT class.

        Parameters
        ----------
        name : str
            Type name (without _.prefix).
        udt_class : type
            The compiled dataclass.
        """
        self._types[name] = udt_class

    def get(self, name: str) -> type | None:
        """Get a registered type by name.

        Parameters
        ----------
        name : str
            Type name (with or without _.prefix).

        Returns
        -------
        type | None
            The registered type, or None if not found.
        """
        # Strip _.prefix if present
        clean_name = name.lstrip("_").lstrip(".")
        return self._types.get(clean_name)

    def has(self, name: str) -> bool:
        """Check if a type is registered.

        Parameters
        ----------
        name : str
            Type name.

        Returns
        -------
        bool
            True if type is registered.
        """
        return self.get(name) is not None

    def create_instance(self, name: str) -> Any:
        """Create an instance of a registered type.

        Parameters
        ----------
        name : str
            Type name.

        Returns
        -------
        Any
            Instance of the type with default values.

        Raises
        ------
        KeyError
            If type is not registered.
        """
        udt_class = self.get(name)
        if udt_class is None:
            raise KeyError(f"UDT '{name}' not registered")
        return udt_class()

    def add_pending(self, name: str, block: Block) -> None:
        """Add a block for pending compilation.

        Parameters
        ----------
        name : str
            Type name.
        block : Block
            The parsed block.
        """
        self._pending[name] = block

    def compile_pending(self) -> list[str]:
        """Compile all pending blocks in dependency order.

        Returns
        -------
        list[str]
            List of error messages, empty if all succeeded.
        """
        errors: list[str] = []
        generator = UDTGenerator(registry=self)

        # Keep trying until no progress or all done
        max_iterations = len(self._pending) + 1
        for _ in range(max_iterations):
            if not self._pending:
                break

            compiled_any = False
            to_remove: list[str] = []

            for name, block in self._pending.items():
                result = generator.compile_udt(block)
                if result.success and result.udt_class is not None:
                    self.register(name, result.udt_class)
                    to_remove.append(name)
                    compiled_any = True
                elif not result.success and not _has_unresolved_deps(
                    result.generation_result.dependencies, self._types
                ):
                    # Failed for reason other than missing deps
                    errors.append(f"{name}: {result.compile_error}")
                    to_remove.append(name)

            for name in to_remove:
                del self._pending[name]

            if not compiled_any:
                # No progress - remaining types have circular or missing deps
                for name in self._pending:
                    errors.append(f"{name}: unresolved dependencies")
                break

        return errors


def _has_unresolved_deps(deps: list[str], registered: dict[str, type]) -> bool:
    """Check if any dependencies are unresolved."""
    for dep in deps:
        clean = dep.lstrip("_").lstrip(".")
        if clean not in registered:
            return True
    return False


@dataclass
class UDTGenerator:
    """Generates Python dataclasses from UDT definitions.

    Attributes
    ----------
    type_mapper : TypeMapper
        Type mapper for SCL to Python conversion.
    registry : UDTRegistry | None
        Optional registry for resolving nested UDT references.
    """

    type_mapper: TypeMapper = field(default_factory=TypeMapper)
    registry: UDTRegistry | None = None

    def generate(self, block: Block) -> UDTGenerationResult:
        """Generate Python code for a UDT block.

        Parameters
        ----------
        block : Block
            A parsed block with block_type=TYPE.

        Returns
        -------
        UDTGenerationResult
            The generation result.
        """
        if block.block_type != "TYPE":
            return UDTGenerationResult(
                success=False,
                python_code="",
                class_name=python_class_name(block.name),
                errors=[f"Block '{block.name}' is not a TYPE block"],
            )

        if block.user_data_type is None:
            return UDTGenerationResult(
                success=False,
                python_code="",
                class_name=python_class_name(block.name),
                errors=[f"Block '{block.name}' has no user_data_type"],
            )

        return self._generate_udt(block.user_data_type)

    def _generate_udt(self, udt: UserDataType) -> UDTGenerationResult:
        """Generate Python code for a UserDataType.

        Parameters
        ----------
        udt : UserDataType
            The user data type definition.

        Returns
        -------
        UDTGenerationResult
            The generation result.
        """
        lines: list[str] = []
        dependencies: list[str] = []
        errors: list[str] = []

        # Imports
        lines.append("from dataclasses import dataclass, field")
        lines.append("")
        lines.append("")

        # Class definition
        lines.append("@dataclass")
        lines.append(f"class {python_class_name(udt.name)}:")

        # Docstring
        lines.append(f'    """Generated UDT: {udt.name}."""')
        lines.append("")

        # Fields
        if not udt.fields:
            lines.append("    pass")
        else:
            for struct_field in udt.fields:
                field_line, field_deps = self._generate_field(struct_field)
                if field_line:
                    lines.append(f"    {field_line}")
                dependencies.extend(field_deps)

        lines.append("")

        python_code = "\n".join(lines)

        return UDTGenerationResult(
            success=len(errors) == 0,
            python_code=python_code,
            class_name=python_class_name(udt.name),
            dependencies=list(set(dependencies)),
            errors=errors,
        )

    def _generate_field(self, struct_field: StructField) -> tuple[str, list[str]]:
        """Generate a single field definition.

        Parameters
        ----------
        struct_field : StructField
            The struct field.

        Returns
        -------
        tuple[str, list[str]]
            The field definition line and list of dependencies.
        """
        name = struct_field.name
        data_type = struct_field.data_type
        dependencies: list[str] = []

        # Check for UDT reference (_.typeName)
        if data_type.startswith("_."):
            udt_name = data_type[2:]  # Remove _.
            dependencies.append(udt_name)
            type_hint = udt_name
            default = f"field(default_factory={udt_name})"
            return f"{name}: {type_hint} = {default}", dependencies

        # Check for array of UDT
        if data_type.startswith("Array") and "_." in data_type:
            # Array[1..9] of _.typeUnitParameter
            import re

            match = re.match(r"Array\[(\d+)\.\.(\d+)\]\s+of\s+_\.(\w+)", data_type)
            if match:
                lower = int(match.group(1))
                upper = int(match.group(2))
                element_type = match.group(3)
                size = upper - lower + 1
                dependencies.append(element_type)
                type_hint = f"list[{element_type}]"
                default = f"field(default_factory=lambda: [{element_type}() for _ in range({size})])"
                return f"{name}: {type_hint} = {default}", dependencies

        # Standard type
        type_hint = self.type_mapper.get_python_type_hint(data_type)
        default = self._get_default_value(data_type)

        # Handle complex defaults
        if default.startswith("[") or default.startswith("{"):
            return f"{name}: {type_hint} = field(default_factory=lambda: {default})", dependencies

        return f"{name}: {type_hint} = {default}", dependencies

    def _get_default_value(self, data_type: str) -> str:
        """Get default value for a type.

        Parameters
        ----------
        data_type : str
            The SCL data type.

        Returns
        -------
        str
            Python default value representation.
        """
        default_val = self.type_mapper.create_default(data_type)

        if isinstance(default_val, bool):
            return "True" if default_val else "False"
        if isinstance(default_val, str):
            return f'"{default_val}"'
        if isinstance(default_val, list):
            # Format list elements
            if default_val and isinstance(default_val[0], bool):
                elements = ["True" if v else "False" for v in default_val]
            else:
                elements = [str(v) for v in default_val]
            return f"[{', '.join(elements)}]"
        return str(default_val)

    def compile_udt(
        self,
        block: Block,
        extra_globals: dict[str, Any] | None = None,
    ) -> UDTCompileResult:
        """Generate and compile a UDT to an executable Python class.

        Parameters
        ----------
        block : Block
            The parsed UDT block.
        extra_globals : dict[str, Any] | None
            Additional globals to make available during compilation.

        Returns
        -------
        UDTCompileResult
            The compilation result.
        """
        # First generate the code
        gen_result = self.generate(block)

        if not gen_result.success:
            return UDTCompileResult(
                success=False,
                udt_class=None,
                generation_result=gen_result,
                compile_error="Generation failed",
            )

        # Check if dependencies are available
        compile_globals: dict[str, Any] = {
            "dataclass": __import__("dataclasses").dataclass,
            "field": __import__("dataclasses").field,
        }

        # Add registered types from registry
        if self.registry:
            for dep in gen_result.dependencies:
                dep_class = self.registry.get(dep)
                if dep_class is not None:
                    compile_globals[dep] = dep_class
                else:
                    return UDTCompileResult(
                        success=False,
                        udt_class=None,
                        generation_result=gen_result,
                        compile_error=f"Missing dependency: {dep}",
                    )

        # Add extra globals
        if extra_globals:
            compile_globals.update(extra_globals)

        # Compile
        try:
            exec(gen_result.python_code, compile_globals)
            udt_class = compile_globals.get(gen_result.class_name)

            if udt_class is None:
                return UDTCompileResult(
                    success=False,
                    udt_class=None,
                    generation_result=gen_result,
                    compile_error=f"Class '{gen_result.class_name}' not found after compilation",
                )

            return UDTCompileResult(
                success=True,
                udt_class=udt_class,
                generation_result=gen_result,
            )

        except Exception as e:
            return UDTCompileResult(
                success=False,
                udt_class=None,
                generation_result=gen_result,
                compile_error=str(e),
            )


def generate_udt(block: Block) -> UDTGenerationResult:
    """Generate Python code for a UDT block.

    Parameters
    ----------
    block : Block
        A parsed block with block_type=TYPE.

    Returns
    -------
    UDTGenerationResult
        The generation result.
    """
    generator = UDTGenerator()
    return generator.generate(block)


def compile_udt(
    block: Block,
    registry: UDTRegistry | None = None,
    extra_globals: dict[str, Any] | None = None,
) -> UDTCompileResult:
    """Compile a UDT block to an executable Python class.

    Parameters
    ----------
    block : Block
        The parsed UDT block.
    registry : UDTRegistry | None
        Optional registry for resolving dependencies.
    extra_globals : dict[str, Any] | None
        Additional globals for compilation.

    Returns
    -------
    UDTCompileResult
        The compilation result.
    """
    generator = UDTGenerator(registry=registry)
    return generator.compile_udt(block, extra_globals)


def compile_udt_directory(
    directory: Path,
    pattern: str = "*.s7dcl",
) -> tuple[UDTRegistry, list[str]]:
    """Compile all UDTs in a directory.

    This function discovers all UDT files in a directory, resolves
    dependencies, and compiles them in the correct order.

    Parameters
    ----------
    directory : Path
        Directory containing UDT files.
    pattern : str
        Glob pattern for finding files.

    Returns
    -------
    tuple[UDTRegistry, list[str]]
        The registry with compiled types and any error messages.
    """
    from plc_code.parser import parse_scl_file

    registry = UDTRegistry()
    errors: list[str] = []

    # Find and parse all UDT files
    for file_path in directory.rglob(pattern):
        try:
            block = parse_scl_file(file_path)
            if block.block_type == "TYPE" and block.user_data_type:
                registry.add_pending(block.name, block)
        except Exception as e:
            errors.append(f"{file_path}: {e}")

    # Compile in dependency order
    compile_errors = registry.compile_pending()
    errors.extend(compile_errors)

    return registry, errors
