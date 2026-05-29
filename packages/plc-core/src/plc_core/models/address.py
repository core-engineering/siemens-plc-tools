"""PLC address model with format conversion support.

This module provides the PLCAddress class for representing and converting
between S7-1500 and IOL address formats.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PLCAddress:
    """Represents a PLC memory address with format conversion support.

    Supports conversion between S7-1500 format (e.g., %I1.0) and
    IOL format (e.g., E 1.0).

    Attributes
    ----------
    address_type : str
        Address type prefix (I, Q, M, IW, QW, MW, etc.).
    byte_address : int
        Byte address number.
    bit_address : int | None
        Bit address number (None for word addresses).

    Example
    -------
    >>> addr = PLCAddress.from_s7_format("%I1.0")
    >>> print(addr.to_iol_format())
    E 1.0
    >>> addr2 = PLCAddress.from_iol_format("PEW 70")
    >>> print(addr2.to_s7_format())
    %IW70
    """

    address_type: str
    byte_address: int
    bit_address: int | None = None

    @classmethod
    def from_s7_format(cls, address: str) -> PLCAddress | None:
        """Parse S7-1500 format address.

        Parameters
        ----------
        address : str
            S7 format address string (e.g., %I1.0, %Q0.2, %IW70, %MW100).

        Returns
        -------
        PLCAddress | None
            PLCAddress instance or None if parsing fails.

        Example
        -------
        >>> PLCAddress.from_s7_format("%I1.0")
        PLCAddress(address_type='I', byte_address=1, bit_address=0)
        """
        if not address:
            return None

        addr = address.strip().lstrip("%")
        if not addr:
            return None

        # Word addresses: IW, QW, MW, PIW, PQW, etc.
        for prefix in ("IW", "QW", "MW", "PIW", "PQW"):
            if addr.upper().startswith(prefix):
                try:
                    byte_addr = int(addr[len(prefix) :])
                    return cls(address_type=prefix.upper(), byte_address=byte_addr)
                except ValueError:
                    return None

        # Bit addresses: I, Q, M with byte.bit format
        for prefix in ("I", "Q", "M"):
            if addr.upper().startswith(prefix) and not addr.upper().startswith((prefix + "W", prefix + "D")):
                rest = addr[len(prefix) :]
                if "." in rest:
                    try:
                        byte_str, bit_str = rest.split(".", 1)
                        return cls(
                            address_type=prefix.upper(),
                            byte_address=int(byte_str),
                            bit_address=int(bit_str),
                        )
                    except ValueError:
                        return None
                else:
                    try:
                        return cls(address_type=prefix.upper(), byte_address=int(rest))
                    except ValueError:
                        return None

        return None

    @classmethod
    def from_iol_format(cls, address: str) -> PLCAddress | None:
        """Parse IOL format address.

        IOL uses German notation:
        - E (Eingang) = Input = I
        - A (Ausgang) = Output = Q
        - M (Merker) = Memory = M
        - PEW = Peripheral Input Word = IW
        - PAW = Peripheral Output Word = QW

        Parameters
        ----------
        address : str
            IOL format address string (e.g., E 1.0, A 0.2, PEW 70).

        Returns
        -------
        PLCAddress | None
            PLCAddress instance or None if parsing fails.

        Example
        -------
        >>> PLCAddress.from_iol_format("E 1.0")
        PLCAddress(address_type='I', byte_address=1, bit_address=0)
        """
        if not address:
            return None

        addr = address.strip().upper()
        if not addr:
            return None

        # Try word addresses first
        for iol_prefix, s7_prefix in [
            ("PEW", "IW"),
            ("PAW", "QW"),
            ("EW", "IW"),
            ("AW", "QW"),
            ("MW", "MW"),
        ]:
            if addr.startswith(iol_prefix):
                rest = addr[len(iol_prefix) :].strip()
                try:
                    return cls(address_type=s7_prefix, byte_address=int(rest))
                except ValueError:
                    return None

        # Bit addresses
        for iol_prefix, s7_prefix in [("E", "I"), ("A", "Q"), ("M", "M")]:
            if addr.startswith(iol_prefix) and not addr.startswith(("EW", "AW")):
                rest = addr[len(iol_prefix) :].strip()
                if "." in rest:
                    try:
                        byte_str, bit_str = rest.split(".", 1)
                        return cls(
                            address_type=s7_prefix,
                            byte_address=int(byte_str),
                            bit_address=int(bit_str),
                        )
                    except ValueError:
                        return None
                else:
                    try:
                        return cls(address_type=s7_prefix, byte_address=int(rest))
                    except ValueError:
                        return None

        return None

    def to_s7_format(self) -> str:
        """Convert to S7-1500 format string.

        Returns
        -------
        str
            Address in S7 format (e.g., %I1.0, %IW70).
        """
        if self.bit_address is not None:
            return f"%{self.address_type}{self.byte_address}.{self.bit_address}"
        return f"%{self.address_type}{self.byte_address}"

    def to_iol_format(self) -> str:
        """Convert to IOL format string.

        Returns
        -------
        str
            Address in IOL format (e.g., E 1.0, PEW 70).
        """
        s7_to_iol = {
            "I": "E",
            "Q": "A",
            "M": "M",
            "IW": "PEW",
            "QW": "PAW",
            "MW": "MW",
        }
        iol_type = s7_to_iol.get(self.address_type, self.address_type)
        if self.bit_address is not None:
            return f"{iol_type} {self.byte_address}.{self.bit_address}"
        return f"{iol_type} {self.byte_address}"

    def __str__(self) -> str:
        """Return S7 format representation."""
        return self.to_s7_format()
