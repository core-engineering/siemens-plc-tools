"""The simulation web API and its service layer, on a fake OPC UA client."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plc_sim.core.config import SimConfig
from plc_sim.core.models import ConnectionInfo, ConnectionStatus, OpcUaNode, OpcUaValue
from plc_sim.web import services
from plc_sim.web.routes import sim_router
from plc_sim.web.services import SimService, get_sim_service

ENDPOINT = "opc.tcp://192.0.2.10:4840"


class FakeOpcUaClient:
    """Stands in for ``OpcUaClient``: records calls, answers from fixed data."""

    instances: list[FakeOpcUaClient] = []
    fail_connect = False

    def __init__(self, config: Any) -> None:
        self.config = config
        self.is_connected = False
        self.writes: list[tuple[str, Any, str | None]] = []
        self.unsubscribed: list[str] = []
        FakeOpcUaClient.instances.append(self)

    async def connect(self) -> ConnectionInfo:
        if FakeOpcUaClient.fail_connect:
            raise OSError("connection refused")
        self.is_connected = True
        return ConnectionInfo(
            status=ConnectionStatus.CONNECTED, endpoint=self.config.endpoint, server_name="fake"
        )

    async def disconnect(self) -> None:
        self.is_connected = False

    async def get_status(self) -> ConnectionInfo:
        status = ConnectionStatus.CONNECTED if self.is_connected else ConnectionStatus.DISCONNECTED
        return ConnectionInfo(status=status, endpoint=self.config.endpoint, server_name="fake")

    async def browse_node(self, node_id: str | None) -> list[OpcUaNode]:
        parent = node_id or "root"
        return [OpcUaNode(node_id=f"{parent}.a", browse_name="a", display_name="a", parent_node_id=parent)]

    async def read_values(self, node_ids: list[str]) -> list[OpcUaValue]:
        return [OpcUaValue(node_id=n, value=len(n)) for n in node_ids]

    async def write_value(self, node_id: str, value: Any, data_type: str | None) -> bool:
        if node_id == "broken":
            raise ValueError("type mismatch")
        self.writes.append((node_id, value, data_type))
        return True

    async def subscribe(
        self, node_ids: list[str], queue: asyncio.Queue[OpcUaValue], interval_ms: int | None
    ) -> str:
        for n in node_ids:
            queue.put_nowait(OpcUaValue(node_id=n, value=1))
        return "sub-1"

    async def unsubscribe(self, subscription_id: str) -> None:
        self.unsubscribed.append(subscription_id)


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> SimService:
    """A fresh singleton wired to the fake client and a config that reads no plc.yaml."""
    monkeypatch.setattr(services, "OpcUaClient", FakeOpcUaClient)
    monkeypatch.setattr(services, "_service", None)
    FakeOpcUaClient.instances = []
    FakeOpcUaClient.fail_connect = False
    svc = get_sim_service()
    config = SimConfig()
    config.endpoint = ENDPOINT
    svc.set_config(config)
    return svc


@pytest.fixture
def api(service: SimService) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(sim_router)
    with TestClient(app) as client:
        yield client


class TestBeforeConnect:
    def test_config_reports_the_endpoint_and_no_config_file(self, api: TestClient) -> None:
        body = api.get("/api/sim/config").json()
        assert body["endpoint"] == ENDPOINT
        assert body["has_config"] is False

    def test_status_is_disconnected(self, api: TestClient) -> None:
        body = api.get("/api/sim/status").json()
        assert (body["status"], body["endpoint"]) == ("disconnected", ENDPOINT)

    @pytest.mark.parametrize(
        ("method", "url", "payload"),
        [
            ("get", "/api/sim/browse", None),
            ("get", "/api/sim/read?node_id=ns=3;s=x", None),
            ("post", "/api/sim/write", {"node_id": "ns=3;s=x", "value": 1}),
            ("get", "/api/sim/subscribe?node_id=ns=3;s=x", None),
        ],
    )
    def test_live_calls_are_refused_with_409(
        self, api: TestClient, method: str, url: str, payload: dict[str, Any] | None
    ) -> None:
        response = api.request(method.upper(), url, json=payload)
        assert response.status_code == 409
        assert "Not connected" in response.json()["detail"]


class TestConnected:
    @pytest.fixture(autouse=True)
    def _connect(self, api: TestClient) -> None:
        assert api.post("/api/sim/connect").json()["status"] == "connected"

    def test_connect_uses_the_configured_endpoint(self) -> None:
        assert FakeOpcUaClient.instances[-1].config.endpoint == ENDPOINT

    def test_browse_without_node_lists_the_roots(self, api: TestClient) -> None:
        body = api.get("/api/sim/browse").json()
        assert body["parent_node_id"] == ""
        assert [n["node_id"] for n in body["nodes"]] == ["root.a"]

    def test_browse_a_node(self, api: TestClient) -> None:
        body = api.get("/api/sim/browse", params={"node_id": "ns=3;s=Db"}).json()
        assert body["parent_node_id"] == "ns=3;s=Db"
        assert body["nodes"][0]["node_id"] == "ns=3;s=Db.a"

    def test_read_several_values(self, api: TestClient) -> None:
        body = api.get("/api/sim/read", params=[("node_id", "ab"), ("node_id", "abc")]).json()
        assert [(v["node_id"], v["value"]) for v in body["values"]] == [("ab", 2), ("abc", 3)]

    def test_write_passes_value_and_type(self, api: TestClient) -> None:
        body = api.post("/api/sim/write", json={"node_id": "x", "value": 4.5, "data_type": "Float"}).json()
        assert body == {"success": True, "node_id": "x", "error": ""}
        assert FakeOpcUaClient.instances[-1].writes == [("x", 4.5, "Float")]

    def test_a_failed_write_is_reported_in_the_body(self, api: TestClient) -> None:
        response = api.post("/api/sim/write", json={"node_id": "broken", "value": 1})
        assert response.status_code == 200
        assert response.json() == {"success": False, "node_id": "broken", "error": "type mismatch"}

    def test_write_multiple_reports_each_write(self, api: TestClient) -> None:
        writes = [{"node_id": "x", "value": True}, {"node_id": "broken", "value": 1}]
        body = api.post("/api/sim/write-multiple", json={"writes": writes}).json()
        assert [(r["node_id"], r["success"], r["error"]) for r in body] == [
            ("x", True, ""),
            ("broken", False, "type mismatch"),
        ]

    def test_disconnect_returns_to_disconnected(self, api: TestClient) -> None:
        assert api.post("/api/sim/disconnect").json() == {"status": "disconnected"}
        assert api.get("/api/sim/status").json()["status"] == "disconnected"
        assert api.get("/api/sim/browse").status_code == 409


def test_connect_with_an_endpoint_override(api: TestClient) -> None:
    other = "opc.tcp://192.0.2.11:4840"
    body = api.post("/api/sim/connect", json={"endpoint": other}).json()
    assert body["endpoint"] == other
    assert FakeOpcUaClient.instances[-1].config.endpoint == other


def test_a_connection_failure_is_a_500(api: TestClient) -> None:
    FakeOpcUaClient.fail_connect = True
    response = api.post("/api/sim/connect")
    assert response.status_code == 500
    assert response.json()["detail"] == "connection refused"


class TestService:
    def test_set_config_drops_the_client(self, service: SimService) -> None:
        asyncio.run(service.connect())
        assert service.client is not None
        service.set_config(SimConfig())
        assert service.client is None

    def test_monitoring_streams_changes_and_unsubscribes(self, service: SimService) -> None:
        async def scenario() -> tuple[str, list[str], list[str]]:
            await service.connect()
            sub_id, queue = await service.start_monitoring(["a", "b"])
            stream = service.get_change_stream(queue)
            seen = [(await anext(stream)).node_id, (await anext(stream)).node_id]
            await stream.aclose()
            await service.stop_monitoring(sub_id)
            assert queue not in service._change_queues
            client = service.client
            assert isinstance(client, FakeOpcUaClient)
            return sub_id, seen, client.unsubscribed

        assert asyncio.run(scenario()) == ("sub-1", ["a", "b"], ["sub-1"])
