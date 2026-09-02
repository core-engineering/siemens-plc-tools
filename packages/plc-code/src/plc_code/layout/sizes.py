"""Elementary S7 type sizes for standard-access data blocks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ElementarySize:
    """Size of an elementary type; ``bits == 1`` only for Bool.

    Attributes
    ----------
    bits : int
        Size in bits. For Bool, bits = 1; for all other types, bits is a multiple of 8.
    """

    bits: int

    @property
    def bytes(self) -> int:
        """Size in bytes, with Bool (1 bit) rounded to 1 byte.

        Returns
        -------
        int
            Size in bytes.
        """
        return max(1, self.bits // 8)


_BITS: dict[str, int] = {
    "bool": 1,
    "byte": 8,
    "char": 8,
    "sint": 8,
    "usint": 8,
    "int": 16,
    "uint": 16,
    "word": 16,
    "date": 16,
    "wchar": 16,
    "dint": 32,
    "udint": 32,
    "dword": 32,
    "real": 32,
    "time": 32,
    "time_of_day": 32,
    "tod": 32,
    "lint": 64,
    "ulint": 64,
    "lword": 64,
    "lreal": 64,
    "ltime": 64,
    "ltod": 64,
    "ltime_of_day": 64,
    "ldt": 64,
    "date_and_time": 64,
    "dt": 64,
    "dtl": 96,
}


def elementary_size(name: str) -> ElementarySize | None:
    """Size of ``name`` (case-insensitive), or None for a UDT, Struct, String, WString.

    Parameters
    ----------
    name : str
        The name of an S7 type (e.g., "Int", "Bool", "lreal").

    Returns
    -------
    ElementarySize | None
        An ElementarySize with the bits for the type, or None if the name is not a
        standard elementary type.
    """
    bits = _BITS.get(name.lower())
    return ElementarySize(bits) if bits is not None else None
