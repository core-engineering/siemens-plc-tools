"""Helpers writing SIMATIC SD fixtures the way TIA Portal does (UTF-8 BOM, CRLF)."""

from __future__ import annotations

from pathlib import Path

BOM = b"\xef\xbb\xbf"


def write_s7dcl(directory: Path, name: str, text: str, *, bom: bool = True, crlf: bool = True) -> Path:
    """Write text as a SIMATIC SD file with TIA Portal's encoding or variants.

    Creates the file at ``directory/name`` with UTF-8 + BOM + CRLF by default
    (matching TIA Portal's output). Individual aspects can be disabled for
    testing error handling (e.g., missing BOM or bare LF line endings).

    Parameters
    ----------
    directory : Path
        Target directory; created if it does not exist.
    name : str
        Filename (e.g., "Probe.s7dcl").
    text : str
        Text content (internal line endings normalized to LF first).
    bom : bool, optional
        Include UTF-8 BOM (default: True, matching TIA Portal).
    crlf : bool, optional
        Convert LF to CRLF (default: True, matching TIA Portal).

    Returns
    -------
    Path
        Absolute path to the written file.
    """
    body = text.replace("\r\n", "\n")
    if crlf:
        body = body.replace("\n", "\r\n")
    data = (BOM if bom else b"") + body.encode("utf-8")
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
