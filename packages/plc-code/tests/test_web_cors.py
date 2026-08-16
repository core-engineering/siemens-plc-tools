"""Tests for the web server's cross-origin policy.

The analysis server has no authentication and its API reads project files and
(via the plc-sim mount) writes PLC tags.  It used to install CORS middleware
unconditionally with ``allow_origins=["*"]`` and ``allow_credentials=True``,
which advertises a credentialled cross-origin channel to any page the operator
happens to have open.  CORS is now opt-in through ``PLC_WEB_ALLOWED_ORIGINS``;
the bundled UI is same-origin and needs none.
"""

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from plc_code.web.app import CORS_ORIGINS_ENV, configure_cors


def _cors_middleware(app: FastAPI) -> list[object]:
    """Return the CORS middleware entries installed on ``app``."""
    return [m for m in app.user_middleware if m.cls is CORSMiddleware]


class TestCorsIsOptIn:
    """No environment variable, no cross-origin channel."""

    def test_unset_installs_no_middleware(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The default posture is same-origin only."""
        monkeypatch.delenv(CORS_ORIGINS_ENV, raising=False)
        app = FastAPI()
        assert configure_cors(app) == []
        assert _cors_middleware(app) == []

    def test_empty_value_installs_no_middleware(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty or whitespace value is not an allow-list."""
        monkeypatch.setenv(CORS_ORIGINS_ENV, "   ")
        app = FastAPI()
        assert configure_cors(app) == []
        assert _cors_middleware(app) == []

    def test_commas_only_installs_no_middleware(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Separators without origins yield no origins."""
        monkeypatch.setenv(CORS_ORIGINS_ENV, " , , ")
        app = FastAPI()
        assert configure_cors(app) == []
        assert _cors_middleware(app) == []


class TestCorsAllowList:
    """When set, the value is an explicit list of origins."""

    def test_single_origin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One origin is allow-listed verbatim."""
        monkeypatch.setenv(CORS_ORIGINS_ENV, "http://localhost:5173")
        app = FastAPI()
        assert configure_cors(app) == ["http://localhost:5173"]
        assert len(_cors_middleware(app)) == 1

    def test_multiple_origins_are_split_and_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Comma-separated, surrounding whitespace ignored."""
        monkeypatch.setenv(CORS_ORIGINS_ENV, "http://localhost:5173 , https://tools.example.com")
        app = FastAPI()
        assert configure_cors(app) == [
            "http://localhost:5173",
            "https://tools.example.com",
        ]

    def test_wildcard_is_only_ever_operator_chosen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``*`` remains possible, but only as a deliberate operator decision."""
        monkeypatch.setenv(CORS_ORIGINS_ENV, "*")
        app = FastAPI()
        assert configure_cors(app) == ["*"]


class TestShippedAppDefaults:
    """The module-level ``app`` is built at import time."""

    def test_module_app_has_no_wildcard_cors(self) -> None:
        """Importing the app must not install a wildcard CORS policy."""
        from plc_code.web.app import app as shipped_app

        for middleware in _cors_middleware(shipped_app):
            assert middleware.kwargs.get("allow_origins") != ["*"]  # type: ignore[attr-defined]
