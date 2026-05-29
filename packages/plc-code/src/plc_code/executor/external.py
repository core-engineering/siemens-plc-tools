"""External dependencies handling for SCL execution.

This module provides utilities for handling external dependencies that
SCL code may reference, including:
- Library types (_.TypeName references)
- Global data blocks ("DBName".member access)
- External function blocks

These utilities help create mocks and stubs for testing SCL code that
depends on external definitions.
"""

from dataclasses import dataclass, field, make_dataclass
from typing import Any


@dataclass
class ExternalType:
    """Represents an external type reference.

    Attributes
    ----------
    name : str
        The type name (without _.prefix).
    fields : dict[str, Any]
        Field name to default value mapping.
    """

    name: str
    fields: dict[str, Any] = field(default_factory=dict)


def create_stub_type(
    name: str,
    fields: dict[str, type] | None = None,
    defaults: dict[str, Any] | None = None,
) -> type:
    """Create a stub dataclass for an external type.

    This function generates a dataclass at runtime that can be used
    as a stand-in for external library types.

    Parameters
    ----------
    name : str
        The class name.
    fields : dict[str, type] | None
        Field name to type mapping. Defaults to empty dict.
    defaults : dict[str, Any] | None
        Field name to default value mapping.

    Returns
    -------
    type
        A dynamically created dataclass.

    Examples
    --------
    >>> StubType = create_stub_type(
    ...     "typeUnitParameter",
    ...     fields={"enabled": bool, "value": float},
    ...     defaults={"enabled": False, "value": 0.0}
    ... )
    >>> instance = StubType()
    >>> instance.enabled
    False
    """
    fields = fields or {}
    defaults = defaults or {}

    # Build field definitions for make_dataclass
    field_defs: list[tuple[str, type, Any]] = []

    for field_name, field_type in fields.items():
        if field_name in defaults:
            default_val = defaults[field_name]
            # Use field() for mutable defaults
            if isinstance(default_val, (list, dict)):

                def make_copy_factory(d: Any = default_val) -> Any:
                    return d.copy()

                field_defs.append((field_name, field_type, field(default_factory=make_copy_factory)))
            else:
                field_defs.append((field_name, field_type, default_val))
        else:
            # No default - use type's natural default
            if field_type is bool:
                field_defs.append((field_name, field_type, False))
            elif field_type in (int, float):
                field_defs.append((field_name, field_type, 0))
            elif field_type is str:
                field_defs.append((field_name, field_type, ""))
            else:
                field_defs.append((field_name, field_type, None))

    return make_dataclass(name, field_defs)


def create_stub_from_spec(
    name: str,
    spec: dict[str, str],
) -> type:
    """Create a stub type from a simple specification.

    Parameters
    ----------
    name : str
        The class name.
    spec : dict[str, str]
        Field name to type string mapping.
        Supported types: "bool", "int", "float", "str"

    Returns
    -------
    type
        A dynamically created dataclass.

    Examples
    --------
    >>> StubType = create_stub_from_spec(
    ...     "typeUnitInput",
    ...     {"percCollarSwitch": "bool", "value": "float"}
    ... )
    """
    type_map = {
        "bool": bool,
        "Bool": bool,
        "int": int,
        "Int": int,
        "DInt": int,
        "float": float,
        "Real": float,
        "LReal": float,
        "str": str,
        "String": str,
    }

    fields = {}
    for field_name, type_str in spec.items():
        fields[field_name] = type_map.get(type_str, Any)

    return create_stub_type(name, fields)


@dataclass
class MockDataBlock:
    """A mock data block for testing.

    This class provides a flexible mock data block that can be
    configured with arbitrary fields for testing purposes.

    Attributes
    ----------
    _name : str
        The data block name.
    _data : dict[str, Any]
        Internal data storage.
    """

    _name: str
    _data: dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, name: str) -> Any:
        """Get a field value.

        Parameters
        ----------
        name : str
            The field name.

        Returns
        -------
        Any
            The field value.

        Raises
        ------
        AttributeError
            If field not found.
        """
        if name.startswith("_"):
            return super().__getattribute__(name)
        try:
            data = super().__getattribute__("_data")
            if name in data:
                return data[name]
        except AttributeError:
            pass
        raise AttributeError(f"'{self._name}' has no field '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        """Set a field value.

        Parameters
        ----------
        name : str
            The field name.
        value : Any
            The value to set.
        """
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            self._data[name] = value

    def __repr__(self) -> str:
        """String representation."""
        return f"MockDataBlock({self._name!r}, {self._data})"


def create_mock_db(
    name: str,
    structure: dict[str, Any] | None = None,
) -> MockDataBlock:
    """Create a mock data block with initial structure.

    Parameters
    ----------
    name : str
        The data block name (e.g., "ProcessData").
    structure : dict[str, Any] | None
        Initial field name to value mapping.

    Returns
    -------
    MockDataBlock
        The configured mock data block.

    Examples
    --------
    >>> db = create_mock_db("ProcessData", {
    ...     "armCount": 4,
    ...     "status": {"active": True}
    ... })
    >>> db.armCount
    4
    """
    mock = MockDataBlock(_name=name, _data=structure or {})
    return mock


@dataclass
class NestedMockDB:
    """A mock data block that supports nested attribute access.

    This allows creating mock DBs with deeply nested structures
    like "DB".arm[0].parameter.value.

    Attributes
    ----------
    _name : str
        The data block name.
    _data : dict[str, Any]
        Internal data storage.
    """

    _name: str = ""
    _data: dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, name: str) -> Any:
        """Get a field, creating nested mock if needed."""
        if name.startswith("_"):
            return super().__getattribute__(name)
        try:
            data = super().__getattribute__("_data")
            if name in data:
                val = data[name]
                # If dict, wrap in NestedMockDB for chained access
                if isinstance(val, dict):
                    return NestedMockDB(_name=f"{self._name}.{name}", _data=val)
                return val
            # Auto-create nested mock for unknown attributes
            nested = NestedMockDB(_name=f"{self._name}.{name}")
            data[name] = nested._data
            return nested
        except AttributeError:
            pass
        raise AttributeError(f"'{self._name}' has no field '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        """Set a field value."""
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            self._data[name] = value

    def __getitem__(self, index: int) -> Any:
        """Support array indexing."""
        key = f"[{index}]"
        if key not in self._data:
            self._data[key] = {}
        val = self._data[key]
        if isinstance(val, dict):
            return NestedMockDB(_name=f"{self._name}{key}", _data=val)
        return val

    def __setitem__(self, index: int, value: Any) -> None:
        """Support array indexing for assignment."""
        self._data[f"[{index}]"] = value

    def __repr__(self) -> str:
        """String representation."""
        return f"NestedMockDB({self._name!r})"


def create_nested_mock_db(
    name: str,
    structure: dict[str, Any] | None = None,
) -> NestedMockDB:
    """Create a mock data block with nested attribute support.

    Parameters
    ----------
    name : str
        The data block name.
    structure : dict[str, Any] | None
        Initial nested structure.

    Returns
    -------
    NestedMockDB
        The configured mock.

    Examples
    --------
    >>> db = create_nested_mock_db("ArmData")
    >>> db.arm.position = 45.0
    >>> db.arm.position
    45.0
    """
    return NestedMockDB(_name=name, _data=structure or {})


@dataclass
class DependencyRegistry:
    """Registry for managing external dependencies.

    This class provides a central registry for external types
    and data blocks, making it easier to set up test environments.

    Attributes
    ----------
    types : dict[str, type]
        Registered external types.
    dbs : dict[str, Any]
        Registered data blocks.
    """

    types: dict[str, type] = field(default_factory=dict)
    dbs: dict[str, Any] = field(default_factory=dict)

    def register_type(self, name: str, type_class: type) -> None:
        """Register an external type.

        Parameters
        ----------
        name : str
            Type name (with or without _.prefix).
        type_class : type
            The type class (dataclass).
        """
        clean_name = name.lstrip("_").lstrip(".")
        self.types[clean_name] = type_class

    def register_stub(
        self,
        name: str,
        fields: dict[str, type] | None = None,
        defaults: dict[str, Any] | None = None,
    ) -> type:
        """Register a stub type.

        Parameters
        ----------
        name : str
            Type name.
        fields : dict[str, type] | None
            Field definitions.
        defaults : dict[str, Any] | None
            Default values.

        Returns
        -------
        type
            The created stub class.
        """
        stub = create_stub_type(name, fields, defaults)
        self.register_type(name, stub)
        return stub

    def get_type(self, name: str) -> type | None:
        """Get a registered type.

        Parameters
        ----------
        name : str
            Type name.

        Returns
        -------
        type | None
            The type class, or None if not found.
        """
        clean_name = name.lstrip("_").lstrip(".")
        return self.types.get(clean_name)

    def has_type(self, name: str) -> bool:
        """Check if a type is registered.

        Parameters
        ----------
        name : str
            Type name.

        Returns
        -------
        bool
            True if registered.
        """
        return self.get_type(name) is not None

    def register_db(self, name: str, db: Any) -> None:
        """Register a data block.

        Parameters
        ----------
        name : str
            Data block name.
        db : Any
            The data block object.
        """
        self.dbs[name] = db

    def create_mock_db(
        self,
        name: str,
        structure: dict[str, Any] | None = None,
        nested: bool = False,
    ) -> Any:
        """Create and register a mock data block.

        Parameters
        ----------
        name : str
            Data block name.
        structure : dict[str, Any] | None
            Initial structure.
        nested : bool
            If True, create NestedMockDB for deep access.

        Returns
        -------
        Any
            The created mock.
        """
        mock: MockDataBlock | NestedMockDB
        if nested:
            mock = create_nested_mock_db(name, structure)
        else:
            mock = create_mock_db(name, structure)
        self.dbs[name] = mock
        return mock

    def get_db(self, name: str) -> Any:
        """Get a registered data block.

        Parameters
        ----------
        name : str
            Data block name.

        Returns
        -------
        Any
            The data block.

        Raises
        ------
        KeyError
            If not found.
        """
        if name not in self.dbs:
            raise KeyError(f"Data block '{name}' not registered")
        return self.dbs[name]

    def apply_to_runtime(self, runtime: Any) -> None:
        """Apply all registered DBs to a PLCRuntime.

        Parameters
        ----------
        runtime : PLCRuntime
            The runtime to configure.
        """
        for name, db in self.dbs.items():
            runtime.register_db(name, db)

    def get_compile_globals(self) -> dict[str, Any]:
        """Get globals dict for compile_block/compile_udt.

        Returns
        -------
        dict[str, Any]
            Dictionary of type names to classes.
        """
        return self.types.copy()
