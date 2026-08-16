"""PLC runtime simulation for SCL execution.

This module provides the runtime environment for executing transpiled
SCL code, including clock simulation and global data block management.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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
    global_dbs : dict[str, Any]
        Registry of global data blocks.
    fb_instances : dict[str, Any]
        Registry of function block instances.
    """

    clock: MockClock = field(default_factory=MockClock)
    cycle_time: float = 0.010  # 10ms default
    cycle_count: int = 0
    global_dbs: dict[str, Any] = field(default_factory=dict)
    fb_instances: dict[str, Any] = field(default_factory=dict)
    block_search_paths: list[Path] = field(default_factory=list)
    _named_block_cache: dict[str, Any] = field(default_factory=dict, repr=False)
    _block_kind_cache: dict[str, BlockType | None] = field(default_factory=dict, repr=False)
    _fb_instantiating: set[str] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        """Wrap ``global_dbs`` so missing constant DBs auto-load from search paths."""
        if not isinstance(self.global_dbs, _GlobalDBs):
            wrapped = _GlobalDBs(self)
            wrapped.update(self.global_dbs)
            self.global_dbs = wrapped

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
            candidate = search_dir / filename
            if candidate.exists():
                return candidate
            # Also search recursively one level deep
            for subdir in search_dir.iterdir() if search_dir.is_dir() else []:
                if subdir.is_dir():
                    candidate2 = subdir / filename
                    if candidate2.exists():
                        return candidate2
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

        # Set inputs (VAR_INPUT parameters)
        for param_name, value in inputs.items():
            if hasattr(instance, param_name):
                setattr(instance, param_name, value)

        # Set in-out parameters (VAR_IN_OUT parameters - passed by value-in/value-out)
        for param_name, value in in_outs.items():
            if hasattr(instance, param_name):
                setattr(instance, param_name, value)

        instance.execute()

        # Collect all outputs and updated in-out values
        result_dict: dict[str, Any] = {}
        for name in instance._outputs:
            result_dict[name] = getattr(instance, name)
        for name in instance._in_outs:
            result_dict[name] = getattr(instance, name)

        # Capture the FUNCTION return value.  A ``FUNCTION "Name" : <type>`` block
        # returns its value through ``#Name := ...`` inside the body, which the
        # transpiler emits as ``self.Name``.  That attribute is not part of
        # _outputs/_in_outs, so expose it under the block name so an
        # expression-position caller (e.g. ``IF "Name"(...) THEN``) can read it.
        if block_name not in result_dict and hasattr(instance, block_name):
            result_dict[block_name] = getattr(instance, block_name)

        return result_dict

    def execute_cycle(self) -> None:
        """Execute one PLC cycle.

        This advances the clock by the cycle time and increments
        the cycle counter. It does not automatically execute any
        function blocks - that is left to the test harness.
        """
        self.clock.advance(self.cycle_time)
        self.cycle_count += 1

    def reset(self) -> None:
        """Reset the runtime to initial state.

        This resets the clock, cycle count, and clears all
        registered data blocks, function block instances, and named block cache.
        """
        self.clock.reset()
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
