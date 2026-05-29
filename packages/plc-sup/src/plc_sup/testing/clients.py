"""Async client wrappers for supervision infrastructure verification."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx
import msgpack  # type: ignore[import-untyped]
import psycopg
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class RedisVerifier:
    """Async Redis client for stream verification."""

    def __init__(self, url: str = "redis://localhost:6379") -> None:
        self._url = url
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        client = aioredis.from_url(self._url, decode_responses=False)
        # redis-py's typing for .ping() unions sync (bool) and async
        # (Awaitable[bool]) variants; await is correct at runtime on the
        # async client.
        await client.ping()  # type: ignore[misc]
        self._client = client
        logger.info("Connected to Redis at %s", self._url)

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_latest_stream_value(self, stream: str, path: str) -> Any | None:
        """Read the latest entry from a Redis stream and extract a nested value.

        Parameters
        ----------
        stream : str
            Redis stream key (e.g., "opcua:data").
        path : str
            Dot-separated path into the msgpack-decoded data.

        Returns
        -------
        Any | None
            The value at the path, or None if not found.
        """
        if not self._client:
            raise RuntimeError("Not connected to Redis")

        entries = await self._client.xrevrange(stream, count=1)
        if not entries:
            return None

        _entry_id, fields = entries[0]
        # Stream entries have a "value" field containing msgpack data
        raw_value = fields.get(b"value")
        if raw_value is None:
            return None

        try:
            data = msgpack.unpackb(raw_value, raw=False)
        except Exception:
            return None

        if isinstance(data, dict):
            return _get_nested(data, path)

        return None


class DbVerifier:
    """Sync PostgreSQL client for database verification.

    Uses psycopg (sync) wrapped in asyncio.to_thread for async compatibility.
    """

    def __init__(self, url: str = "postgresql://localhost:5432/supervision") -> None:
        self._url = url

    async def query_count(self, query: str) -> int:
        """Execute a query and return the row count."""

        def _run() -> int:
            with psycopg.connect(self._url) as conn:
                with conn.cursor() as cur:
                    cur.execute(query)
                    rows = cur.fetchall()
                    return len(rows)

        return await asyncio.to_thread(_run)


class ApiVerifier:
    """Async HTTP client for API verification."""

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        self._base_url = base_url.rstrip("/")

    async def request(
        self,
        endpoint: str,
        method: str = "GET",
        timeout_s: float = 5.0,
    ) -> tuple[int, dict[str, Any] | None]:
        """Send an HTTP request and return (status_code, json_body).

        Returns
        -------
        tuple[int, dict | None]
            HTTP status code and parsed JSON body (or None).
        """
        url = f"{self._base_url}{endpoint}"
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.request(method, url)
            try:
                body = response.json()
            except Exception:
                body = None
            return response.status_code, body


def _get_nested(data: dict[str, Any], path: str) -> Any | None:
    """Traverse a nested dict/list using dot-separated path.

    Supports numeric indices for list access (e.g., "arms.0.percCollar").
    """
    current: Any = data
    for key in path.split("."):
        if isinstance(current, dict):
            current = current.get(key)
            if current is None:
                return None
        elif isinstance(current, list):
            try:
                current = current[int(key)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


class InfraClient:
    """SSH-based infrastructure client for docker operations on edge device."""

    def __init__(
        self,
        ssh_host: str,
        ssh_user: str = "maintenance",
        ssh_auth_sock: str | None = None,
        expected_containers: int = 0,
    ) -> None:
        self._ssh_host = ssh_host
        self._ssh_user = ssh_user
        self._expected_containers = expected_containers
        # Prefer an explicit socket (from config), then the ambient
        # SSH_AUTH_SOCK environment variable, then a conventional fallback.
        self._ssh_auth_sock = (
            ssh_auth_sock or os.environ.get("SSH_AUTH_SOCK") or os.path.expanduser("~/.ssh/agent.sock")
        )

    async def _ssh_cmd(self, cmd: str, timeout_s: float = 30.0) -> tuple[int, str]:
        """Run a command on the edge device via SSH."""
        ssh_cmd = (
            f"ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "
            f"{self._ssh_user}@{self._ssh_host} {cmd!r}"
        )
        proc = await asyncio.subprocess.create_subprocess_shell(
            ssh_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={
                **os.environ,
                "SSH_AUTH_SOCK": self._ssh_auth_sock,
            },
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except TimeoutError:
            proc.kill()
            return 1, f"SSH command timed out after {timeout_s}s"
        output = (stdout or b"").decode() + (stderr or b"").decode()
        return proc.returncode or 0, output.strip()

    async def docker_stop(self, container: str) -> str:
        """Stop a container on the edge device."""
        code, output = await self._ssh_cmd(f"docker stop {container}")
        if code != 0:
            raise RuntimeError(f"Failed to stop {container}: {output}")
        logger.info("Stopped container %s", container)
        return output

    async def docker_start(self, container: str) -> str:
        """Start a container on the edge device."""
        code, output = await self._ssh_cmd(f"docker start {container}")
        if code != 0:
            raise RuntimeError(f"Failed to start {container}: {output}")
        logger.info("Started container %s", container)
        return output

    async def docker_restart(self, container: str) -> str:
        """Restart a container on the edge device."""
        code, output = await self._ssh_cmd(f"docker restart {container}")
        if code != 0:
            raise RuntimeError(f"Failed to restart {container}: {output}")
        logger.info("Restarted container %s", container)
        return output

    async def wait_healthy(self, container: str, timeout_s: float = 120.0) -> bool:
        """Wait until a container reports healthy status."""
        import time

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            code, output = await self._ssh_cmd(
                f"docker inspect --format='{{{{.State.Health.Status}}}}' {container}"
            )
            if code == 0 and "healthy" in output:
                logger.info("Container %s is healthy", container)
                return True
            await asyncio.sleep(3)
        return False

    async def wait_all_healthy(self, timeout_s: float = 120.0, expected_count: int | None = None) -> bool:
        """Wait until at least ``expected_count`` containers are healthy.

        Parameters
        ----------
        timeout_s : float
            Maximum time to wait, in seconds.
        expected_count : int | None
            Number of containers expected to report ``healthy`` status.
            Defaults to the value configured on the client
            (``expected_containers`` from the infrastructure config).
        """
        import time

        if expected_count is None:
            expected_count = self._expected_containers
        if expected_count <= 0:
            raise ValueError(
                "expected_count must be > 0; set infra.expected_containers in config "
                "or pass expected_count explicitly"
            )

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            code, output = await self._ssh_cmd(
                "docker ps --format '{{.Names}} {{.Status}}' | grep -c healthy"
            )
            if code == 0:
                try:
                    count = int(output.strip())
                    if count >= expected_count:
                        logger.info("All %d containers healthy", count)
                        return True
                except ValueError:
                    pass
            await asyncio.sleep(5)
        return False

    async def docker_ps(self) -> str:
        """Get container status from edge device."""
        code, output = await self._ssh_cmd("docker ps --format 'table {{.Names}}\t{{.Status}}'")
        return output if code == 0 else f"Failed: {output}"

    @staticmethod
    async def wait_for_user(message: str) -> None:
        """Prompt user for a physical action and wait for Enter."""
        import sys

        print(f"\n  >>> {message}")
        print("  >>> Press Enter when done...")
        await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
