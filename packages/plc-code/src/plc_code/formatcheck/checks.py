"""Pure checks over the bytes and text of one SIMATIC SD file.

Each family of codes is one function. They never raise on bad input: a
finding is the result. Nothing here reads the file system; the runner does.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Severity = Literal["ERROR", "WARNING"]

BOM = b"\xef\xbb\xbf"


@dataclass(frozen=True)
class Finding:
    """One violation of the import contract."""

    path: Path
    line: int | None
    code: str
    severity: Severity
    message: str


def check_bytes(path: Path, data: bytes) -> list[Finding]:
    """F001 (BOM), F002 (bare LF), F003 (UTF-8) on the raw bytes.

    F003 short-circuits: undecodable bytes make line counting meaningless.
    """
    findings: list[Finding] = []
    if not data.startswith(BOM):
        findings.append(
            Finding(
                path,
                None,
                "F001",
                "ERROR",
                "file does not start with the UTF-8 BOM",
            )
        )
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        findings.append(
            Finding(
                path,
                None,
                "F003",
                "ERROR",
                f"bytes are not valid UTF-8 ({exc.reason} at byte {exc.start})",
            )
        )
        return findings
    line = _first_bare_lf_line(data)
    if line is not None:
        findings.append(Finding(path, line, "F002", "ERROR", "line ends with a bare LF (TIA writes CRLF)"))
    return findings


def _first_bare_lf_line(data: bytes) -> int | None:
    """1-based number of the first line terminated by LF without a preceding CR."""
    for number, raw in enumerate(data.split(b"\n")[:-1], start=1):
        if not raw.endswith(b"\r"):
            return number
    return None
