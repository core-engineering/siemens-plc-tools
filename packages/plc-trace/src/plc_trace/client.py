"""OPC UA retrieval client for the on-PLC trace recorder.

Talks to a running trace instance (the ``control``/``status``/ring-array
layout produced by :mod:`plc_trace.scaffold`) over an existing
:class:`~plc_core.opcua.client.OpcUaClient` connection: start/stop/decimation
control, status polling, and a chunked, ring-aware fetch of the recorded
samples.
"""

from __future__ import annotations

import asyncio
import csv
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from plc_core.opcua.client import OpcUaClient

from plc_trace.config import TraceConfig

#: Poll interval while waiting for ``status.recording`` to flip, in seconds.
_POLL_INTERVAL_S = 0.05

#: ``control.mode`` values, per the contract UDT (see plc_trace.scaffold).
_MODE_VALUES: dict[str, int] = {"ring": 0, "oneshot": 1}
_MODE_NAMES: dict[int, str] = {v: k for k, v in _MODE_VALUES.items()}


@dataclass
class TraceStatus:
    """Snapshot of the trace instance's ``status`` struct (public fields only).

    Internal FC bookkeeping fields (``status.startMem``, ``status.decCounter``)
    are deliberately omitted.

    Attributes
    ----------
    recording : bool
        Whether the recorder is currently sampling.
    wrapped : bool
        Whether the ring has wrapped at least once (ring mode only).
    write_idx : int
        Next index to be written.
    sample_count : int
        Lifetime sample counter for the current recording. In ring mode it
        keeps counting past ``depth`` (buffer occupancy = ``min(sample_count,
        depth)``, or check ``wrapped``); in one-shot mode it stops at
        ``depth`` because recording auto-stops.
    cycle_counter : int
        Plant cycle counter since the last start.
    cycle_time_ms : float
        Plant cycle time captured at the last start, in milliseconds.
    depth : int
        Ring depth (fixed at scaffold time).
    """

    recording: bool
    wrapped: bool
    write_idx: int
    sample_count: int
    cycle_counter: int
    cycle_time_ms: float
    depth: int


@dataclass
class TraceRecording:
    """A fetched trace, reordered oldest-first and ready to save.

    Attributes
    ----------
    columns : dict[str, list[Any]]
        One entry per UDT field, in declaration order.
    sample_cycles : list[int]
        Plant cycle counter at each sample, oldest-first.
    t_rel_s : list[float]
        Time relative to the recording start edge (cycle 0), in seconds
        (``sample_cycles * cycle_time_ms / 1000``). In a wrapped fetch the
        first row's ``t_rel_s`` is not 0 — it reflects how far the oldest
        retained sample is from the start edge.
    meta : dict[str, Any]
        Run metadata: ``db_path``, ``mode``, ``decimation``, ``wrapped``,
        ``sample_count``, ``depth``, ``cycle_time_ms``, ``started_at_iso``,
        ``fetched_at_iso``.
    """

    columns: dict[str, list[Any]]
    sample_cycles: list[int]
    t_rel_s: list[float]
    meta: dict[str, Any] = field(default_factory=dict)

    def save(self, path: Path) -> None:
        """Write the recording as CSV plus a ``<path>.meta.json`` sidecar.

        Parameters
        ----------
        path : Path
            Destination CSV path. The metadata sidecar is written next to it
            as ``<path>.meta.json`` (the full CSV filename, suffix appended).
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        field_names = list(self.columns.keys())

        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["t_rel_s", "sample_cycles", *field_names])
            for i in range(len(self.sample_cycles)):
                row = [self.t_rel_s[i], self.sample_cycles[i]]
                row.extend(self.columns[name][i] for name in field_names)
                writer.writerow(row)

        meta_path = path.with_name(path.name + ".meta.json")
        meta_path.write_text(json.dumps(self.meta, indent=2), encoding="utf-8")


class TraceClient:
    """Protocol layer over a running trace instance.

    Parameters
    ----------
    client : OpcUaClient
        Connected OPC UA client.
    resolve : Callable[[str], str]
        Maps a tag path (e.g. ``"TraceData.control.start"``) to a NodeId
        string. Production: ``lambda p: tag_resolver.resolve(p).node_id``.
    config : TraceConfig
        Trace module configuration (``db_path``, ``fetch_chunk``, ...).
    fields : list[str] | None
        UDT field names, in declaration order (everything under the DB
        besides ``control``, ``status``, ``sampleCycles``). Required by
        :meth:`fetch`; production wiring browses it once from the tag cache.
    """

    def __init__(
        self,
        client: OpcUaClient,
        resolve: Callable[[str], str],
        config: TraceConfig,
        fields: list[str] | None = None,
    ) -> None:
        self._client = client
        self._resolve = resolve
        self._config = config
        self._db = config.db_path
        self._fields = fields
        self._started_at_iso: str | None = None

    async def start(self, mode: str = "ring", decimation: int = 1, timeout_s: float = 5.0) -> None:
        """Arm the recorder and wait for it to start sampling.

        Parameters
        ----------
        mode : str
            ``"ring"`` (wraps, default) or ``"oneshot"`` (stops at depth).
        decimation : int
            Sample every k-th cycle (1 = every cycle).
        timeout_s : float
            How long to wait for ``status.recording`` to become True.

        Raises
        ------
        ValueError
            If ``mode`` is not ``"ring"`` or ``"oneshot"``.
        TimeoutError
            If the recorder does not report ``recording`` within ``timeout_s``.
        """
        if mode not in _MODE_VALUES:
            raise ValueError(f"Unknown trace mode {mode!r}; expected 'ring' or 'oneshot'")

        await self._write(f"{self._db}.control.mode", _MODE_VALUES[mode])
        await self._write(f"{self._db}.control.decimation", decimation)
        await self._write(f"{self._db}.control.start", True)
        await self._wait_for(f"{self._db}.status.recording", expected=True, timeout_s=timeout_s)
        self._started_at_iso = datetime.now().astimezone().isoformat()

    async def stop(self, timeout_s: float = 5.0) -> TraceStatus:
        """Clear ``control.start`` and wait for the recorder to stop.

        Parameters
        ----------
        timeout_s : float
            How long to wait for ``status.recording`` to become False.

        Returns
        -------
        TraceStatus
            Status snapshot taken right after the recorder stopped.

        Raises
        ------
        TimeoutError
            If the recorder does not clear ``recording`` within ``timeout_s``.
        """
        await self._write(f"{self._db}.control.start", False)
        await self._wait_for(f"{self._db}.status.recording", expected=False, timeout_s=timeout_s)
        return await self.status()

    async def set_decimation(self, k: int) -> None:
        """Update the sampling decimation mid-run.

        Parameters
        ----------
        k : int
            Sample every k-th cycle (values below 1 are treated as 1 by the
            recorder FC).
        """
        await self._write(f"{self._db}.control.decimation", k)

    async def status(self) -> TraceStatus:
        """Read the current trace status.

        Returns
        -------
        TraceStatus
            Current status snapshot.
        """
        recording = await self._read(f"{self._db}.status.recording")
        wrapped = await self._read(f"{self._db}.status.wrapped")
        write_idx = await self._read(f"{self._db}.status.writeIdx")
        sample_count = await self._read(f"{self._db}.status.sampleCount")
        cycle_counter = await self._read(f"{self._db}.status.cycleCounter")
        cycle_time_ms = await self._read(f"{self._db}.status.cycleTimeMs")
        depth = await self._read(f"{self._db}.status.depth")
        return TraceStatus(
            recording=bool(recording),
            wrapped=bool(wrapped),
            write_idx=int(write_idx),
            sample_count=int(sample_count),
            cycle_counter=int(cycle_counter),
            cycle_time_ms=float(cycle_time_ms),
            depth=int(depth),
        )

    async def fetch(self) -> TraceRecording:
        """Fetch the recorded samples, reordered oldest-first.

        Returns
        -------
        TraceRecording
            The fetched samples plus run metadata.

        Raises
        ------
        RuntimeError
            If the trace buffer is empty (``sampleCount == 0``).
        """
        st = await self.status()
        if min(st.sample_count, st.depth) == 0:
            raise RuntimeError("Trace buffer is empty (sampleCount = 0)")

        if st.wrapped:
            span = st.depth
            order = list(range(st.write_idx, st.depth)) + list(range(0, st.write_idx))
        else:
            span = st.write_idx
            order = list(range(span))

        fields = self._field_names()
        cycles_raw = await self._read_full(f"{self._db}.sampleCycles", span)
        columns: dict[str, list[Any]] = {}
        for name in fields:
            raw = await self._read_full(f"{self._db}.{name}", span)
            columns[name] = [raw[i] for i in order]

        sample_cycles = [int(cycles_raw[i]) for i in order]
        dt_s = st.cycle_time_ms / 1000.0
        t_rel_s = [c * dt_s for c in sample_cycles]

        mode_raw = int(await self._read(f"{self._db}.control.mode"))
        decimation_raw = int(await self._read(f"{self._db}.control.decimation"))
        meta = {
            "db_path": self._db,
            "mode": _MODE_NAMES.get(mode_raw, mode_raw),
            "decimation": decimation_raw,
            "wrapped": st.wrapped,
            "sample_count": st.sample_count,
            "depth": st.depth,
            "cycle_time_ms": st.cycle_time_ms,
            "started_at_iso": self._started_at_iso,
            "fetched_at_iso": datetime.now().astimezone().isoformat(),
        }
        return TraceRecording(columns=columns, sample_cycles=sample_cycles, t_rel_s=t_rel_s, meta=meta)

    def _field_names(self) -> list[str]:
        if self._fields is None:
            raise RuntimeError(
                "TraceClient was constructed without 'fields'; pass the UDT field "
                "names (in declaration order) — production wiring browses them "
                "once from the tag cache."
            )
        return self._fields

    async def _read(self, path: str) -> Any:
        node_id = self._resolve(path)
        value = await self._client.read_value(node_id)
        return value.value

    async def _write(self, path: str, value: Any) -> None:
        node_id = self._resolve(path)
        await self._client.write_value(node_id, value)

    async def _read_full(self, path: str, count: int) -> list[Any]:
        if count <= 0:
            return []
        node_id = self._resolve(path)
        out: list[Any] = []
        step = max(1, self._config.fetch_chunk)
        for lo in range(0, count, step):
            hi = min(lo + step, count) - 1
            out.extend(await self._client.read_array_range(node_id, lo, hi))
        return out

    async def _wait_for(self, path: str, *, expected: bool, timeout_s: float) -> None:
        node_id = self._resolve(path)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while True:
            value = await self._client.read_value(node_id)
            if bool(value.value) == expected:
                return
            if loop.time() >= deadline:
                raise TimeoutError(f"Timed out after {timeout_s}s waiting for {path} == {expected}")
            await asyncio.sleep(_POLL_INTERVAL_S)
