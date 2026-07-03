"""Execute the generated recorder FC in the plc-code transpiler harness."""

from pathlib import Path

import pytest
from plc_code.executor import PLCRuntime, create_harness
from plc_trace.scaffold import generate_trace_blocks

FIXTURES = Path(__file__).parent / "fixtures"
DEPTH = 4


def _fresh_trace_state():
    return {
        "control": {"start": False, "mode": 0, "decimation": 1},
        "status": {
            "recording": False,
            "wrapped": False,
            "writeIdx": 0,
            "sampleCount": 0,
            "cycleCounter": 0,
            "cycleTimeMs": 0.0,
            "depth": DEPTH,
            "startMem": False,
            "decCounter": 0,
        },
        "sampleCycles": dict.fromkeys(range(DEPTH), 0),
        "posX": dict.fromkeys(range(DEPTH), 0.0),
        "speedY": dict.fromkeys(range(DEPTH), 0.0),
        "counter": dict.fromkeys(range(DEPTH), 0),
        "flag": dict.fromkeys(range(DEPTH), False),
    }


@pytest.fixture()
def harness(tmp_path: Path):
    blocks = generate_trace_blocks(FIXTURES / "typeDemoTrace.s7dcl", depth=DEPTH, name="TraceData")
    # Complete the FILL region deterministically: posX records the cycle counter
    # via a stand-in (timeCycle * 1000 stays constant, so use sampleCount).
    fc = blocks["fc"].replace(
        "#trace.posX[#idx] := 0.0; // TODO: assign your signal",
        "#trace.posX[#idx] := DINT_TO_REAL(#trace.status.sampleCount);",
    )
    (tmp_path / "typeTraceData.s7dcl").write_bytes(
        b"\xef\xbb\xbf" + blocks["type"].replace("\n", "\r\n").encode()
    )
    (tmp_path / "TraceDataRecorder.s7dcl").write_bytes(b"\xef\xbb\xbf" + fc.replace("\n", "\r\n").encode())
    runtime = PLCRuntime(block_search_paths=[tmp_path])
    h = create_harness(tmp_path / "TraceDataRecorder.s7dcl", runtime)
    h.set_inputs(timeCycle=0.005, trace=_fresh_trace_state())
    return h


def _cycles(h, n, **control):
    out = None
    for _ in range(n):
        if control:
            trace = h.get_outputs()["trace"]
            trace["control"].update(control)
            h.set_inputs(trace=trace)
            control = {}
        h.execute()
        out = h.get_outputs()["trace"]
    return out


def test_start_edge_resets_and_records(harness):
    t = _cycles(harness, 1)  # idle
    assert t["status"]["recording"] is False
    t = _cycles(harness, 3, start=True)  # start edge + 3 cycles
    assert t["status"]["recording"] is True
    assert t["status"]["sampleCount"] == 3
    assert [t["sampleCycles"][i] for i in range(3)] == [1, 2, 3]
    assert t["status"]["cycleTimeMs"] == pytest.approx(5.0)


def test_ring_wraps_and_keeps_counting(harness):
    t = _cycles(harness, 6, start=True)  # depth 4, 6 samples -> wrap
    assert t["status"]["wrapped"] is True
    assert t["status"]["writeIdx"] == 2
    assert t["status"]["sampleCount"] == 6
    # oldest surviving samples are cycles 3..6 laid out [5, 6, 3, 4]
    assert [t["sampleCycles"][i] for i in range(4)] == [5, 6, 3, 4]


def test_oneshot_stops_full_and_rearms_on_new_edge(harness):
    t = _cycles(harness, 6, start=True, mode=1)
    assert t["status"]["recording"] is False  # auto-stopped at depth
    assert t["status"]["sampleCount"] == 4
    assert t["status"]["wrapped"] is False
    t = _cycles(harness, 1, start=False)  # release
    t = _cycles(harness, 2, start=True)  # new edge -> re-armed
    assert t["status"]["recording"] is True
    assert t["status"]["sampleCount"] == 2


def test_decimation_and_midrun_change(harness):
    t = _cycles(harness, 6, start=True, decimation=3)  # samples at cycles 1, 4
    assert t["status"]["sampleCount"] == 2
    assert [t["sampleCycles"][i] for i in range(2)] == [1, 4]
    t = _cycles(harness, 2, decimation=1)  # next reload samples every cycle
    assert t["status"]["sampleCount"] == 4
    # cycle counter stays exact through the change
    assert t["sampleCycles"][2] == 7 and t["sampleCycles"][3] == 8


def test_stop_freezes_data(harness):
    t = _cycles(harness, 3, start=True)
    frozen = [t["sampleCycles"][i] for i in range(4)]
    t = _cycles(harness, 5, start=False)
    assert t["status"]["recording"] is False
    assert [t["sampleCycles"][i] for i in range(4)] == frozen
