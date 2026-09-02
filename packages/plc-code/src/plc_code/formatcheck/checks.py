"""Pure checks over the bytes and text of one SIMATIC SD file.

Each family of codes is one function. They never raise on bad input: a
finding is the result. Nothing here reads the file system; the runner does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Severity = Literal["ERROR", "WARNING"]

BOM = b"\xef\xbb\xbf"


@dataclass(frozen=True)
class Finding:
    """One violation of the import contract.

    Attributes
    ----------
    path : Path
        File path where the violation occurs.
    line : int | None
        1-based line number (None for file-level violations like F001, F003).
    code : str
        Unique violation code (e.g., "F001", "F002", "F003").
    severity : Severity
        Violation severity level ("ERROR" or "WARNING").
    message : str
        Human-readable violation message.
    """

    path: Path
    line: int | None
    code: str
    severity: Severity
    message: str


def check_bytes(path: Path, data: bytes) -> list[Finding]:
    """Check raw bytes of a SIMATIC SD file for import-readiness violations.

    Validates F001 (UTF-8 BOM), F002 (bare LF line endings), and F003 (UTF-8
    encoding). Never raises on bad input; violations are returned as findings.
    F003 short-circuits: undecodable bytes make line counting meaningless.

    Parameters
    ----------
    path : Path
        File path (used in Finding output; file is not read).
    data : bytes
        Raw file contents to check.

    Returns
    -------
    list[Finding]
        List of violations found. Empty list if all checks pass.
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


_BLOCK_RE = re.compile(
    r"^\s*(FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK|DATA_BLOCK|TYPE)\b\s*(?:\"([^\"]+)\"|([A-Za-z_][\w]*))?",
    re.MULTILINE,
)
_UDT_NAME_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*:\s*STRUCT\b", re.MULTILINE | re.IGNORECASE)
_PRAGMA_ITEM_RE = re.compile(r"(S7_\w+)\s*:=\s*\"([^\"]*)\"")
_S7_OPTIMIZED_ACCESS_RE = re.compile(r"S7_Optimized_Access")
_TITLE_RE = re.compile(r"^\s*TITLE\s*=", re.MULTILINE)
_BEGIN_RE = re.compile(r"^\s*BEGIN\s*$", re.MULTILINE)

CODE_KINDS = ("FUNCTION_BLOCK", "FUNCTION", "ORGANIZATION_BLOCK")


def _strip_comments_and_strings(text: str) -> str:
    """Remove comments and string literals from text, replacing with spaces.

    Removes:
    - Single-quoted strings: 'text'
    - Double-quoted strings: "text"
    - Line comments: // to end of line
    - Block comments: (* ... *)

    Replaces each removed section with spaces to preserve line numbers.

    Parameters
    ----------
    text : str
        Source text to clean.

    Returns
    -------
    str
        Text with comments and strings replaced by spaces.
    """
    result: list[str] = []
    i = 0
    while i < len(text):
        # Check for single-quoted string
        if text[i] == "'":
            start = i
            i += 1
            while i < len(text):
                if text[i] == "'":
                    i += 1
                    break
                i += 1
            result.append(" " * (i - start))
        # Check for double-quoted string
        elif text[i] == '"':
            start = i
            i += 1
            while i < len(text):
                if text[i] == '"':
                    i += 1
                    break
                i += 1
            result.append(" " * (i - start))
        # Check for line comment
        elif i + 1 < len(text) and text[i : i + 2] == "//":
            start = i
            while i < len(text) and text[i] != "\n":
                i += 1
            result.append(" " * (i - start))
        # Check for block comment
        elif i + 1 < len(text) and text[i : i + 2] == "(*":
            start = i
            i += 2
            while i + 1 < len(text):
                if text[i : i + 2] == "*)":
                    i += 2
                    break
                i += 1
            else:
                # Unclosed block comment, consume to end
                i = len(text)
            result.append(" " * (i - start))
        else:
            result.append(text[i])
            i += 1
    return "".join(result)


@dataclass(frozen=True)
class BlockHeader:
    """What the light scan learns about the (first) block of a file.

    Attributes
    ----------
    kind : str
        Block keyword (e.g., "FUNCTION_BLOCK", "DATA_BLOCK", "TYPE").
    name : str
        Block name (unquoted or extracted from STRUCT definition).
    pragma : dict[str, str]
        Dictionary of S7_* pragmas found before the block keyword.
    line : int
        1-based line number where the block keyword appears.
    """

    kind: str
    name: str
    pragma: dict[str, str]
    line: int


def scan_block(text: str) -> BlockHeader | None:
    """Locate the first block keyword, its name and the pragma that precedes it.

    A regex scan, not the parser: a file that does not parse still gets its
    format verdict. ``TYPE`` names sit inside the block (``name : STRUCT``).

    Parameters
    ----------
    text : str
        File text to scan.

    Returns
    -------
    BlockHeader | None
        Header information for the first block, or None if no block found.
    """
    match = _BLOCK_RE.search(text)
    if match is None:
        return None
    kind = match.group(1)
    name = match.group(2) or match.group(3) or ""
    if kind == "TYPE":
        # Find first UDT name (name : STRUCT) after the TYPE keyword
        for m in _UDT_NAME_RE.finditer(text):
            if m.start() > match.end():
                name = m.group(1)
                break
    pragma = dict(_PRAGMA_ITEM_RE.findall(text[: match.start()]))
    line = text.count("\n", 0, match.start()) + 1
    return BlockHeader(kind=kind, name=name, pragma=pragma, line=line)


def _has_external_markers(text: str) -> bool:
    """Check if text contains external-source form markers (outside comments/strings).

    Looks for:
    - S7_Optimized_Access inside pragma blocks { ... }
    - TITLE = at line start
    - BEGIN on its own line

    Parameters
    ----------
    text : str
        File text to check.

    Returns
    -------
    bool
        True if external-source markers detected.
    """
    cleaned = _strip_comments_and_strings(text)

    # Check for TITLE = at line start
    if _TITLE_RE.search(cleaned):
        return True

    # Check for BEGIN on its own line
    if _BEGIN_RE.search(cleaned):
        return True

    # Check for S7_Optimized_Access inside pragma blocks { ... }
    i = 0
    while i < len(cleaned):
        brace_pos = cleaned.find("{", i)
        if brace_pos == -1:
            break
        close_brace = cleaned.find("}", brace_pos)
        if close_brace == -1:
            break
        pragma_block = cleaned[brace_pos : close_brace + 1]
        if _S7_OPTIMIZED_ACCESS_RE.search(pragma_block):
            return True
        i = close_brace + 1

    return False


def check_text(path: Path, text: str) -> list[Finding]:
    """F010 (external-source form), F011 (one block per file), F012 (file name), F020/F021 (header).

    Parameters
    ----------
    path : Path
        File path (used in Finding output; file is not read).
    text : str
        File text to check.

    Returns
    -------
    list[Finding]
        List of violations found. Empty list if all checks pass.
    """
    if _has_external_markers(text):
        return [
            Finding(
                path,
                None,
                "F010",
                "ERROR",
                (
                    "external-source form (TITLE/BEGIN/S7_Optimized_Access); a VCI workspace holds "
                    "SIMATIC SD files"
                ),
            )
        ]
    findings: list[Finding] = []
    blocks = list(_BLOCK_RE.finditer(text))
    if len(blocks) > 1:
        line = text.count("\n", 0, blocks[1].start()) + 1
        msg = f"{len(blocks)} blocks in one file; TIA writes one block per file"
        findings.append(Finding(path, line, "F011", "ERROR", msg))
    header = scan_block(text)
    if header is None:
        return findings
    if header.name and header.name != path.stem:
        msg = f"block '{header.name}' in a file named '{path.stem}'"
        findings.append(Finding(path, header.line, "F012", "ERROR", msg))
    if header.kind in CODE_KINDS and "S7_EditorMode" not in header.pragma:
        msg = f"{header.kind} header lacks S7_EditorMode"
        findings.append(Finding(path, header.line, "F020", "ERROR", msg))
    if header.kind == "DATA_BLOCK" and "S7_StandardRetain" not in header.pragma:
        msg = "DATA_BLOCK header lacks S7_StandardRetain"
        findings.append(Finding(path, header.line, "F020", "ERROR", msg))
    if header.kind != "TYPE" and "S7_Optimized" not in header.pragma:
        msg = f"{header.kind} header lacks S7_Optimized"
        findings.append(Finding(path, header.line, "F021", "WARNING", msg))
    return findings
