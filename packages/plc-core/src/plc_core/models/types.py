"""PLC data types and I/O category enumerations.

This module provides enumerations for common PLC data types and I/O categories.
"""

from __future__ import annotations

from enum import Enum


class IOCategory(str, Enum):
    """I/O signal categories.

    Attributes
    ----------
    DI : str
        Digital Input.
    DO : str
        Digital Output.
    AI : str
        Analog Input.
    AO : str
        Analog Output.
    SDI : str
        Safety Digital Input.
    SDO : str
        Safety Digital Output.
    SAI : str
        Safety Analog Input.
    SAO : str
        Safety Analog Output.
    """

    DI = "DI"
    DO = "DO"
    AI = "AI"
    AO = "AO"
    SDI = "SDI"
    SDO = "SDO"
    SAI = "SAI"
    SAO = "SAO"

    @property
    def is_input(self) -> bool:
        """Check if this is an input category."""
        return self in (IOCategory.DI, IOCategory.AI, IOCategory.SDI, IOCategory.SAI)

    @property
    def is_output(self) -> bool:
        """Check if this is an output category."""
        return self in (IOCategory.DO, IOCategory.AO, IOCategory.SDO, IOCategory.SAO)

    @property
    def is_digital(self) -> bool:
        """Check if this is a digital category."""
        return self in (IOCategory.DI, IOCategory.DO, IOCategory.SDI, IOCategory.SDO)

    @property
    def is_analog(self) -> bool:
        """Check if this is an analog category."""
        return self in (IOCategory.AI, IOCategory.AO, IOCategory.SAI, IOCategory.SAO)

    @property
    def is_safety(self) -> bool:
        """Check if this is a safety category."""
        return self in (IOCategory.SDI, IOCategory.SDO, IOCategory.SAI, IOCategory.SAO)

    @classmethod
    def from_mnemonic_prefix(cls, prefix: str) -> IOCategory | None:
        """Get IOCategory from mnemonic prefix.

        Parameters
        ----------
        prefix : str
            Mnemonic prefix (e.g., "DI", "DO", "AI").

        Returns
        -------
        IOCategory | None
            Matching category or None if not found.
        """
        try:
            return cls(prefix.upper())
        except ValueError:
            return None


class DataType(str, Enum):
    """PLC data types.

    Attributes
    ----------
    BOOL : str
        Boolean type.
    INT : str
        16-bit signed integer.
    DINT : str
        32-bit signed integer.
    REAL : str
        32-bit floating point.
    WORD : str
        16-bit unsigned.
    DWORD : str
        32-bit unsigned.
    STRING : str
        Character string.
    TIME : str
        Time duration.
    DATE : str
        Date value.
    TOD : str
        Time of day.
    DT : str
        Date and time.
    """

    BOOL = "Bool"
    INT = "Int"
    DINT = "DInt"
    REAL = "Real"
    WORD = "Word"
    DWORD = "DWord"
    STRING = "String"
    TIME = "Time"
    DATE = "Date"
    TOD = "TOD"
    DT = "DT"

    @classmethod
    def from_string(cls, value: str) -> DataType:
        """Parse data type from string.

        Parameters
        ----------
        value : str
            Data type name (case-insensitive).

        Returns
        -------
        DataType
            Matching type, defaults to BOOL if not found.
        """
        normalized = value.strip().lower()
        mapping = {
            "bool": cls.BOOL,
            "boolean": cls.BOOL,
            "int": cls.INT,
            "integer": cls.INT,
            "dint": cls.DINT,
            "real": cls.REAL,
            "float": cls.REAL,
            "word": cls.WORD,
            "dword": cls.DWORD,
            "string": cls.STRING,
            "time": cls.TIME,
            "date": cls.DATE,
            "tod": cls.TOD,
            "dt": cls.DT,
        }
        return mapping.get(normalized, cls.BOOL)
