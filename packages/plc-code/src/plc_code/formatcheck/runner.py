"""Walk a file or a workspace and aggregate import-readiness findings."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from plc_code.formatcheck.checks import Finding, check_bytes, check_text, check_xml
from plc_code.formatcheck.safety_grammar import check_s7res_pair, check_safety_grammar

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

    TIA Portal exports both ``.s7dcl`` sources and tag table XML with a UTF-8
    BOM and CRLF line endings, so F001/F002/F003 apply to every file the same
    way; only the text-level check dispatched afterwards differs by suffix.

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
    findings = check_bytes(path, data)
    if any(f.code == "F003" for f in findings):
        return findings
    text = data.decode("utf-8-sig")
    if path.suffix.lower() == ".xml":
        return findings + check_xml(path, text)
    # Les regles S0xx viennent d'imports reels en TIA V21 : elles refusent ce que l'importeur refuse,
    # message a l'appui (voir safety_grammar.py). Le compagnon .s7res est lu ici parce qu'un MLCID
    # n'a de sens qu'en paire — un identifiant sans texte s'affiche nu dans l'editeur.
    res_path = path.with_suffix(".s7res")
    res_text = res_path.read_text(encoding="utf-8-sig") if res_path.is_file() else None
    return (
        findings
        + check_text(path, text)
        + check_safety_grammar(path, text)
        + check_s7res_pair(path, text, res_text)
    )


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
