"""Step parsing and configuration of the supervision-pipeline test runner."""

from __future__ import annotations

from plc_sup.core.config import SupConfig
from plc_sup.testing.steps import (
    InfraStep,
    VerifyApiStep,
    VerifyRedisStep,
    _parse_infra,
    _parse_verify_api,
    _parse_verify_db,
    _parse_verify_redis,
)


class TestStepParsing:
    def test_verify_redis_parses_durations_and_defaults(self) -> None:
        step = _parse_verify_redis({"stream": "opcua:arm1", "path": "angle", "value": 1.5, "timeout": "2s"})
        assert step == VerifyRedisStep(
            stream="opcua:arm1", path="angle", value=1.5, timeout_s=2.0, poll_interval_s=0.5
        )

    def test_verify_db_defaults_to_one_row(self) -> None:
        step = _parse_verify_db({"query": "SELECT 1"})
        assert (step.expected_rows, step.timeout_s, step.poll_interval_s) == (1, 10.0, 1.0)

    def test_verify_api_uppercases_the_method(self) -> None:
        step = _parse_verify_api({"endpoint": "/health", "method": "post", "expected_status": 503})
        assert isinstance(step, VerifyApiStep)
        assert (step.method, step.expected_status, step.expected_json) == ("POST", 503, None)

    def test_infra_parses_the_action_and_timeout(self) -> None:
        step = _parse_infra({"action": "docker_restart", "container": "redis", "timeout": "30s"})
        assert step == InfraStep(action="docker_restart", container="redis", timeout_s=30.0)

    def test_the_step_types_are_registered_with_the_core_schema(self) -> None:
        from plc_core.testing.schema import _STEP_PARSERS as step_parsers  # registered at import time

        for name in ("verify_redis", "verify_db", "verify_api", "infra"):
            assert name in step_parsers


class TestSupConfig:
    def test_defaults_hold_without_a_config(self) -> None:
        config = SupConfig.from_dict({})
        assert config.redis.url == "redis://localhost:6379"
        assert config.database.url.startswith("postgresql://")
        assert config.api.base_url == "http://localhost:8000"
        assert config.testing.test_dir == "supervision-tests"

    def test_each_section_overrides_its_defaults(self) -> None:
        config = SupConfig.from_dict(
            {
                "redis": {"url": "redis://edge:6379", "stream_prefix": "sup:"},
                "database": {"url": "postgresql://edge:5432/x"},
                "api": {"base_url": "http://edge:8000"},
                "testing": {"test_dir": "tests-int"},
            }
        )
        assert config.redis.stream_prefix == "sup:"
        assert config.database.url == "postgresql://edge:5432/x"
        assert config.api.base_url == "http://edge:8000"
        assert config.testing.test_dir == "tests-int"
