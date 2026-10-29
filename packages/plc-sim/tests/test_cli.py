"""The ``plc sim`` commands that talk to a server, on a fake OPC UA client."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from rich.console import Console

import plc_sim.cli as cli_module
import plc_sim.core.client as client_module
from plc_sim.cli import sim_group
from plc_sim.core.models import ConnectionInfo, ConnectionStatus, NodeClass, OpcUaNode, OpcUaValue
from plc_sim.testing.results_cache import (
    BaselineFingerprint,
    CachedScenarioResult,
    TestResultsCache,
    save_results_cache,
)

ENDPOINT = "opc.tcp://192.0.2.10:4840"

# A small address space: one folder with one writable variable and one sub-folder.
TREE: dict[str | None, list[OpcUaNode]] = {
    None: [
        OpcUaNode(
            node_id="db", browse_name="Db", display_name="Db", node_class=NodeClass.OBJECT, children_count=2
        )
    ],
    "db": [
        OpcUaNode(
            node_id="db.speed", browse_name="speed", display_name="speed", data_type="Float", is_writable=True
        ),
        OpcUaNode(
            node_id="db.sub",
            browse_name="sub",
            display_name="sub",
            node_class=NodeClass.OBJECT,
            children_count=1,
        ),
    ],
    "db.sub": [
        OpcUaNode(node_id="db.sub.flag", browse_name="flag", display_name="flag", data_type="Boolean")
    ],
}


class FakeOpcUaClient:
    """Stands in for ``OpcUaClient``; ``refuse`` makes ``connect`` fail as the real one reports it."""

    refuse = False
    browsed: list[str | None] = []
    values: dict[str, Any] = {}

    def __init__(self, config: Any) -> None:
        self.config = config

    async def connect(self) -> ConnectionInfo:
        if FakeOpcUaClient.refuse:
            return ConnectionInfo(status=ConnectionStatus.ERROR, error_message="connection refused")
        return ConnectionInfo(
            status=ConnectionStatus.CONNECTED,
            endpoint=self.config.endpoint,
            server_name="fake-server",
            session_id="s-1",
            namespaces=["urn:a", "urn:b"],
        )

    async def disconnect(self) -> None:
        pass

    async def browse_node(self, node_id: str | None = None) -> list[OpcUaNode]:
        FakeOpcUaClient.browsed.append(node_id)
        return TREE.get(node_id, [])

    async def read_value(self, node_id: str) -> OpcUaValue:
        return OpcUaValue(
            node_id=node_id, display_name=node_id, value=self.values.get(node_id, 0), data_type="Float"
        )

    async def write_value(self, node_id: str, value: str, data_type: str | None) -> bool:
        if node_id == "broken":
            raise ValueError("type mismatch")
        if node_id == "rejected":
            return False
        self.values[node_id] = value
        return True


@pytest.fixture(autouse=True)
def fake_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every command builds the fake; run from an empty directory so no plc.yaml is found.

    The console gets a fixed width so Rich wraps tables the same in any terminal.
    """
    monkeypatch.setattr(client_module, "OpcUaClient", FakeOpcUaClient)
    monkeypatch.setattr(cli_module, "console", Console(width=200))
    monkeypatch.chdir(tmp_path)
    FakeOpcUaClient.refuse = False
    FakeOpcUaClient.browsed = []
    FakeOpcUaClient.values = {}


def run(*args: str) -> Any:
    return CliRunner().invoke(sim_group, list(args), catch_exceptions=False)


def test_connect_prints_server_namespaces_and_roots() -> None:
    result = run("connect", "-e", ENDPOINT)
    assert result.exit_code == 0
    assert f"Connected to {ENDPOINT}" in result.output
    assert "fake-server" in result.output and "[1] urn:b" in result.output
    assert "Db" in result.output and "(2 children)" in result.output


def test_connect_reports_a_refused_connection() -> None:
    FakeOpcUaClient.refuse = True
    result = run("connect", "-e", ENDPOINT)
    assert result.exit_code == 1
    assert "Connection failed: connection refused" in result.output


def test_browse_stops_at_the_requested_depth() -> None:
    result = run("browse", "--depth", "2", "-e", ENDPOINT)
    assert result.exit_code == 0
    assert "speed" in result.output and "RW" in result.output and "sub" in result.output
    assert "flag" not in result.output
    assert FakeOpcUaClient.browsed == [None, "db"]


def test_browse_deeper_reaches_the_leaves() -> None:
    result = run("browse", "--depth", "3", "-e", ENDPOINT)
    assert "flag" in result.output
    assert FakeOpcUaClient.browsed == [None, "db", "db.sub"]


def test_browse_from_a_given_node() -> None:
    run("browse", "db", "--depth", "1", "-e", ENDPOINT)
    assert FakeOpcUaClient.browsed == ["db"]


def test_read_prints_value_type_and_quality() -> None:
    FakeOpcUaClient.values = {"db.speed": 1.5}
    result = run("read", "db.speed", "-e", ENDPOINT)
    assert result.exit_code == 0
    assert "1.5" in result.output and "Float" in result.output and "Good" in result.output


def test_write_reads_back_the_written_value() -> None:
    result = run("write", "db.speed", "2.5", "--type", "Float", "-e", ENDPOINT)
    assert result.exit_code == 0
    assert "OK db.speed = 2.5 (Float)" in result.output


def test_write_reports_a_failed_write() -> None:
    result = run("write", "broken", "1", "-e", ENDPOINT)
    assert result.exit_code == 1
    assert "Write failed: type mismatch" in result.output


def test_write_reports_a_write_the_server_rejects() -> None:
    result = run("write", "rejected", "1", "-e", ENDPOINT)
    assert result.exit_code == 1
    assert "Write failed" in result.output


@pytest.mark.parametrize(
    "command", [["browse"], ["read", "db.speed"], ["write", "db.speed", "1"], ["monitor", "db.speed"]]
)
def test_commands_report_a_refused_connection_with_exit_1(command: list[str]) -> None:
    FakeOpcUaClient.refuse = True
    result = run(*command, "-e", ENDPOINT)
    assert result.exit_code == 1
    assert "Connection failed: connection refused" in result.output


class TestResults:
    def _write_cache(self, tmp_path: Path) -> None:
        cache = TestResultsCache(
            baseline=BaselineFingerprint(
                hash="0123456789abcdef", source_files={"a.s7dcl": "x"}, computed_at="t0"
            ),
            results={
                "EFAT-001 start pump": CachedScenarioResult(
                    "EFAT-001 start pump", None, "passed", 1.25, None, "2026-01-01T00:00:00"
                ),
                "EFAT-002 stop pump": CachedScenarioResult(
                    "EFAT-002 stop pump",
                    None,
                    "failed",
                    0.5,
                    "expected True\ngot False",
                    "2026-01-01T00:00:01",
                ),
            },
        )
        save_results_cache(cache, tmp_path / ".sim" / "test_results.json")

    def test_without_a_cache_it_exits_1(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(sim_group, ["results"])
        assert result.exit_code == 1
        assert "No results cache found" in result.output

    def test_lists_every_cached_scenario_with_totals(self, tmp_path: Path) -> None:
        self._write_cache(tmp_path)
        result = run("results")
        assert result.exit_code == 0
        assert "0123456789ab" in result.output
        assert "1 failed" in result.output and "1 passed" in result.output
        assert "EFAT-001" in result.output and "EFAT-002" in result.output
        assert "expected True got False" in result.output
        assert "Displayed 2 of 2" in result.output

    def test_failed_only_and_filter(self, tmp_path: Path) -> None:
        self._write_cache(tmp_path)
        assert "Displayed 1 of 2" in run("results", "--failed-only").output
        assert "EFAT-001" not in run("results", "--failed-only").output
        assert "No scenarios match" in run("results", "-k", "valve").output
