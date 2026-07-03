"""plc-trace configuration tests."""

from pathlib import Path

from plc_trace.config import TraceConfig, load_trace_config


def test_trace_config_defaults():
    cfg = TraceConfig.from_dict({})
    assert cfg.db_path == "TraceData"
    assert cfg.fetch_chunk == 500
    assert cfg.output_dir == ".sim/traces"


def test_trace_config_from_dict():
    cfg = TraceConfig.from_dict({"db_path": "MyTrace", "fetch_chunk": 100, "output_dir": "out"})
    assert (cfg.db_path, cfg.fetch_chunk, cfg.output_dir) == ("MyTrace", 100, "out")


def test_load_trace_config_reads_plc_yaml(tmp_path: Path):
    (tmp_path / "plc.yaml").write_text(
        "sim:\n"
        "  endpoint: opc.tcp://10.0.0.1:4840\n"
        "  interface: Simulation\n"
        "  namespaces: [TraceData]\n"
        "  trace:\n"
        "    db_path: TraceData\n"
        "    fetch_chunk: 250\n",
        encoding="utf-8",
    )
    trace_cfg, sim_raw = load_trace_config(start_path=tmp_path)
    assert trace_cfg.fetch_chunk == 250
    assert sim_raw["endpoint"] == "opc.tcp://10.0.0.1:4840"


def test_cli_group_exists():
    from plc_trace.cli import trace_group

    assert trace_group.name == "trace"
