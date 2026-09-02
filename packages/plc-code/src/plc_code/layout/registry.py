"""Registry of user data types, built from `TYPE` blocks on disk."""

from __future__ import annotations

from pathlib import Path

from plc_code.parser import parse_scl_file
from plc_code.parser.models import Block, UserDataType
from plc_code.parser.parser import ParseError
from plc_code.project.discovery import discover_blocks


class UnknownTypeError(KeyError):
    """A UDT name that no registered `TYPE` block declares.

    Attributes
    ----------
    name : str
        The type name that was not found.
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name

    def __str__(self) -> str:
        return f"unknown user data type {self.name!r}"


def normalize_type_name(name: str) -> str:
    """Normalize type names so they resolve to the same type.

    Type references can be written as ``_.typeX`` (prefixed), ``"typeX"``
    (quoted), or ``typeX`` (bare). This function normalizes all three forms
    to a canonical unquoted name. Quoted prefixes (e.g., ``"_.typeX"``) are
    handled by stripping quotes first, then the prefix, then quotes again.

    Parameters
    ----------
    name : str
        A type name in any of the three forms.

    Returns
    -------
    str
        The normalized type name.
    """
    name = name.strip()
    name = name.strip('"')
    if name.startswith("_."):
        name = name[2:]
    return name.strip('"')


class TypeRegistry:
    """UDT definitions keyed by name.

    Collects user-defined type blocks (TYPE ... END_TYPE) from a directory
    tree and makes them queryable by name, with case-sensitive matching on
    the normalized type name.

    Attributes
    ----------
    _types : dict[str, UserDataType]
        Mapping of normalized type names to UserDataType objects.
    problems : list[str]
        Files that failed to parse, recorded as ``f"{path}: {message}"``.
    """

    def __init__(self) -> None:
        self._types: dict[str, UserDataType] = {}
        self.problems: list[str] = []

    @classmethod
    def from_directories(cls, *directories: Path) -> TypeRegistry:
        """Parse every ``.s7dcl`` under ``directories`` and keep the `TYPE` blocks.

        Recursively discovers all ``.s7dcl`` files in the given directories,
        parses them, and registers any TYPE blocks found. Files that fail to
        parse are recorded in ``registry.problems`` and skipped.

        Parameters
        ----------
        *directories : Path
            One or more directory paths to scan.

        Returns
        -------
        TypeRegistry
            A new registry populated with all TYPE blocks found. Check
            ``registry.problems`` for any parse errors encountered.
        """
        registry = cls()
        for directory in directories:
            for block_file in discover_blocks(directory):
                try:
                    block = parse_scl_file(block_file.source_path)
                    registry.add(block)
                except ParseError as e:
                    registry.problems.append(f"{block_file.source_path}: {e}")
        return registry

    def add(self, block: Block) -> None:
        """Register a TYPE block if it contains a user data type.

        Parameters
        ----------
        block : Block
            A parsed block. Only blocks with ``block_type == "TYPE"`` and a
            non-None ``user_data_type`` are registered; others are ignored.
        """
        if block.block_type == "TYPE" and block.user_data_type is not None:
            self._types[normalize_type_name(block.user_data_type.name)] = block.user_data_type

    def get(self, name: str) -> UserDataType:
        """Look up a registered type by name.

        Parameters
        ----------
        name : str
            The type name, in any of the forms recognized by ``normalize_type_name``.

        Returns
        -------
        UserDataType
            The registered type.

        Raises
        ------
        UnknownTypeError
            If the normalized name is not registered.
        """
        try:
            return self._types[normalize_type_name(name)]
        except KeyError:
            raise UnknownTypeError(normalize_type_name(name)) from None

    def __contains__(self, name: object) -> bool:
        """Check whether a type name is registered.

        Parameters
        ----------
        name : object
            The name to check (must be a string for True; other types return
            False).

        Returns
        -------
        bool
            True if the normalized name is in the registry.
        """
        return isinstance(name, str) and normalize_type_name(name) in self._types

    def __len__(self) -> int:
        """Return the number of registered types.

        Returns
        -------
        int
            The count of unique types in the registry.
        """
        return len(self._types)
