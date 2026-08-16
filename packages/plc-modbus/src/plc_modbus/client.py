"""Async Modbus TCP client wrapping pymodbus.

The :class:`ModbusClient` exposes a small, focused API tailored for PLC
integration testing — read-only access to holding/input registers, coils
and discrete inputs, plus a register-address parser that lets the caller
write paths like ``"HOLDING:42"`` or ``"HOLDING:42/3"`` directly in YAML.

Writes are intentionally not exposed at this stage: the integration test
flow is to stimulate the process side via the existing OPC UA client, then
verify the Modbus mirror reflects the change. Adding write support later
is straightforward if needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from plc_modbus.config import ModbusConfig


class ModbusConnectionError(RuntimeError):
    """Raised when the Modbus TCP connection fails or drops."""


class ModbusReadError(RuntimeError):
    """Raised when a Modbus read returns an error response."""


# Supported register-area prefixes mapped to the pymodbus read function name.
_AREA_HOLDING = "HOLDING"
_AREA_INPUT = "INPUT"
_AREA_COIL = "COIL"
_AREA_DISCRETE = "DISCRETE"
_VALID_AREAS = frozenset({_AREA_HOLDING, _AREA_INPUT, _AREA_COIL, _AREA_DISCRETE})


@dataclass(frozen=True)
class RegisterAddress:
    """Parsed Modbus register address.

    Attributes
    ----------
    area : str
        One of ``HOLDING``, ``INPUT``, ``COIL``, ``DISCRETE``.
    address : int
        Zero-based register/coil index.
    bit : int | None
        For ``HOLDING:N/B`` / ``INPUT:N/B`` syntax, the bit position 0..15
        within the 16-bit word. ``None`` if the address refers to the
        whole word (or a coil/discrete which is already a bit).
    """

    area: str
    address: int
    bit: int | None = None

    @property
    def is_bit(self) -> bool:
        """Whether the address targets a single bit (coil, discrete, or N/B)."""
        return self.area in (_AREA_COIL, _AREA_DISCRETE) or self.bit is not None


_ADDR_RE = re.compile(r"^(?P<area>[A-Z]+):(?P<addr>\d+)(?:/(?P<bit>\d+))?$")


def parse_register_address(spec: str) -> RegisterAddress:
    """Parse a register specifier such as ``"HOLDING:42"`` or ``"HOLDING:42/3"``.

    Examples
    --------
    >>> parse_register_address("HOLDING:0")
    RegisterAddress(area='HOLDING', address=0, bit=None)
    >>> parse_register_address("HOLDING:5/3")
    RegisterAddress(area='HOLDING', address=5, bit=3)
    >>> parse_register_address("COIL:7")
    RegisterAddress(area='COIL', address=7, bit=None)

    Raises
    ------
    ValueError
        If the format is malformed, the area unknown, or the bit out of range.
    """
    match = _ADDR_RE.match(spec.strip())
    if match is None:
        raise ValueError(
            f"Invalid Modbus register address {spec!r}; expected "
            "'AREA:ADDRESS' or 'AREA:ADDRESS/BIT' (e.g. 'HOLDING:42', 'HOLDING:5/3')"
        )

    area = match.group("area")
    if area not in _VALID_AREAS:
        raise ValueError(f"Unknown Modbus area {area!r} in {spec!r}; " f"valid areas: {sorted(_VALID_AREAS)}")

    address = int(match.group("addr"))
    if address < 0:
        raise ValueError(f"Negative address {address} in {spec!r}")

    bit_str = match.group("bit")
    bit: int | None = None
    if bit_str is not None:
        bit = int(bit_str)
        if not 0 <= bit <= 15:
            raise ValueError(f"Bit {bit} out of range in {spec!r}; must be 0..15")
        if area not in (_AREA_HOLDING, _AREA_INPUT):
            raise ValueError(
                f"Bit indexing 'AREA:N/B' only valid for HOLDING/INPUT, got {area!r} in {spec!r}"
            )

    return RegisterAddress(area=area, address=address, bit=bit)


def decode_value(reg: int, dtype: str) -> Any:
    """Decode a 16-bit Modbus register value to a Python type.

    Supported dtypes:

    - ``uint16`` (default): integer 0..65535
    - ``int16``: signed integer -32768..32767
    - ``word``: same as uint16, kept as alias
    - ``bool``: True if non-zero, False otherwise
    """
    dtype = dtype.lower()
    if dtype in ("uint16", "word"):
        return reg & 0xFFFF
    if dtype == "int16":
        v = reg & 0xFFFF
        return v - 0x10000 if v >= 0x8000 else v
    if dtype == "bool":
        return reg != 0
    raise ValueError(f"Unsupported dtype {dtype!r}; valid: uint16, int16, word, bool")


class ModbusClient:
    """Async Modbus TCP client.

    Wraps :class:`pymodbus.client.AsyncModbusTcpClient` with a smaller
    surface tailored for tests:

    - context-manager (``async with``) handles connect/close
    - read methods raise :class:`ModbusConnectionError` / :class:`ModbusReadError`
      on failure (no silent error responses)
    - :meth:`read_register_at` accepts a string address spec and returns
      the decoded value

    Example
    -------
    >>> from plc_modbus import ModbusClient, ModbusConfig
    >>> async with ModbusClient(ModbusConfig(host="192.168.1.50")) as mb:
    ...     value = await mb.read_register_at("HOLDING:0", dtype="uint16")
    """

    def __init__(self, config: ModbusConfig) -> None:
        self._config = config
        self._client: Any = None  # AsyncModbusTcpClient, lazy import

    async def __aenter__(self) -> ModbusClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        """Open the TCP connection."""
        from pymodbus.client import AsyncModbusTcpClient

        self._client = AsyncModbusTcpClient(
            host=self._config.host,
            port=self._config.port,
            timeout=self._config.timeout_s,
        )
        ok = await self._client.connect()
        if not ok or not self._client.connected:
            raise ModbusConnectionError(
                f"Failed to connect to Modbus TCP server " f"{self._config.host}:{self._config.port}"
            )

    async def disconnect(self) -> None:
        """Close the TCP connection."""
        if self._client is not None:
            self._client.close()
            self._client = None

    @property
    def connected(self) -> bool:
        """True while the underlying TCP connection is open."""
        return self._client is not None and self._client.connected

    async def read_holding_registers(self, address: int, count: int = 1) -> list[int]:
        """Read ``count`` holding registers starting at ``address``."""
        return await self._read("read_holding_registers", address, count)

    async def read_input_registers(self, address: int, count: int = 1) -> list[int]:
        """Read ``count`` input registers starting at ``address``."""
        return await self._read("read_input_registers", address, count)

    async def read_coils(self, address: int, count: int = 1) -> list[bool]:
        """Read ``count`` coils starting at ``address``."""
        return await self._read_bits("read_coils", address, count)

    async def read_discrete_inputs(self, address: int, count: int = 1) -> list[bool]:
        """Read ``count`` discrete inputs starting at ``address``."""
        return await self._read_bits("read_discrete_inputs", address, count)

    async def read_register_at(self, spec: str, dtype: str = "uint16") -> Any:
        """Read a single register by spec like ``"HOLDING:42"`` or ``"HOLDING:5/3"``.

        For ``COIL:N`` / ``DISCRETE:N`` the ``dtype`` is ignored (always bool).
        For ``HOLDING:N/B`` / ``INPUT:N/B`` returns a bool.
        Otherwise the register is decoded via :func:`decode_value`.
        """
        block = await self.read_register_block(spec, 1, dtype)
        return next(iter(block.values()))

    async def read_register_block(self, spec: str, count: int = 1, dtype: str = "uint16") -> dict[str, Any]:
        """Read ``count`` consecutive values starting at ``spec``, keyed by address.

        Returns an insertion-ordered mapping of each register's own spec to its
        decoded value — ``{"HOLDING:10": 42, "HOLDING:11": 99}`` — rather than a
        bare list. The keys are rebuilt from the *parsed* address, which is what
        lets a caller that cannot parse a register spec itself (plc-core must not
        import plc-modbus) still report which address produced which value.

        Parameters
        ----------
        spec : str
            Starting address, ``"AREA:ADDRESS"`` or ``"AREA:ADDRESS/BIT"``.
        count : int
            How many consecutive registers/coils to read. Must be >= 1, and
            must be 1 for a ``/BIT`` spec.
        dtype : str
            Decoding applied to every whole register read; ignored for
            ``COIL``/``DISCRETE`` and for a ``/BIT`` spec, which are bools.

        Raises
        ------
        ValueError
            If ``count`` is below 1, or above 1 for a ``/BIT`` spec.
        ModbusReadError
            If the server returns fewer values than requested.
        """
        if count < 1:
            raise ValueError(f"count must be at least 1, got {count} for {spec!r}")

        addr = parse_register_address(spec)
        if addr.bit is not None and count > 1:
            raise ValueError(
                f"Cannot read {count} registers from the bit spec {spec!r}: "
                "'AREA:ADDRESS/BIT' selects one bit of one word, so a range has no "
                "meaning. Drop the '/BIT' suffix to read consecutive whole registers."
            )

        values: list[Any]
        if addr.area == _AREA_COIL:
            values = list(await self.read_coils(addr.address, count))
        elif addr.area == _AREA_DISCRETE:
            values = list(await self.read_discrete_inputs(addr.address, count))
        else:
            regs = (
                await self.read_holding_registers(addr.address, count)
                if addr.area == _AREA_HOLDING
                else await self.read_input_registers(addr.address, count)
            )
            if addr.bit is not None:
                values = [bool((regs[0] >> addr.bit) & 0x1)] if regs else []
            else:
                values = [decode_value(word, dtype) for word in regs]

        if len(values) != count:
            raise ModbusReadError(f"Read of {count} value(s) from {spec!r} returned {len(values)}")

        if addr.bit is not None:
            keys = [f"{addr.area}:{addr.address}/{addr.bit}"]
        else:
            keys = [f"{addr.area}:{addr.address + offset}" for offset in range(count)]
        return dict(zip(keys, values, strict=True))

    async def _read(self, method: str, address: int, count: int) -> list[int]:
        if self._client is None:
            raise ModbusConnectionError("ModbusClient not connected")
        fn = getattr(self._client, method)
        try:
            response = await fn(address=address, count=count, device_id=self._config.unit_id)
        except Exception as e:  # pragma: no cover - pymodbus exceptions are diverse
            raise ModbusReadError(
                f"{method}(address={address}, count={count}) raised {type(e).__name__}: {e}"
            ) from e
        if response.isError():
            raise ModbusReadError(f"{method}(address={address}, count={count}) returned error: {response}")
        return list(response.registers)

    async def _read_bits(self, method: str, address: int, count: int) -> list[bool]:
        if self._client is None:
            raise ModbusConnectionError("ModbusClient not connected")
        fn = getattr(self._client, method)
        try:
            response = await fn(address=address, count=count, device_id=self._config.unit_id)
        except Exception as e:  # pragma: no cover
            raise ModbusReadError(
                f"{method}(address={address}, count={count}) raised {type(e).__name__}: {e}"
            ) from e
        if response.isError():
            raise ModbusReadError(f"{method}(address={address}, count={count}) returned error: {response}")
        return [bool(b) for b in response.bits[:count]]
