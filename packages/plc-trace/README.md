# plc-trace

Cycle-granular on-PLC trace recorder: an SCL scaffolding generator that turns
a flat UDT into a ring/one-shot sample buffer driven from the cyclic OB, plus
an OPC UA client (CLI + scenario steps) to control it and fetch recordings.

## 1. What and why

`plc sim monitor` and OPC UA subscriptions sample at the **OPC UA publishing
rate** (hundreds of ms, subject to network and server jitter) — fine for
watching a value drift, useless for verifying anything that happens within a
handful of PLC cycles (a control-loop transient, an edge-to-edge latency, a
jerk-limited ramp). `plc-trace` instead runs entirely **inside the PLC
cycle**: a generated FUNCTION block samples a set of signals into a ring (or
one-shot) buffer once per call, at the plant's own cycle time, with **no
network involved in the sampling path**. The buffer is then fetched over OPC
UA after the fact — the network only carries the retrieval, not the
acquisition.

Use it to capture a project-specific set of internal/output signals at full
cycle resolution for offline analysis (CSV) or to assert against inside an
EFAT scenario.

## 2. Quickstart

1. **Author a UDT** with only flat scalar fields — `Bool`, `Int`, `DInt`,
   `UDInt`, `Real`, `LReal` (see [§7](#7-v1-limits) for why). Example
   (`typeDemoTrace.s7dcl`):

   ```
   TYPE
       typeDemoTrace : STRUCT
           posX : Real;
           speedY : LReal;
           counter : DInt;
           flag : Bool;
       END_STRUCT;
   END_TYPE
   ```

2. **Scaffold the trace blocks:**

   ```bash
   plc trace scaffold --udt path/to/typeDemoTrace.s7dcl --depth 6000 --name TraceData
   ```

   This writes three files next to the UDT (or under `--out DIR`):
   `typeTraceData.s7dcl` (the trace UDT), `TraceData.s7dcl` (the instance
   DB), `TraceDataRecorder.s7dcl` (the recorder FUNCTION). Import all three
   into TIA Portal.

3. **Complete the FILL SAMPLE region** in `TraceDataRecorder.s7dcl` — one
   placeholder assignment per source field, each marked
   `// TODO: assign your signal`:

   ```
   #trace.posX[#idx] := 0.0; // TODO: assign your signal
   ```

   Replace the placeholder right-hand side with the actual signal to record
   (e.g. `#trace.posX[#idx] := "InstQuayManagement".quayStatus.armPosition.x;`).
   Leave everything outside the FILL SAMPLE region untouched — it is
   generated, normative logic (see [§3](#3-normative-dbudt-contract)).

4. **Call the recorder once per plant cycle**, from the cyclic regulation OB
   (`#timeCycle` is the OB's cycle time in **seconds**):

   ```
   "TraceDataRecorder"(timeCycle := #timeCycle, trace := "TraceData");
   ```

5. **Expose the `TraceData` DB over OPC UA**: in TIA Portal, *Project tree →
   OPC UA communication → Server interfaces*, add a namespace node mapping
   to the `TraceData` DB (entire DB, Read/Write — the client both writes
   `control.*` and reads `status.*` plus the sample arrays). Download the
   OPC UA configuration to the device/PLCSIM instance.

6. **Wire it into `plc.yaml`** — add a `sim.trace:` block and list the DB
   under `sim.namespaces`:

   ```yaml
   sim:
     endpoint: opc.tcp://192.168.0.50:4840
     interface: Simulation
     namespaces:
       - TraceData
     trace:
       db_path: TraceData
       fetch_chunk: 500
       output_dir: .sim/traces
   ```

7. **Control it** — via the CLI:

   ```bash
   plc trace start --mode ring --decimation 1
   # ... exercise the plant ...
   plc trace stop
   plc trace fetch -o my-run.csv
   ```

   or from an EFAT scenario, with the `trace_start` / `trace_stop` /
   `trace_fetch` steps (see [§6](#6-client-api-cli-and-scenario-steps)).

## 3. Normative DB/UDT contract

`plc trace scaffold` generates the following `type<Name>` layout. This
layout is **normative**: golden tests in `packages/plc-trace/tests/`
freeze its exact text, and the OPC UA client in this package hard-codes
these field paths. Do not hand-edit the `control`/`status`/`sampleCycles`
structure or the field names.

```
TYPE
    type<Name> : STRUCT
        control : STRUCT
            start : Bool;        // rising edge = start (resets indices); low level = stop
            mode : Int;          // 0 = ring (default), 1 = one-shot
            decimation : UDInt;  // sample every k-th cycle; 0/1 = every cycle; writable mid-run
        END_STRUCT;
        status : STRUCT
            recording : Bool;
            wrapped : Bool;
            writeIdx : DInt;
            sampleCount : DInt;
            cycleCounter : UDInt;
            cycleTimeMs : Real;
            depth : DInt;
            startMem : Bool;     // internal FC edge memory
            decCounter : UDInt;  // internal decimation countdown
        END_STRUCT;
        sampleCycles : Array[0..depth-1] of UDInt;
        <field1> : Array[0..depth-1] of <type1>;
        <field2> : Array[0..depth-1] of <type2>;
        ...                      // one Array[0..depth-1] per source-UDT field, declaration order
    END_STRUCT;
END_TYPE
```

### `control` (client-writable)

| Field | Type | Semantics |
|---|---|---|
| `start` | `Bool` | Rising edge arms the recorder: resets `writeIdx`, `sampleCount`, `cycleCounter`, `decCounter`, latches `cycleTimeMs := timeCycle * 1000.0`, sets `recording := TRUE`. Any low level (`FALSE`) stops recording (`recording := FALSE`); a fresh rising edge re-arms it (this is how one-shot mode "re-arms on next start edge"). |
| `mode` | `Int` | `0` = **ring** (default): wraps at `depth`, keeps the newest `depth` samples, sets `wrapped := TRUE` on first wrap. `1` = **one-shot**: recording stops automatically (`recording := FALSE`) once `writeIdx` reaches `depth`; does not wrap. The FC does not clear `control.start` on auto-stop, so to re-arm, the client must lower `start` (release) and raise it again — a fresh rising edge. |
| `decimation` | `UDInt` | Sample every k-th cycle; `0` or `1` both mean "every cycle". Writable mid-run: the FC reloads its internal down-counter (`decCounter`) from `control.decimation` each time a sample is taken, so a change takes effect at the **next decimation-counter reload**, not immediately. |

### `status` (client-readable; `startMem`/`decCounter` are internal — client-ignored)

| Field | Type | Semantics |
|---|---|---|
| `recording` | `Bool` | Whether the recorder is currently sampling. |
| `wrapped` | `Bool` | Whether the ring has wrapped at least once (ring mode only; stays `FALSE` in one-shot). |
| `writeIdx` | `DInt` | Next index to be written. |
| `sampleCount` | `DInt` | Total samples recorded since the last start (does not exceed `depth`). |
| `cycleCounter` | `UDInt` | Plant cycle counter since the last start; increments every cycle while `recording` is `TRUE`, independent of decimation. |
| `cycleTimeMs` | `Real` | Plant cycle time captured at start (`timeCycle * 1000.0`), in milliseconds. |
| `depth` | `DInt` | Ring depth, fixed at scaffold time (written as the DB's initial value). |
| `startMem` | `Bool` | **Internal, client-ignored.** FC edge-detection memory for `control.start`. |
| `decCounter` | `UDInt` | **Internal, client-ignored.** Internal decimation countdown. |

### Sample arrays

- `sampleCycles : Array[0..depth-1] of UDInt` — the `cycleCounter` value
  captured at the moment each sample was taken.
- One `Array[0..depth-1] of <field type>` per source-UDT field, in the
  source UDT's declaration order, named identically to the source field.

## 4. Timestamps

Each sample carries a **cycle counter**, not a wall-clock timestamp — the
recorder FC has no access to a wall clock. The client derives two kinds of
time from it:

- **Relative:** `t_rel_s = sample_cycles × cycle_time_ms / 1000` — the
  sample's time in seconds, computed from the recorded cycle number and the
  plant cycle time captured at start.
- **Absolute anchor:** the **client's own wall clock**, captured the moment
  `TraceClient.start()` observes `status.recording` flip to `True`
  (`meta["started_at_iso"]`). A sample's approximate wall-clock time is
  `started_at_iso + t_rel_s`.

The anchor is deliberately a client-side timestamp, not a PLC-side one:
there is no `RD_SYS_T`-equivalent read wired into this harness (not
harness-executable), and PLCSIM Advanced runs on **virtual time**, so the
PLC's own clock is not a reliable proxy for wall-clock time during
simulation. Cycle-counter-based relative timing is unaffected by either
limitation, since it only depends on the plant's own cycle time.

## 5. Sizing

Per-field arrays plus the `sampleCycles` array (`UDInt`, 4 bytes/sample)
dominate the DB footprint; `control`/`status` are fixed-size and negligible.
Approximate footprint:

```
bytes ≈ depth × (4 + Σ field sizes)
```

where `4` is `sampleCycles`'s per-sample cost and `Σ field sizes` sums the
per-sample byte size of each source-UDT field (typical S7-1500 sizes:
`Bool` 1, `Int` 2, `DInt`/`UDInt` 4, `Real` 4, `LReal` 8 — treat as a
planning estimate; actual packing can vary with block optimization).

**Example:** 15 `Real` fields (4 bytes each), `depth = 6000`:

```
6000 × (4 + 15 × 4) = 6000 × 64 = 384,000 bytes ≈ 384 KB
```

Pick `depth` accordingly — a DB sized to hold minutes of data at a fast
cycle time can run into the megabytes.

## 6. Client API, CLI, and scenario steps

### Client API (`plc_trace.client`)

- `TraceConfig(db_path="TraceData", fetch_chunk=500, output_dir=".sim/traces")`
  — `load_trace_config()` loads it (plus the raw `sim` dict) from `plc.yaml`.
- `TraceClient(client, resolve, config, fields=None)` — wraps a connected
  `OpcUaClient`:
  - `await start(mode="ring", decimation=1, timeout_s=5.0)` — arms the
    recorder, waits for `status.recording` to become `True`.
  - `await stop(timeout_s=5.0) -> TraceStatus` — clears `control.start`,
    waits for `status.recording` to become `False`, returns the final status.
  - `await set_decimation(k)` — updates `control.decimation` mid-run.
  - `await status() -> TraceStatus` — snapshot of the public `status.*`
    fields (`recording`, `wrapped`, `write_idx`, `sample_count`,
    `cycle_counter`, `cycle_time_ms`, `depth`).
  - `await fetch() -> TraceRecording` — reads the buffer (chunked via
    `IndexRange`, `fetch_chunk` elements at a time), reorders it
    oldest-first (unwrapping the ring if `wrapped`), and computes `t_rel_s`.
    Raises `RuntimeError` if the buffer is empty (`sampleCount == 0`).
- `TraceRecording.save(path)` — writes a CSV (`t_rel_s, sample_cycles,
  <field1>, <field2>, ...`) plus a `<path>.meta.json` sidecar (`db_path`,
  `mode`, `decimation`, `wrapped`, `sample_count`, `depth`, `cycle_time_ms`,
  `started_at_iso`, `fetched_at_iso`).

`TraceClient` needs the source UDT's field names (in declaration order) to
know which arrays to fetch; production wiring (`browse_trace_fields`)
discovers them once from the tag cache instead of requiring them to be
hard-coded.

### CLI (`plc trace ...`)

| Command | Options | Notes |
|---|---|---|
| `plc trace scaffold` | `--udt FILE` (required), `--depth INT` (required), `--name TEXT` (default `TraceData`), `--out DIR`, `--force` | Generates the three SCL sources; see [§2](#2-quickstart). |
| `plc trace status` | `-e/--endpoint TEXT` | Prints the current `status.*` fields. |
| `plc trace start` | `--mode [ring\|oneshot]` (default `ring`), `--decimation INT` (default `1`), `-e/--endpoint TEXT` | Arms the recorder and waits for it to start. |
| `plc trace stop` | `-e/--endpoint TEXT` | Stops the recorder, prints final `sample_count`/`wrapped`. |
| `plc trace fetch` | `-o/--output PATH` (default `<output_dir>/trace_<timestamp>.csv`), `-e/--endpoint TEXT` | Fetches and saves the recording (CSV + `.meta.json`). |

All runtime commands (`status`/`start`/`stop`/`fetch`) load `sim.trace` and
the rest of `sim.*` from `plc.yaml`; `-e/--endpoint` overrides the
configured endpoint for a one-off connection.

### Scenario steps (`plc sim test`)

Registered when `plc-trace` is installed alongside `plc-sim` (soft wiring —
absent otherwise). One `TraceClient` instance is shared across all
`trace_*` steps within a scenario run, so `trace_fetch`'s metadata can
reference the `started_at_iso` captured by an earlier `trace_start`.

| Step | Fields | Notes |
|---|---|---|
| `trace_start` | `mode` (default `ring`), `decimation` (default `1`) | Arms the recorder; fails the step on timeout/connection error. |
| `trace_stop` | — | Stops the recorder; reports `sample_count`, `wrapped`, `recording`. |
| `trace_fetch` | `output` (default `""`) | Fetches and saves as CSV. Default filename: explicit `output` if set; else `<output_dir>/<scenario-name>.csv`; else (scenario name unavailable) `<output_dir>/trace_<YYYYmmdd_HHMMSS>.csv`. |

Example — `plc.yaml` plus a scenario snippet:

```yaml
sim:
  endpoint: opc.tcp://192.168.0.50:4840
  interface: Simulation
  namespaces:
    - TraceData
  trace:
    db_path: TraceData
    fetch_chunk: 500
    output_dir: .sim/traces
```

```yaml
scenario:
  name: "Capture a jog transient"
  steps:
    - step: trace_start
      mode: ring
      decimation: 1
    - step: write
      values:
        TestInterface.simUserInput.angularSpeedSetpoints.[0]: 0.5
    - step: wait
      duration: 2s
    - step: trace_stop
    - step: trace_fetch
      output: jog-transient.csv
```

## 7. v1 limits

- **Scalar fields only.** Source UDT fields must be `Bool`, `Int`, `DInt`,
  `UDInt`, `Real`, or `LReal`; nested UDTs, arrays, and strings are
  rejected at scaffold time (`ScaffoldError`) — flatten your UDT first.
- **One buffer per config/DB.** `TraceConfig`/`TraceClient` address a
  single `db_path`; recording multiple independent buffers means running
  multiple configs (and, in a scenario, wiring separate clients).
- **Client/server reads only — no pub/sub.** `status()` and `fetch()` poll
  over OPC UA read/`IndexRange` calls; there is no subscription-based
  streaming of samples.
- **`IndexRange` behaviour is unverified against a real S7-1500 OPC UA
  server.** The test suite validates chunked/ring-aware fetch against
  asyncua's in-memory test server, which does not enforce the same
  `IndexRange` semantics a spec-compliant server would. Treat this as
  first validated at commissioning, against the real bench.
