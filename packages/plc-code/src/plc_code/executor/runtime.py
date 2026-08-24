"""PLC runtime simulation for SCL execution.

This module provides the runtime environment for executing transpiled
SCL code, including clock simulation and global data block management.
"""

import atexit
import json
import os
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from plc_code.executor.models import python_identifier
from plc_code.parser.models import BlockType

# Matches a scalar constant declaration inside a DATA_BLOCK VAR section:
#   NAME : Type := value;
_DB_CONST_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*:\s*\w+\s*:=\s*([^;]+);", re.MULTILINE)

# Matches an array member declaration with bounds:
#   NAME : Array[lo..hi] of Type;
_DB_ARRAY_DECL_RE = re.compile(
    r"^\s*([A-Za-z_]\w*)\s*:\s*Array\[\s*(-?\d+)\s*\.\.\s*(-?\d+)\s*\]\s*of\s+\w+\s*;",
    re.MULTILINE | re.IGNORECASE,
)

# Matches an array element initialiser:
#   NAME[idx] := value;
_DB_ARRAY_ELEM_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*\[\s*(-?\d+)\s*\]\s*:=\s*([^;]+);", re.MULTILINE)


def _convert_db_literal(raw: str) -> Any:
    """Convert an SCL literal from a DATA_BLOCK default to a Python value."""
    value = raw.strip()
    lowered = value.lower()
    if lowered.startswith("16#"):
        return int(value[3:], 16)
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value.strip('"')


def load_data_block(path: str | Path) -> SimpleNamespace:
    """Load a constant ``DATA_BLOCK`` ``.s7dcl`` file into an attribute namespace.

    Each ``NAME : Type := value;`` scalar declaration in the block's ``VAR``
    section becomes an attribute with its converted Python value. Array members
    declared as ``NAME : Array[lo..hi] of Type;`` and filled by ``NAME[idx] :=
    value;`` initialisers become a 0-based Python ``list`` (so that
    ``"DbName".MEMBER`` and ``RD_ARRAY_DI`` can read them at execution time).

    Parameters
    ----------
    path : str | Path
        Path to the DATA_BLOCK ``.s7dcl`` file.

    Returns
    -------
    SimpleNamespace
        Namespace exposing each scalar constant and array member as an attribute.
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    members: dict[str, Any] = {name: _convert_db_literal(raw) for name, raw in _DB_CONST_RE.findall(text)}

    # Array members: the declaration gives the (0-based) size, the element
    # initialisers give the values. Missing elements default to 0.
    arrays: dict[str, list[Any]] = {}
    for name, _lo, hi in _DB_ARRAY_DECL_RE.findall(text):
        arrays[name] = [0] * (int(hi) + 1)
    for name, idx, raw in _DB_ARRAY_ELEM_RE.findall(text):
        index = int(idx)
        if name not in arrays:
            # Initialiser without a matching declaration: size to the max index seen.
            arrays[name] = []
        if index >= len(arrays[name]):
            arrays[name].extend([0] * (index + 1 - len(arrays[name])))
        arrays[name][index] = _convert_db_literal(raw)
    members.update(arrays)

    return SimpleNamespace(**members)


class _GlobalDBs(dict):
    """Dict of global data blocks that lazily auto-loads constant DBs.

    On access to a missing key, the matching ``<name>.s7dcl`` is searched for in
    the owning runtime's ``block_search_paths``; if it is a ``DATA_BLOCK`` it is
    loaded via :func:`load_data_block` and cached.  ``__contains__`` is *not*
    overridden, so ``name in runtime.global_dbs`` stays False for unregistered
    blocks (``get_db`` keeps raising for genuinely unknown names).
    """

    def __init__(self, runtime: "PLCRuntime") -> None:
        super().__init__()
        self._runtime = runtime

    def __missing__(self, key: str) -> Any:
        for search_dir in self._runtime.block_search_paths:
            candidate = Path(search_dir) / f"{key}.s7dcl"
            if candidate.exists() and "DATA_BLOCK" in candidate.read_text(encoding="utf-8-sig"):
                db = load_data_block(candidate)
                self[key] = db
                return db
        raise KeyError(key)


#: Width in bits of each SCL slice selector: ``%X0`` a bit, ``%B1`` a byte,
#: ``%W2`` a word, ``%D0`` a double word.
SLICE_WIDTHS: dict[str, int] = {"X": 1, "B": 8, "W": 16, "D": 32}


def _slice_base(value: Any) -> int:
    """The integer a slice is taken of; a Real has no bit slices in SCL."""
    if isinstance(value, float):
        raise TypeError(f"bit/byte slice of a Real value ({value!r}); SCL slices integers only")
    return int(value)


def _bit_slice(value: Any, width: int, index: int) -> Any:
    """``value.%Xn`` / ``%Bn`` / ``%Wn`` / ``%Dn``: the slice read as an integer (a bit as bool).

    A negative base reads as its two's-complement bits (``-1 .%X15`` is True).
    """
    bits = (_slice_base(value) >> (index * width)) & ((1 << width) - 1)
    return bool(bits) if width == 1 else bits


def _with_bit_slice(value: Any, width: int, index: int, new: Any) -> int:
    """``value`` with its slice ``n`` of ``width`` bits replaced by ``new``.

    The result is an unbounded Python int: the base's declared width is not known
    here, so setting the sign bit of an ``Int`` gives ``32768``, not ``-32768``.
    Out of contract for signed bases; the corpus writes slices of ``Byte``/``Word``.
    """
    mask = ((1 << width) - 1) << (index * width)
    return (_slice_base(value) & ~mask) | ((int(new) << (index * width)) & mask)


#: Line-coverage registry, alive when ``PLC_SCL_COVERAGE`` names a file: which SCL
#: lines each block declares as executable, and which a run actually touched.
#: Written (merged with the file's previous content) at interpreter exit, so the
#: pytest subprocesses ``plc code test --coverage`` spawns each add their share.
_COVERAGE_EXECUTABLE: dict[str, set[int]] = {}
_COVERAGE_TOUCHED: dict[str, set[int]] = {}
_COVERAGE_HOOKED = False


def coverage_path() -> Path | None:
    """The coverage file ``PLC_SCL_COVERAGE`` names, or ``None`` when coverage is off."""
    value = os.environ.get("PLC_SCL_COVERAGE")
    return Path(value) if value else None


def record_executable(block: str, lines: list[int]) -> None:
    """Register a block's executable SCL lines and arm the exit-time dump."""
    global _COVERAGE_HOOKED
    _COVERAGE_EXECUTABLE.setdefault(block, set()).update(lines)
    if not _COVERAGE_HOOKED:
        _COVERAGE_HOOKED = True
        atexit.register(_dump_coverage)


def _dump_coverage() -> None:
    path = coverage_path()
    if path is None:
        return
    merged: dict[str, dict[str, list[int]]] = {}
    try:
        merged = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        merged = {}
    for block, lines in _COVERAGE_EXECUTABLE.items():
        entry = merged.setdefault(block, {"executable": [], "touched": []})
        entry["executable"] = sorted(set(entry.get("executable", [])) | lines)
    for block, lines in _COVERAGE_TOUCHED.items():
        entry = merged.setdefault(block, {"executable": [], "touched": []})
        entry["touched"] = sorted(set(entry.get("touched", [])) | lines)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(merged, indent=0, sort_keys=True), encoding="utf-8")
    except OSError:
        pass  # coverage must never fail the run it measures


class UnsetTag:
    """What a PLC tag reads as before anything set it.

    False in a condition and ``0`` in arithmetic and ordering (``<``, ``<=``,
    ``>``, ``>=`` behave as ``0`` would), as an unforced input is; but ``=``
    holds only between the same tag by name, never against ``0``/``FALSE``, so two
    tag-table *constants* (``"MODE_ONE"``, ``"MODE_TWO"``) compared or used as
    ``CASE`` labels stay distinct without a tag table being loaded. That one
    deliberate disagreement (``tag <= 0`` and ``tag >= 0`` but not ``tag = 0``)
    is the price of the labels; set the tag and it disappears. Division by an
    unset tag raises, as on the PLC.
    """

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"UnsetTag({self.name!r})"

    def __bool__(self) -> bool:
        return False

    def __eq__(self, other: object) -> bool:
        # Equal to the same tag only: a CASE label that is an unset constant must
        # not match a selector holding 0 or another unset constant.
        return isinstance(other, UnsetTag) and self.name == other.name

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash(("UnsetTag", self.name))

    def __int__(self) -> int:
        return 0

    __index__ = __int__

    def __float__(self) -> float:
        return 0.0

    def _as_number(self, other: Any) -> Any:
        return 0.0 if isinstance(other, float) else 0

    def __lt__(self, other: Any) -> bool:
        return bool(self._as_number(other) < other)

    def __le__(self, other: Any) -> bool:
        return bool(self._as_number(other) <= other)

    def __gt__(self, other: Any) -> bool:
        return bool(self._as_number(other) > other)

    def __ge__(self, other: Any) -> bool:
        return bool(self._as_number(other) >= other)

    def __add__(self, other: Any) -> Any:
        return self._as_number(other) + other

    __radd__ = __add__

    def __sub__(self, other: Any) -> Any:
        return self._as_number(other) - other

    def __rsub__(self, other: Any) -> Any:
        return other - self._as_number(other)

    def __mul__(self, other: Any) -> Any:
        return self._as_number(other) * other

    __rmul__ = __mul__

    def __truediv__(self, other: Any) -> Any:
        return self._as_number(other) / other

    def __rtruediv__(self, other: Any) -> Any:
        raise ZeroDivisionError(f"division by the unset tag {self.name!r}")

    def __floordiv__(self, other: Any) -> Any:
        return self._as_number(other) // other

    def __rfloordiv__(self, other: Any) -> Any:
        raise ZeroDivisionError(f"division by the unset tag {self.name!r}")

    def __mod__(self, other: Any) -> Any:
        return self._as_number(other) % other

    def __rmod__(self, other: Any) -> Any:
        raise ZeroDivisionError(f"modulo by the unset tag {self.name!r}")

    def __pow__(self, other: Any) -> Any:
        return 0**other

    def __rpow__(self, other: Any) -> Any:
        return other**0

    def __neg__(self) -> int:
        return 0

    __pos__ = __neg__
    __abs__ = __neg__

    def __invert__(self) -> int:
        return ~0

    def __round__(self, ndigits: int | None = None) -> int:
        return 0

    def __format__(self, spec: str) -> str:
        return format(0, spec)

    def __and__(self, other: Any) -> Any:
        return other & 0

    __rand__ = __and__

    def __or__(self, other: Any) -> Any:
        return other | 0

    __ror__ = __or__

    def __xor__(self, other: Any) -> Any:
        return other ^ 0

    __rxor__ = __xor__

    def __lshift__(self, other: Any) -> int:
        return 0

    __rshift__ = __lshift__

    def __rlshift__(self, other: Any) -> Any:
        return other << 0

    def __rrshift__(self, other: Any) -> Any:
        return other >> 0


class _Tags(dict):
    """The PLC tag table: ``"DI_START"``, ``"DO_PUMP"`` read and written by name.

    A tag never set reads as an :class:`UnsetTag` (false, ``0``, equal to itself
    by name). A bare quoted name that is a registered or loadable global data
    block (``"MyDB"`` passed whole to a block) resolves to that block instead, so
    the one rendering ``self._runtime.tags["name"]`` serves both.
    """

    def __init__(self, runtime: "PLCRuntime") -> None:
        super().__init__()
        self._runtime = runtime

    def __missing__(self, key: str) -> Any:
        try:
            return self._runtime.global_dbs[key]
        except (KeyError, OSError, UnicodeDecodeError):
            unset = UnsetTag(key)
            self[key] = unset  # remembered: one search-path walk per name, not per read
            return unset

    def __setitem__(self, key: str, value: Any) -> None:
        if key in self._runtime.global_dbs:
            raise KeyError(f"{key!r} is a global data block; write its members, not the name")
        super().__setitem__(key, value)

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        """``tags.get(name)`` resolves like ``tags[name]``; ``default`` is never needed."""
        return self[key]


class _AutoStruct:
    """Auto-vivifying struct for UDT (User Defined Type) simulation.

    Supports both attribute access (``obj.field``) and integer/string
    index access (``obj[1]``, ``obj["key"]``). Unset attributes and
    index slots are created on first access so that deeply-nested
    write patterns like::

        self.mdhParams.jointParams[1].alpha = 0.0

    work without pre-declaring the full structure.

    Instances can be converted to plain dicts with :meth:`to_dict` so
    that test code can do ``p["jointParams"][1]["alpha"]``.
    """

    __slots__ = ("_attrs", "_items")

    def __init__(self) -> None:
        object.__setattr__(self, "_attrs", {})
        object.__setattr__(self, "_items", {})

    # --- attribute protocol ---

    def __getattr__(self, name: str) -> Any:
        attrs = object.__getattribute__(self, "_attrs")
        if name not in attrs:
            attrs[name] = _AutoStruct()
        return attrs[name]

    def __setattr__(self, name: str, value: Any) -> None:
        attrs = object.__getattribute__(self, "_attrs")
        attrs[name] = value

    # --- item protocol (list / dict indices) ---

    def __getitem__(self, idx: Any) -> Any:
        items = object.__getattribute__(self, "_items")
        if idx not in items:
            items[idx] = _AutoStruct()
        return items[idx]

    def __setitem__(self, idx: Any, value: Any) -> None:
        items = object.__getattribute__(self, "_items")
        items[idx] = value

    # --- dict / list conversion ---

    def to_dict(self) -> dict:
        """Recursively convert this struct to a plain Python dict.

        Attribute fields become string-keyed dict entries.
        Index slots become integer/string-keyed dict entries stored
        under the same level (merged with attribute entries).
        """
        attrs = object.__getattribute__(self, "_attrs")
        items = object.__getattribute__(self, "_items")

        result: dict = {}

        # Values may themselves be plain Python lists holding _AutoStruct
        # elements (e.g. a VAR_IN_OUT array-of-UDT member such as
        # ``buffer.records : ARRAY[..] of typeSoeRecord`` whose slots get
        # replaced with _AutoStruct instances the first time SCL code writes
        # a field into one of them). Recurse through _auto_struct_to_dict so
        # those elements are converted too, not just direct _AutoStruct
        # attribute values.
        for k, v in attrs.items():
            result[k] = _auto_struct_to_dict(v)

        # If there are indexed items, merge them in as their own dict
        # (they come from patterns like  obj.someList[1].field)
        # We expose them under their key directly so that
        #   p["jointParams"][1]["alpha"]  works when jointParams is
        #   an _AutoStruct used as a list.
        if items:
            converted_items: dict = {}
            for k, v in items.items():
                converted_items[k] = _auto_struct_to_dict(v)
            # If there are ONLY items (no attrs), return the items dict directly
            if not result:
                return converted_items
            # If there are both, the caller used the struct as *both* a
            # container and a record — store items under a special key.
            # In practice this shouldn't happen for normal PLC patterns.
            result.update(converted_items)

        return result

    def clone(self) -> "_AutoStruct":
        """Return a deep copy of this struct.

        Used to honour S7 ``VAR_INPUT`` copy-in semantics when a UDT is passed
        into a (nested) FB call: the callee receives its own copy so that a
        later mutation of the caller's struct is not aliased into the callee's
        retained state (e.g. an internal ``prevInput := input`` snapshot).
        """
        attrs = object.__getattribute__(self, "_attrs")
        items = object.__getattribute__(self, "_items")
        new = _AutoStruct()
        new_attrs = object.__getattribute__(new, "_attrs")
        new_items = object.__getattribute__(new, "_items")
        for k, v in attrs.items():
            new_attrs[k] = _clone_value(v)
        for k, v in items.items():
            new_items[k] = _clone_value(v)
        return new

    def __repr__(self) -> str:
        return f"_AutoStruct({self.to_dict()!r})"


def _clone_value(value: Any) -> Any:
    """Deep-copy *_AutoStruct* / list containers; return scalars unchanged."""
    if isinstance(value, _AutoStruct):
        return value.clone()
    if isinstance(value, list):
        return [_clone_value(v) for v in value]
    return value


def _dict_to_auto_struct(value: Any) -> Any:
    """Recursively convert a dict (or list of dicts) to *_AutoStruct* objects.

    String keys become attributes (accessible via ``obj.name``).
    Integer keys become items (accessible via ``obj[n]``) so that
    array-like dicts such as ``{0: 0.0, 1: 1.0}`` work with ``obj[0]``.
    Scalars and non-dict values are returned unchanged.
    """
    if isinstance(value, dict):
        s = _AutoStruct()
        for k, v in value.items():
            converted = _dict_to_auto_struct(v)
            if isinstance(k, int):
                object.__getattribute__(s, "_items")[k] = converted
            else:
                object.__getattribute__(s, "_attrs")[k] = converted
        return s
    if isinstance(value, list):
        return [_dict_to_auto_struct(item) for item in value]
    return value


def _auto_struct_to_dict(value: Any) -> Any:
    """Recursively convert *_AutoStruct* objects back to plain Python dicts/lists."""
    if isinstance(value, _AutoStruct):
        return value.to_dict()
    if isinstance(value, list):
        return [_auto_struct_to_dict(item) for item in value]
    return value


@dataclass
class MockClock:
    """Controllable clock for test environments.

    This clock allows tests to control the passage of time, enabling
    deterministic testing of timer-dependent logic.

    Attributes
    ----------
    _current_time : float
        Current simulation time in seconds.
    """

    _current_time: float = 0.0

    def get_time(self) -> float:
        """Get the current simulation time.

        Returns
        -------
        float
            Current time in seconds.
        """
        return self._current_time

    def advance(self, seconds: float) -> None:
        """Advance the clock by a specified duration.

        Parameters
        ----------
        seconds : float
            Duration to advance in seconds.

        Raises
        ------
        ValueError
            If seconds is negative.
        """
        if seconds < 0:
            raise ValueError("Cannot advance clock by negative time")
        self._current_time += seconds

    def advance_ms(self, milliseconds: float) -> None:
        """Advance the clock by milliseconds.

        Parameters
        ----------
        milliseconds : float
            Duration to advance in milliseconds.
        """
        self.advance(milliseconds / 1000)

    def set_time(self, time: float) -> None:
        """Set the clock to a specific time.

        Parameters
        ----------
        time : float
            Time to set in seconds.

        Raises
        ------
        ValueError
            If time is negative.
        """
        if time < 0:
            raise ValueError("Cannot set clock to negative time")
        self._current_time = time

    def reset(self) -> None:
        """Reset the clock to zero."""
        self._current_time = 0.0


@dataclass
class PLCRuntime:
    """Simulates PLC cyclic execution behavior.

    This class provides the runtime environment for executing transpiled
    SCL function blocks, including:
    - A controllable clock for time simulation
    - Global data block registry
    - Function block instance registry
    - Cycle management

    Attributes
    ----------
    clock : MockClock
        The simulation clock.
    cycle_time : float
        Duration of one PLC cycle in seconds.
    cycle_count : int
        Number of cycles executed.
    tags : dict[str, Any]
        The PLC tag table, by tag name without quotes; an unset tag reads as
        ``False``. Generated code reaches a bare quoted name through it.
    global_dbs : dict[str, Any]
        Registry of global data blocks.
    fb_instances : dict[str, Any]
        Registry of function block instances.
    """

    clock: MockClock = field(default_factory=MockClock)
    cycle_time: float = 0.010  # 10ms default
    cycle_count: int = 0
    global_dbs: dict[str, Any] = field(default_factory=dict)
    tags: dict[str, Any] = field(default_factory=dict)
    #: What the simulated clock's zero stands for when a block reads the system time.
    epoch: datetime = field(default=datetime(2026, 1, 1, tzinfo=UTC), repr=False)
    #: The last 10 000 system instructions the blocks asked for (name, inputs, outputs).
    system_call_log: deque[tuple[str, dict[str, Any], list[str]]] = field(
        default_factory=lambda: deque(maxlen=10_000), repr=False
    )
    #: What a stubbed system instruction returns as ``RET_VAL``: ``0`` (no error) by
    #: default, so a block's nominal path runs; set ``16#8080`` to exercise its
    #: error handling instead. Every stub is logged either way.
    system_stub_status: int = 0
    _runtime_last_call: float | None = field(default=None, repr=False)
    fb_instances: dict[str, Any] = field(default_factory=dict)
    block_search_paths: list[Path] = field(default_factory=list)
    _named_block_cache: dict[str, Any] = field(default_factory=dict, repr=False)
    _block_kind_cache: dict[str, BlockType | None] = field(default_factory=dict, repr=False)
    _block_signature_cache: dict[str, list[str] | None] = field(default_factory=dict, repr=False)
    _block_file_index: dict[Path, dict[str, Path]] = field(default_factory=dict, repr=False)
    _fb_instantiating: set[str] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        """Wrap ``global_dbs`` so missing constant DBs auto-load from search paths."""
        if not isinstance(self.global_dbs, _GlobalDBs):
            wrapped = _GlobalDBs(self)
            wrapped.update(self.global_dbs)
            self.global_dbs = wrapped
        if not isinstance(self.tags, _Tags):
            tag_table = _Tags(self)
            tag_table.update(self.tags)
            self.tags = tag_table

    def register_db(self, name: str, data: Any) -> None:
        """Register a global data block.

        Parameters
        ----------
        name : str
            The data block name (without quotes, e.g., "ProcessData").
        data : Any
            The data block object (typically a dataclass instance).
        """
        self.global_dbs[name] = data

    def get_db(self, name: str) -> Any:
        """Get a registered data block.

        Parameters
        ----------
        name : str
            The data block name.

        Returns
        -------
        Any
            The data block object.

        Raises
        ------
        KeyError
            If the data block is not registered.
        """
        if name not in self.global_dbs:
            raise KeyError(f"Data block '{name}' not registered in runtime")
        return self.global_dbs[name]

    def register_fb(self, name: str, instance: Any) -> None:
        """Register a function block instance.

        Parameters
        ----------
        name : str
            The instance name.
        instance : Any
            The function block instance.
        """
        self.fb_instances[name] = instance

    def get_fb(self, name: str) -> Any:
        """Get a registered function block instance.

        Parameters
        ----------
        name : str
            The instance name.

        Returns
        -------
        Any
            The function block instance.

        Raises
        ------
        KeyError
            If the instance is not registered.
        """
        if name not in self.fb_instances:
            raise KeyError(f"Function block instance '{name}' not registered")
        return self.fb_instances[name]

    def _compile_named_fb_class(self, block_name: str) -> Any:
        """Resolve, compile (or fetch cached), and return an FB class by name.

        Compiles the named block with an FB-type resolver bound to this runtime,
        so that the compiled class supports nested FB members itself.  The result
        is cached in :attr:`_named_block_cache`.

        Parameters
        ----------
        block_name : str
            The SCL block name without quotes.

        Returns
        -------
        Any
            The compiled function block class.

        Raises
        ------
        FileNotFoundError
            If the block SCL file cannot be found in any search path.
        ValueError
            If block compilation fails.
        """
        # Lazy-import to avoid circular dependency (runtime <- transpiler <- runtime)
        from plc_code.executor.transpiler import compile_block  # noqa: PLC0415
        from plc_code.parser import parse_scl_file  # noqa: PLC0415

        if block_name not in self._named_block_cache:
            block_path = self._find_block_file(block_name)
            if block_path is None:
                search_dirs_str = ", ".join(str(p) for p in self.block_search_paths)
                raise FileNotFoundError(
                    f"Sub-block '{block_name}.s7dcl' not found in search paths: [{search_dirs_str}]"
                )
            parsed = parse_scl_file(block_path)
            result = compile_block(
                parsed,
                fb_type_resolver=lambda n: self.block_kind(n) == "FUNCTION_BLOCK",
                signature_resolver=self.block_signature,
            )
            if not result.success:
                raise ValueError(f"Failed to compile sub-block '{block_name}': {result.compile_error}")
            self._named_block_cache[block_name] = result.fb_class

        return self._named_block_cache[block_name]

    def create_fb_instance(self, name: str, fb_class: type | None = None) -> Any:
        """Create and register a function block instance.

        Parameters
        ----------
        name : str
            The instance/block name.  When ``fb_class`` is omitted, ``name`` is
            treated as a block name and the FB class is resolved and compiled
            from the registered search paths (with nested-FB support).
        fb_class : type | None
            The function block class to instantiate.  When None, the class is
            resolved from ``name`` via :meth:`_compile_named_fb_class`.

        Returns
        -------
        Any
            The created function block instance, bound to this runtime.

        Raises
        ------
        ValueError
            If a circular FB nesting is detected (the same block name is
            requested while already being instantiated).
        """
        if fb_class is None:
            if name in self._fb_instantiating:
                chain = ", ".join(sorted(self._fb_instantiating))
                raise ValueError(
                    f"circular FB nesting: '{name}' is already being instantiated " f"(in-progress: {chain})"
                )
            self._fb_instantiating.add(name)
            try:
                resolved_class = self._compile_named_fb_class(name)
                instance = resolved_class(_runtime=self)
            finally:
                self._fb_instantiating.discard(name)
        else:
            instance = fb_class(_runtime=self)
        self.fb_instances[name] = instance
        return instance

    def _find_block_file(self, block_name: str) -> Path | None:
        """Search for an SCL file by block name in the registered search paths.

        Each search path is walked once, recursively, the first time it is needed
        and indexed by file name (``_block_file_index``); a project tree nests blocks
        by folder and a callee may sit several levels away from its caller. A file
        directly under the search path wins over a nested one of the same name, and
        the search paths are consulted in registration order.

        Parameters
        ----------
        block_name : str
            The block name (e.g. ``"MdhJointTransform"``).

        Returns
        -------
        Path | None
            The path to the first matching ``.s7dcl`` file, or ``None``.
        """
        filename = f"{block_name}.s7dcl"
        for search_dir in self.block_search_paths:
            index = self._block_file_index.get(search_dir)
            if index is None:
                index = {}
                if search_dir.is_dir():
                    for candidate in sorted(search_dir.rglob("*.s7dcl"), key=lambda c: len(c.parts)):
                        index.setdefault(candidate.name, candidate)
                self._block_file_index[search_dir] = index
            found = index.get(filename)
            if found is not None:
                return found
        return None

    def block_kind(self, name: str) -> BlockType | None:
        """Return the declared kind of a block by name, or ``None`` if unresolved.

        Resolves ``name`` via the registered search paths (same logic as
        :meth:`call_named_block`) and reports the block's declared kind
        (e.g. ``"FUNCTION_BLOCK"``, ``"FUNCTION"``, ``"TYPE"``,
        ``"DATA_BLOCK"``, ``"ORGANIZATION_BLOCK"``).  Results are cached.

        Parameters
        ----------
        name : str
            The block name without quotes (e.g. ``"MotionProfile"``).

        Returns
        -------
        BlockType | None
            The declared block kind, or ``None`` if the block cannot be
            found or parsed.
        """
        if name in self._block_kind_cache:
            return self._block_kind_cache[name]
        # Lazy-import to match call_named_block's import path.
        from plc_code.parser import parse_scl_file  # noqa: PLC0415

        path = self._find_block_file(name)
        kind: BlockType | None = None
        if path is not None:
            try:
                parsed = parse_scl_file(path)
                kind = parsed.block_type
            except Exception:
                kind = None
        self._block_kind_cache[name] = kind
        return kind

    def block_signature(self, name: str) -> list[str] | None:
        """Return the parameter names positional call arguments bind to, or ``None``.

        ``VAR_INPUT`` names in declaration order, followed by the ``VAR_IN_OUT`` names
        when the block declares no ``VAR_OUTPUT`` -- the only case where their
        positional order is beyond doubt. A block with outputs offers its inputs
        alone: how TIA orders outputs and in-outs among positional arguments is not
        something this code can verify, so a call reaching past the inputs is
        refused by the binder rather than guessed at. Resolved via the same search
        paths as :meth:`block_kind`; results are cached. Handed to the transpiler as
        its ``signature_resolver`` so ``"Block"(#a, #b)`` binds.

        Parameters
        ----------
        name : str
            The block name without quotes.

        Returns
        -------
        list[str] | None
            The names, possibly empty, or ``None`` if the block cannot be found or
            parsed.
        """
        if name in self._block_signature_cache:
            return self._block_signature_cache[name]
        from plc_code.parser import parse_scl_file  # noqa: PLC0415

        path = self._find_block_file(name)
        signature: list[str] | None = None
        if path is not None:
            try:
                parsed = parse_scl_file(path)
                sections = parsed.variable_sections
                offered: tuple[str, ...] = ("VAR_INPUT", "VAR_IN_OUT")
                if any(section.section_type == "VAR_OUTPUT" for section in sections):
                    offered = ("VAR_INPUT",)
                signature = [
                    variable.name
                    for section_type in offered
                    for section in sections
                    if section.section_type == section_type
                    for variable in section.variables
                ]
            except Exception:
                signature = None
        self._block_signature_cache[name] = signature
        return signature

    def call_named_block(
        self,
        block_name: str,
        inputs: dict[str, Any],
        in_outs: dict[str, Any],
    ) -> dict[str, Any]:
        """Compile (or retrieve cached), execute, and return outputs of a named sub-block.

        This method implements the ``"BlockName"(param := val, out => var)`` SCL pattern.
        It discovers the block file by name, compiles it on first use, runs it with
        the provided inputs and in-out values, then returns a dict of all outputs
        and updated in-out values.

        Parameters
        ----------
        block_name : str
            The SCL block name without quotes (e.g. ``"MdhJointTransform"``).
        inputs : dict[str, Any]
            Input parameter name -> value mapping (from ``:=`` params).
        in_outs : dict[str, Any]
            In-out parameter name -> current value mapping (from ``:=`` params
            that target ``VAR_IN_OUT`` variables; these are also returned).

        Returns
        -------
        dict[str, Any]
            Mapping of output/in-out name -> value after execution.

        Raises
        ------
        FileNotFoundError
            If the block SCL file cannot be found in any search path.
        ValueError
            If block compilation fails.
        """
        fb_class = self._compile_named_fb_class(block_name)
        instance = fb_class(_runtime=self)

        # Bind by the parameter's Python identifier (`"Set Point"` is `Set_Point`);
        # results are keyed by the SCL name the caller used.
        for param_name, value in inputs.items():
            attribute = python_identifier(param_name)
            if hasattr(instance, attribute):
                setattr(instance, attribute, value)

        # Set in-out parameters (VAR_IN_OUT parameters - passed by value-in/value-out)
        for param_name, value in in_outs.items():
            attribute = python_identifier(param_name)
            if hasattr(instance, attribute):
                setattr(instance, attribute, value)

        instance.execute()

        # Collect all outputs and updated in-out values, under their SCL names
        result_dict: dict[str, Any] = {}
        scl_names = getattr(instance, "_scl_names", {})
        for name in instance._outputs:
            result_dict[scl_names.get(name, name)] = getattr(instance, name)
        for name in instance._in_outs:
            result_dict[scl_names.get(name, name)] = getattr(instance, name)

        # Capture the FUNCTION return value.  A ``FUNCTION "Name" : <type>`` block
        # returns its value through ``#Name := ...`` inside the body, which the
        # transpiler emits as ``self.Name``.  That attribute is not part of
        # _outputs/_in_outs, so expose it under the block name so an
        # expression-position caller (e.g. ``IF "Name"(...) THEN``) can read it.
        return_attribute = python_identifier(block_name)
        if block_name not in result_dict and hasattr(instance, return_attribute):
            result_dict[block_name] = getattr(instance, return_attribute)

        return result_dict

    def execute_cycle(self) -> None:
        """Execute one PLC cycle.

        This advances the clock by the cycle time and increments
        the cycle counter. It does not automatically execute any
        function blocks - that is left to the test harness.
        """
        self.clock.advance(self.cycle_time)
        self.cycle_count += 1

    @staticmethod
    def touch(block: str, line: int) -> None:
        """One executed SCL line, recorded for ``plc code test --coverage``."""
        _COVERAGE_TOUCHED.setdefault(block, set()).add(line)

    def system_time(self) -> datetime:
        """The system time ``RD_SYS_T`` reports: ``epoch`` plus the simulated clock."""
        return self.epoch + timedelta(seconds=self.clock.get_time())

    def rd_sys_t(self, out: Any) -> int:
        """``RD_SYS_T(OUT => #dtl)``: fill ``out``'s DTL fields from :meth:`system_time`; status 0.

        ``out`` is the struct the block declared (an ``_AutoStruct``); a plain
        ``dict`` is filled by key. Anything else is not a DTL and raises.
        """
        now = self.system_time()
        fields = {
            "YEAR": now.year,
            "MONTH": now.month,
            "DAY": now.day,
            "WEEKDAY": now.isoweekday() % 7 + 1,  # DTL: 1 = Sunday
            "HOUR": now.hour,
            "MINUTE": now.minute,
            "SECOND": now.second,
            "NANOSECOND": now.microsecond * 1000,
        }
        if isinstance(out, dict):
            out.update(fields)
        elif isinstance(out, _AutoStruct) or hasattr(out, "__dict__"):
            for name, value in fields.items():
                setattr(out, name, value)
        else:
            raise TypeError(f"RD_SYS_T's OUT must be a DTL struct, not {type(out).__name__}")
        return 0

    def runtime_measure(self) -> float:
        """``RUNTIME(#mem)``: seconds of simulated time since the previous call (0.0 the first)."""
        now = self.clock.get_time()
        elapsed = 0.0 if self._runtime_last_call is None else now - self._runtime_last_call
        self._runtime_last_call = now
        return elapsed

    def system_call(self, name: str, inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
        """A system instruction with ``=>`` outputs (``GET_DIAG``, ``RD_SYS_T``, ``Serialize``).

        ``RD_SYS_T`` is real: ``OUT`` is filled from :meth:`system_time`. Every other
        instruction is a stub -- there is no hardware behind the harness: each
        output keeps its current value when it is a struct or an array and becomes
        ``0`` when it is a scalar, ``RET_VAL`` is :attr:`system_stub_status`, and
        the call is appended to :attr:`system_call_log`.

        Parameters
        ----------
        name : str
            The instruction.
        inputs : dict[str, Any]
            Each ``:=`` parameter's value.
        outputs : dict[str, Any]
            Each ``=>`` parameter's *current* value, so a stub can hand back a
            struct or array untouched.

        Returns
        -------
        dict[str, Any]
            One entry per output, plus ``"RET_VAL"``.
        """
        self.system_call_log.append((name, dict(inputs), list(outputs)))
        result: dict[str, Any] = {}
        if name.upper() == "RD_SYS_T":
            for output, current in outputs.items():
                target = current if isinstance(current, _AutoStruct | dict) else _AutoStruct()
                self.rd_sys_t(target)
                result[output] = target
            result["RET_VAL"] = 0
            return result
        for output, current in outputs.items():
            result[output] = current if isinstance(current, list | dict | _AutoStruct) else 0
        result["RET_VAL"] = self.system_stub_status
        return result

    def system_value(self, name: str, *args: Any) -> int:
        """A system instruction called for its value alone (``LED(...)``,
        ``RH_GetPrimaryID()``): a logged stub returning :attr:`system_stub_status`."""
        self.system_call_log.append((name, {str(i): arg for i, arg in enumerate(args)}, []))
        return self.system_stub_status

    @staticmethod
    def dtl_to_ldt(dtl: Any) -> int:
        """``DTL_TO_LDT``: a DTL as LDT, nanoseconds since 1970-01-01 UTC."""

        def part(name: str, default: int) -> int:
            value = dtl.get(name) if isinstance(dtl, dict) else getattr(dtl, name, None)
            if value is None or isinstance(value, _AutoStruct):
                return default  # an _AutoStruct auto-vivifies an unset field
            if not isinstance(value, int | float):
                raise TypeError(f"DTL_TO_LDT: field {name} of {dtl!r} is not a number")
            return int(value)

        if not isinstance(dtl, dict | _AutoStruct) and not hasattr(dtl, "YEAR"):
            raise TypeError(f"DTL_TO_LDT expects a DTL struct, not {type(dtl).__name__}")

        moment = datetime(
            part("YEAR", 1970),
            part("MONTH", 1),
            part("DAY", 1),
            part("HOUR", 0),
            part("MINUTE", 0),
            part("SECOND", 0),
            tzinfo=UTC,
        )
        return int(moment.timestamp()) * 1_000_000_000 + part("NANOSECOND", 0)

    def reset(self) -> None:
        """Reset the runtime to initial state.

        This resets the clock, cycle count, and clears all
        registered data blocks, function block instances, and named block cache.
        """
        self.clock.reset()
        self.tags.clear()
        self.system_call_log.clear()
        self._runtime_last_call = None
        self.cycle_count = 0
        self.global_dbs.clear()
        self.fb_instances.clear()
        self._named_block_cache.clear()

    @property
    def current_time(self) -> float:
        """Get the current simulation time.

        Returns
        -------
        float
            Current time in seconds.
        """
        return self.clock.get_time()
