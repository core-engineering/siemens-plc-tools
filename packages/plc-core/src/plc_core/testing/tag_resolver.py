"""Tag resolver: human-readable dot-paths to OPC UA NodeIds.

Recursively browses the PLC Simulation interface tree and builds
a cache mapping display-name paths (e.g. ``ProcessData.station.input.lampTest``)
to their OPC UA NodeIds (e.g. ``ns=4;i=42``).

The cache is persisted to disk as JSON so subsequent runs load instantly.

Performance note: the fast browse path uses asyncua directly instead of
going through ``OpcUaClient.browse_node()`` / ``_node_to_model()`` which
makes 5-7 OPC UA round-trips per node.  The fast path does 1 call per
level (``get_children``) plus 1 attribute read per child (node_class),
then only fetches data_type/access_level for leaf variables.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from asyncua import Node, ua

from plc_core.opcua.client import OpcUaClient, _get_data_type_name

logger = logging.getLogger(__name__)


@dataclass
class TagInfo:
    """Resolved tag metadata."""

    path: str
    node_id: str
    data_type: str
    is_writable: bool


@dataclass
class _CacheData:
    """Serializable tag cache."""

    tags: dict[str, TagInfo] = field(default_factory=dict)
    built_at: str = ""
    ttl_hours: int = 24
    tag_count: int = 0


class TagResolver:
    """Resolves human-readable dot-paths to OPC UA NodeIds.

    Parameters
    ----------
    client : OpcUaClient
        Connected OPC UA client.
    cache_dir : Path
        Directory to store/load the tag cache JSON.
    ttl_hours : int
        Hours before cache is considered stale.
    """

    def __init__(
        self,
        client: OpcUaClient,
        cache_dir: Path,
        ttl_hours: int = 24,
        on_progress: Any | None = None,
    ) -> None:
        self._client = client
        self._cache_dir = cache_dir
        self._ttl_hours = ttl_hours
        self._tags: dict[str, TagInfo] = {}
        self._built_at: datetime | None = None
        self._on_progress = on_progress  # callable(msg: str) for live feedback

    @property
    def cache_file(self) -> Path:
        return self._cache_dir / "tag_cache.json"

    @property
    def is_loaded(self) -> bool:
        return len(self._tags) > 0

    @property
    def is_stale(self) -> bool:
        """Whether the cache needs rebuilding."""
        if self._built_at is None:
            return True
        age_hours = (datetime.now(UTC) - self._built_at).total_seconds() / 3600
        return age_hours > self._ttl_hours

    @property
    def tag_count(self) -> int:
        return len(self._tags)

    # ------------------------------------------------------------------
    # Build cache by browsing the OPC UA tree
    # ------------------------------------------------------------------

    async def build_cache(self) -> int:
        """Recursively browse the Simulation tree and build tag map.

        Uses asyncua directly for speed — 1 ``get_children()`` per level
        instead of the heavy ``_node_to_model()`` path.

        Returns
        -------
        int
            Number of leaf tags discovered.
        """
        self._tags.clear()
        t0 = time.monotonic()

        # Get interface root nodes via the client (handles ServerInterfaces lookup)
        roots = await self._client.browse_node(None)

        for root in roots:
            self._progress(f"Browsing {root.display_name} ...")
            raw_node = self._client._client.get_node(root.node_id)  # type: ignore[union-attr]
            await self._browse_fast(raw_node, root.display_name)

        elapsed = time.monotonic() - t0
        self._built_at = datetime.now(UTC)

        logger.info(
            "Tag cache built: %d tags in %.1fs",
            len(self._tags),
            elapsed,
        )
        return len(self._tags)

    async def _browse_fast(self, node: Node, prefix: str) -> None:
        """Fast recursive browse using asyncua directly.

        Only reads node_class per child, then data_type + access_level
        for leaf variables.  Skips browse_name/display_name reads by
        using the child's browse name directly.
        """
        children = await node.get_children()

        for child in children:
            # Read display name — single call
            display = (await child.read_display_name()).Text
            if not display:
                bname = await child.read_browse_name()
                display = bname.Name
            path = f"{prefix}.{display}"

            node_class = await child.read_node_class()

            if node_class == ua.NodeClass.Variable:
                # Check for sub-children (struct variable vs leaf)
                sub = await child.get_children()
                if not sub:
                    # Leaf variable — read type info
                    data_type = "Unknown"
                    is_writable = False
                    try:
                        dt_id = await child.read_data_type()
                        data_type = _get_data_type_name(dt_id)
                    except Exception:
                        pass
                    try:
                        al = await child.read_attribute(ua.AttributeIds.AccessLevel)
                        variant = al.Value
                        if variant is not None:
                            val = variant.Value
                            is_writable = bool(int(val) & ua.AccessLevel.CurrentWrite.mask)
                    except Exception:
                        pass

                    self._tags[path] = TagInfo(
                        path=path,
                        node_id=child.nodeid.to_string(),
                        data_type=data_type,
                        is_writable=is_writable,
                    )
                else:
                    # Struct variable — recurse
                    await self._browse_fast(child, path)
            else:
                # Object node — recurse
                await self._browse_fast(child, path)

    def _progress(self, msg: str) -> None:
        """Emit progress feedback if callback is set."""
        if self._on_progress:
            self._on_progress(msg)

    # ------------------------------------------------------------------
    # Resolve paths
    # ------------------------------------------------------------------

    def resolve(self, path: str) -> TagInfo:
        """Resolve a single dot-path to TagInfo.

        Raises
        ------
        KeyError
            If path not found in cache.
        """
        tag = self._tags.get(path)
        if tag is None:
            raise KeyError(f"Tag not found: {path!r}")
        return tag

    def resolve_many(self, paths: list[str]) -> dict[str, TagInfo]:
        """Resolve multiple paths. Raises on first missing path."""
        return {p: self.resolve(p) for p in paths}

    def search(self, pattern: str) -> list[TagInfo]:
        """Search tags by substring match (case-insensitive)."""
        pattern_lower = pattern.lower()
        return [t for t in self._tags.values() if pattern_lower in t.path.lower()]

    # ------------------------------------------------------------------
    # Disk persistence
    # ------------------------------------------------------------------

    def save_cache(self) -> None:
        """Persist tag cache to JSON on disk."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        data = {
            "built_at": self._built_at.isoformat() if self._built_at else "",
            "ttl_hours": self._ttl_hours,
            "tag_count": len(self._tags),
            "tags": {path: asdict(info) for path, info in self._tags.items()},
        }

        self.cache_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Tag cache saved to %s (%d tags)", self.cache_file, len(self._tags))

    def load_cache(self) -> bool:
        """Load tag cache from disk if available and not stale.

        Returns
        -------
        bool
            True if cache was loaded successfully.
        """
        if not self.cache_file.exists():
            return False

        try:
            raw = json.loads(self.cache_file.read_text(encoding="utf-8"))
            built_at_str = raw.get("built_at", "")
            if built_at_str:
                self._built_at = datetime.fromisoformat(built_at_str)
            else:
                self._built_at = None

            self._ttl_hours = raw.get("ttl_hours", self._ttl_hours)

            if self.is_stale:
                logger.info("Tag cache is stale — will rebuild")
                return False

            tags_raw: dict[str, Any] = raw.get("tags", {})
            self._tags = {
                path: TagInfo(
                    path=info["path"],
                    node_id=info["node_id"],
                    data_type=info["data_type"],
                    is_writable=info["is_writable"],
                )
                for path, info in tags_raw.items()
            }

            logger.info(
                "Tag cache loaded from disk: %d tags (built %s)",
                len(self._tags),
                built_at_str,
            )
            return True

        except Exception:
            logger.warning("Failed to load tag cache", exc_info=True)
            return False

    async def ensure_loaded(self, force_refresh: bool = False) -> int:
        """Ensure the tag cache is loaded, building if necessary.

        Parameters
        ----------
        force_refresh : bool
            Force rebuild even if cache exists and is fresh.

        Returns
        -------
        int
            Number of tags available.
        """
        if not force_refresh and self.load_cache():
            return self.tag_count

        count = await self.build_cache()
        self.save_cache()
        return count
