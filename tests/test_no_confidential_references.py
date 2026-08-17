"""Guard against confidential references re-entering this public repository.

This repository is public. Customer project names, contract codes and local
developer paths have leaked into it before — through design docs, CHANGELOG
measurements and test docstrings that cited real programs by name. Removing them
took a full history rewrite, so this test exists to make sure it happens once.

Two kinds of check:

**Structural patterns.** Contract codes and absolute developer paths have a
recognisable shape, so a regex catches them without naming anything.

**An encoded deny-list.** Site and project names have no shape to match, so they
have to be listed. Listing them in plaintext would put the very strings this test
exists to exclude back into the public repo — a test that causes the leak it
checks for. They are therefore base64-encoded. That is obfuscation, not secrecy:
anyone can decode it. The point is only that a clone or a code search for the
customer's name does not hit this file.

To add a term::

    python -c "import base64; print(base64.b64encode(b'newterm').decode())"

Matching is case-insensitive and substring-based, so store terms lowercase.
"""

from __future__ import annotations

import base64
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Base64 of lowercase customer/site/project identifiers. See the module docstring.
_ENCODED_DENY_LIST = (
    "cnV3YWlz",  # a site name
    "YXJjb3M=",  # a project name
    "cGFkYWg=",  # a project name
    "cnVja2lnLXNjbA==",  # an internal port's repo name (the upstream library is public)
    "YXNzaXN0ZWQtY29ubmVjdGlvbg==",  # a project name
    "bWFyaW5lbG9hZGluZ2FybQ==",  # a product family
    "dGVjaG5pcA==",  # a company name
    "bG9hZGluZyBzeXN0ZW1z",  # a business-unit name
)

#: Leaks with a recognisable shape, safe to express in the open.
_PATTERNS = (
    (re.compile(r"C2\d{5}"), "a contract/project code"),
    (re.compile(r"/mnt/c/Users/[A-Za-z0-9._-]+"), "an absolute developer path"),
    (re.compile(r"[A-Za-z]:\\Users\\[A-Za-z0-9._-]+"), "an absolute Windows path"),
)

#: Directories that hold internal working notes and must never be tracked.
_FORBIDDEN_TRACKED_PREFIXES = (
    ".superpowers/",
    "docs/superpowers/",
    "docs/audits/",
)

#: Suffixes worth scanning. Binary and generated content is skipped.
_TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
    ".cfg",
    ".ini",
    ".txt",
    ".json",
    ".s7dcl",
    ".xml",
    ".js",
    ".css",
    ".sh",
    ".gitignore",
}


def _tracked_files() -> list[str]:
    """List every file git tracks, relative to the repository root.

    Returns
    -------
    list[str]
        Repository-relative paths.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [p for p in out.stdout.split("\0") if p]


def _deny_terms() -> list[str]:
    """Decode the deny-list.

    Returns
    -------
    list[str]
        Lowercase identifiers that must not appear in tracked files.
    """
    return [base64.b64decode(entry).decode().lower() for entry in _ENCODED_DENY_LIST]


def _scannable(paths: list[str]) -> list[str]:
    """Keep the text files worth scanning, minus this test itself.

    Parameters
    ----------
    paths : list[str]
        Repository-relative paths.

    Returns
    -------
    list[str]
        Paths to scan.
    """
    self_rel = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()
    return [
        p
        for p in paths
        if p != self_rel and (Path(p).suffix in _TEXT_SUFFIXES or Path(p).name == ".gitignore")
    ]


def test_no_internal_note_directories_are_tracked() -> None:
    """Plan ledgers, task briefs and internal audits stay out of the repo.

    A missing ``.gitignore`` entry is how an internal report was committed the
    first time, so this asserts on what git actually tracks rather than on the
    ignore file.
    """
    tracked = _tracked_files()
    offenders = [p for p in tracked if p.startswith(_FORBIDDEN_TRACKED_PREFIXES)]
    assert not offenders, "internal working notes are tracked:\n  " + "\n  ".join(offenders)


def test_no_confidential_identifiers_in_tracked_files() -> None:
    """No customer identifier, contract code or developer path in tracked files."""
    terms = _deny_terms()
    findings: list[str] = []

    for rel in _scannable(_tracked_files()):
        path = REPO_ROOT / rel
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        lowered = text.lower()
        hits = {term for term in terms if term in lowered}
        for line_number, line in enumerate(text.splitlines(), start=1):
            low = line.lower()
            for term in sorted(hits):
                if term in low:
                    findings.append(f"{rel}:{line_number}: deny-listed identifier")
            for pattern, what in _PATTERNS:
                if pattern.search(line):
                    findings.append(f"{rel}:{line_number}: {what}")

    assert not findings, (
        "confidential references found in tracked files. This repository is "
        "public — scrub these before committing:\n  " + "\n  ".join(sorted(set(findings)))
    )
