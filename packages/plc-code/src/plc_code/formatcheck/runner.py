"""Walk a file or a workspace and aggregate import-readiness findings."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from plc_code.formatcheck.checks import Finding, check_bytes, check_text, check_xml

PATTERNS = ("**/*.s7dcl", "**/*.xml")


@dataclass
class Report:
    """Findings over a set of files.

    Attributes
    ----------
    files : int
        Number of files checked.
    findings : list[Finding]
        All findings across the checked files, in path order.
    """

    files: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> int:
        """Count of ERROR-severity findings."""
        return sum(1 for f in self.findings if f.severity == "ERROR")

    @property
    def warnings(self) -> int:
        """Count of WARNING-severity findings."""
        return sum(1 for f in self.findings if f.severity == "WARNING")

    @property
    def passed(self) -> bool:
        """True when there are no ERROR-severity findings."""
        return self.errors == 0


def check_file(path: Path) -> list[Finding]:
    """Check one file: byte checks first, text checks only when the bytes decode.

    UTF-8 BOM (F001) and CRLF (F002) are import requirements for ``.s7dcl``
    sources only; a tag table XML only needs to decode and be well-formed
    (checked by :func:`check_xml`), so those two codes are dropped for XML
    files while F003 (undecodable bytes) still applies to both.

    Parameters
    ----------
    path : Path
        File to check.

    Returns
    -------
    list[Finding]
        Findings for this file. If the bytes fail to decode (F003), text and
        XML checks are skipped since neither can run on undecodable bytes.
    """
    data = path.read_bytes()
    is_xml = path.suffix.lower() == ".xml"
    findings = check_bytes(path, data)
    if is_xml:
        findings = [f for f in findings if f.code == "F003"]
    if any(f.code == "F003" for f in findings):
        return findings
    text = data.decode("utf-8-sig")
    if is_xml:
        return findings + check_xml(path, text)
    return findings + check_text(path, text)


def check_path(path: Path) -> Report:
    """Check one file, or every ``.s7dcl``/``.xml`` file under a directory.

    Parameters
    ----------
    path : Path
        A single file, or a directory to walk recursively.

    Returns
    -------
    Report
        File count and findings, in path order.
    """
    files = (
        [path]
        if path.is_file()
        else sorted({p for pattern in PATTERNS for p in path.glob(pattern) if p.is_file()})
    )
    report = Report(files=len(files))
    for file in files:
        report.findings.extend(check_file(file))
    return report
