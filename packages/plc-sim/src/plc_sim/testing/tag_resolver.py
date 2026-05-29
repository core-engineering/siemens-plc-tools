"""Backward-compatible re-exports from plc-core."""

from plc_core.testing.tag_resolver import TagInfo, TagResolver  # noqa: F401

__all__ = ["TagInfo", "TagResolver"]
