"""Helpers writing SIMATIC SD fixtures the way TIA Portal does (UTF-8 BOM, CRLF)."""

from __future__ import annotations

from pathlib import Path

BOM = b"\xef\xbb\xbf"


def write_s7dcl(directory: Path, name: str, text: str, *, bom: bool = True, crlf: bool = True) -> Path:
    """Write ``text`` as ``directory/name`` with TIA's encoding, or a deliberately broken variant."""
    body = text.replace("\r\n", "\n")
    if crlf:
        body = body.replace("\n", "\r\n")
    data = (BOM if bom else b"") + body.encode("utf-8")
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
