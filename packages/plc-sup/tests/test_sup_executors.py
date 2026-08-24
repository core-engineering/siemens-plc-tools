"""The verify executors, run against hand-written fake clients (no server anywhere)."""

from __future__ import annotations

import asyncio
from typing import Any

from plc_core.testing.models import Outcome

from plc_sup.testing.executors import execute_verify_api, execute_verify_db, execute_verify_redis
from plc_sup.testing.steps import VerifyApiStep, VerifyDbStep, VerifyRedisStep


class _FakeRedis:
    def __init__(self, values: list[Any]) -> None:
        self._values = list(values)
        self.calls: list[tuple[str, str]] = []

    async def get_latest_stream_value(self, stream: str, path: str) -> Any:
        self.calls.append((stream, path))
        return self._values.pop(0) if len(self._values) > 1 else self._values[0]


class _FakeDb:
    def __init__(self, counts: list[int]) -> None:
        self._counts = list(counts)

    async def query_count(self, query: str) -> int:
        return self._counts.pop(0) if len(self._counts) > 1 else self._counts[0]


class _FakeApi:
    def __init__(self, status: int = 200, body: dict[str, Any] | None = None, error: Exception | None = None):
        self._status, self._body, self._error = status, body or {}, error

    async def request(self, endpoint: str, method: str, timeout_s: float) -> tuple[int, dict[str, Any]]:
        if self._error is not None:
            raise self._error
        return self._status, self._body


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class TestVerifyRedis:
    def test_passes_once_the_expected_value_appears(self) -> None:
        step = VerifyRedisStep(stream="opcua:a", path="x", value=2, timeout_s=1.0, poll_interval_s=0.0)
        result = _run(execute_verify_redis(None, 0, step, 0.0, redis_client=_FakeRedis([1, 2])))
        assert result.outcome is Outcome.PASSED
        assert result.actual_values == {"opcua:a:x": 2}

    def test_times_out_with_the_last_seen_value_in_the_message(self) -> None:
        step = VerifyRedisStep(stream="opcua:a", path="x", value=2, timeout_s=0.05, poll_interval_s=0.01)
        result = _run(execute_verify_redis(None, 0, step, 0.0, redis_client=_FakeRedis([7])))
        assert result.outcome is Outcome.FAILED
        assert (
            result.error_message is not None and "7" in result.error_message and "2" in result.error_message
        )


class TestVerifyDb:
    def test_passes_when_the_row_count_reaches_the_expectation(self) -> None:
        step = VerifyDbStep(query="SELECT 1", expected_rows=3, timeout_s=1.0, poll_interval_s=0.0)
        result = _run(execute_verify_db(None, 0, step, 0.0, db_client=_FakeDb([0, 3])))
        assert result.outcome is Outcome.PASSED and result.actual_values == {"rows": 3}

    def test_fails_after_the_deadline_with_both_counts(self) -> None:
        step = VerifyDbStep(query="SELECT 1", expected_rows=2, timeout_s=0.05, poll_interval_s=0.01)
        result = _run(execute_verify_db(None, 0, step, 0.0, db_client=_FakeDb([1])))
        assert result.outcome is Outcome.FAILED
        assert result.error_message is not None and "got 1 rows" in result.error_message


class TestVerifyApi:
    def test_status_and_json_subset_both_checked(self) -> None:
        step = VerifyApiStep(endpoint="/health", expected_status=200, expected_json={"status": "ok"})
        good = _run(
            execute_verify_api(None, 0, step, 0.0, api_client=_FakeApi(200, {"status": "ok", "extra": 1}))
        )
        assert good.outcome is Outcome.PASSED
        bad = _run(execute_verify_api(None, 0, step, 0.0, api_client=_FakeApi(200, {"status": "degraded"})))
        assert bad.outcome is Outcome.FAILED
        assert bad.error_message is not None and "degraded" in bad.error_message

    def test_a_wrong_status_fails_and_a_transport_error_is_an_error(self) -> None:
        step = VerifyApiStep(endpoint="/health", expected_status=200)
        wrong = _run(execute_verify_api(None, 0, step, 0.0, api_client=_FakeApi(503)))
        assert wrong.outcome is Outcome.FAILED and "503" in (wrong.error_message or "")
        broken = _run(execute_verify_api(None, 0, step, 0.0, api_client=_FakeApi(error=RuntimeError("down"))))
        assert broken.outcome is Outcome.ERROR and "down" in (broken.error_message or "")
