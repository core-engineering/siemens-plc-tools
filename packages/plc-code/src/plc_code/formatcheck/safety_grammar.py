"""SIMATIC SD grammar rules for fail-safe blocks, measured at import time.

Every rule here was established by importing or compiling a real file in TIA
Portal V21 on an S7-1518HF-4 PN (firmware V3.1) and reading the message the
tool gave back. The message is quoted verbatim in each rule's docstring, so a
rule can never be weakened or reinvented from memory: if the quote is missing,
the rule was never measured.

The rules exist because generated SD files look plausible long after they have
stopped being importable. A generator that emits ``x : DInt := 0;`` produces a
file that reads perfectly and that TIA refuses, and the loop from "generate" to
"paste the error back" costs a round trip through a human every time.
"""

from __future__ import annotations

import re
from pathlib import Path

from plc_code.formatcheck.checks import Finding

#: Instructions written without quotes in a SIMATIC SD ladder body. Everything
#: else that appears in call position is a user block and must be quoted.
SYSTEM_INSTRUCTIONS = frozenset({
    "Add", "Sub", "Mul", "Div", "Mod", "Move", "Neg", "Abs",
    "Coil", "Contact", "SetCoil", "ResetCoil", "JumpCoil", "Label",
    "RD_ARRAY_DI", "WR_ARRAY_DI", "RD_ARRAY_I", "WR_ARRAY_I",
    "GT_Contact", "LT_Contact", "GE_Contact", "LE_Contact", "EQ_Contact", "NE_Contact",
})

_TITLE = re.compile(r"^\s*TITLE\s*=")
_DECL_WITH_VALUE = re.compile(r"^\s+\w+\s*:\s*(?:DInt|Int|DWord|Word|Bool|Time|Real)\s*:=")
_SAFETY_HEADER = re.compile(r'S7_Safety\s*:=\s*"(?:TRUE|True)"', re.IGNORECASE)
_MLCID_USE = re.compile(r'S7_(?:BlockTitle|NetworkTitle|NetworkComment|BlockComment)\s*:=\s*"(MLC_\w+)"')
_MLCID_DECL = re.compile(r"^\s*-\s*id:\s*(MLC_\w+)\s*$")
_RES_TEXT = re.compile(r"^\s*[\w-]+:\s*(.*)$")
_CALL = re.compile(r'^\s*("?)([A-Za-z_]\w*)\1\(\s*$')
_ARRAY_STAR = re.compile(r"^\s+\w+\s*:\s*Array\[\*\]")
_SECTION = re.compile(r"^\s*(VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_TEMP|VAR|END_VAR)\s*$")
_OPERAND_READ = re.compile(r'(?::=\s*|Contact\(\s*)"(\w+)"\.(\w+)')
_OPERAND_WRITE = re.compile(r'(?:=>\s*|Coil\(\s*)"(\w+)"\.(\w+)')


def check_safety_grammar(path: Path, text: str) -> list[Finding]:
    """Check one ``.s7dcl`` against the measured SD grammar rules.

    Parameters
    ----------
    path : Path
        File path, used in the findings.
    text : str
        File contents, BOM already stripped.

    Returns
    -------
    list[Finding]
        One finding per violation, in line order.
    """
    lines = text.splitlines()
    safety = bool(_SAFETY_HEADER.search(text))
    findings: list[Finding] = []
    findings += _title_lines(path, lines)
    findings += _declarations_with_values(path, lines)
    findings += _struct_in_safety(path, lines, safety)
    findings += _variable_arrays_outside_in_out(path, lines)
    findings += _unquoted_user_calls(path, lines)
    findings += _read_and_written(path, text, safety)
    return sorted(findings, key=lambda f: (f.line or 0, f.code))


def _title_lines(path: Path, lines: list[str]) -> list[Finding]:
    """S001 - a ``TITLE = ...`` line is refused wherever it is placed.

    Measured: ``Line number 8: Syntax Error : Syntax error '='`` with the line
    after ``DATA_BLOCK``; and, with the line first, ``Syntax error 'TITLE'
    expecting End Of File / SELECTION / LibPragma / TYPE / FUNCTION /
    FUNCTION_BLOCK / DATA_BLOCK / ORGANIZATION_BLOCK / NAMESPACE / FOLDERINFO /
    USING``. Quoting the text changes nothing. A block title is possible, but
    only as an MLCID: ``S7_BlockTitle := "MLC_B"`` resolved by the ``.s7res``.
    """
    return [
        Finding(path, i + 1, "S001", "ERROR",
                "TITLE line is refused by the importer; use S7_BlockTitle with an MLCID and a .s7res")
        for i, line in enumerate(lines) if _TITLE.match(line)
    ]


def _declarations_with_values(path: Path, lines: list[str]) -> list[Finding]:
    """S002 - a declaration cannot carry an initial value.

    Measured: ``Line number 9: Syntax Error : Syntax error ':=' expecting ;``
    on ``skgenMajor : DInt := 0;``. The admitted form declares the member bare
    inside ``VAR`` and assigns it after ``END_VAR`` - for scalars exactly as for
    array cells.
    """
    findings, in_var = [], False
    for i, line in enumerate(lines):
        section = _SECTION.match(line)
        if section:
            in_var = section.group(1) != "END_VAR"
            continue
        if in_var and _DECL_WITH_VALUE.match(line):
            findings.append(Finding(path, i + 1, "S002", "ERROR",
                                    "declaration carries an initial value; declare bare and assign after END_VAR"))
    return findings


def _struct_in_safety(path: Path, lines: list[str], safety: bool) -> list[Finding]:
    """S003 - no ``Struct`` in a fail-safe block interface.

    Measured: ``The type STRUCT is not permitted in the fail-safe block
    interface``. Nested members have to be flattened into names.
    """
    if not safety:
        return []
    return [
        Finding(path, i + 1, "S003", "ERROR", "Struct is not permitted in a fail-safe block interface")
        for i, line in enumerate(lines) if re.search(r":\s*Struct\b", line)
    ]


def _variable_arrays_outside_in_out(path: Path, lines: list[str]) -> list[Finding]:
    """S009 - ``Array[*]`` is only accepted as an in-out parameter.

    Measured indirectly: the form compiles and runs in ``VAR_IN_OUT``; TIA
    rejects a variable-length array elsewhere, as it does on a standard block.
    """
    findings, section = [], ""
    for i, line in enumerate(lines):
        match = _SECTION.match(line)
        if match:
            section = match.group(1)
            continue
        if _ARRAY_STAR.match(line) and section != "VAR_IN_OUT":
            findings.append(Finding(path, i + 1, "S009", "ERROR",
                                    f"Array[*] declared in {section or 'an unknown section'}; only VAR_IN_OUT accepts it"))
    return findings


def _unquoted_user_calls(path: Path, lines: list[str]) -> list[Finding]:
    """S007 - a user block is called with its name in quotes.

    Measured: calling ``FkStage(`` unquoted made the compiler resolve a phantom
    callee - ``The referenced block "FkStage_Callee" no longer exists or has the
    wrong version``, followed by one type error per parameter. The validated
    prototype quotes every user call and leaves system instructions bare.
    """
    findings = []
    for i, line in enumerate(lines):
        match = _CALL.match(line)
        if match and not match.group(1) and match.group(2) not in SYSTEM_INSTRUCTIONS:
            findings.append(Finding(path, i + 1, "S007", "WARNING",
                                    f'call to "{match.group(2)}" is unquoted; user blocks are quoted, system instructions are not'))
    return findings


def _read_and_written(path: Path, text: str, safety: bool) -> list[Finding]:
    """S008 - a standard DB member is read or written by the safety program, never both.

    Measured: ``Read access to parameter '"<DB>"."<member>"' is invalid because
    it is also used for write access in the safety program. Data from standard
    user program may only be read or written.`` The usual cause is an
    intermediate result parked in the interface block and read back later; it
    belongs in ``VAR_TEMP``.
    """
    if not safety:
        return []
    read = {f"{db}.{member}" for db, member in _OPERAND_READ.findall(text)}
    written = {f"{db}.{member}" for db, member in _OPERAND_WRITE.findall(text)}
    return [
        Finding(path, None, "S008", "ERROR",
                f'"{operand}" is both read and written by this safety block; keep intermediates in VAR_TEMP')
        for operand in sorted(read & written)
    ]


def check_s7res_pair(dcl_path: Path, dcl_text: str, res_text: str | None) -> list[Finding]:
    """S005/S006 - MLCID identifiers resolve, and the ``.s7res`` stays valid YAML.

    S005: every ``MLC_*`` referenced by the block must have a text in the
    companion file, and every text must be referenced - an unresolved
    identifier shows as ``MLC_N001`` in the editor, an orphan text is dead
    weight. S006: a text containing ``": "`` must be quoted, because the
    ``.s7res`` is YAML and a bare scalar with a colon-space opens a mapping;
    measured as a refused import.
    """
    used = set(_MLCID_USE.findall(dcl_text))
    if not used and res_text is None:
        return []
    findings: list[Finding] = []
    if res_text is None:
        return [Finding(dcl_path, None, "S005", "ERROR",
                        f"block references {len(used)} MLCID(s) but no .s7res file sits next to it")]
    declared = set()
    for i, line in enumerate(res_text.splitlines()):
        decl = _MLCID_DECL.match(line)
        if decl:
            declared.add(decl.group(1))
            continue
        value = _RES_TEXT.match(line)
        if value and ": " in value.group(1) and not value.group(1).startswith('"'):
            findings.append(Finding(dcl_path.with_suffix(".s7res"), i + 1, "S006", "ERROR",
                                    "unquoted YAML text contains a colon and a space; quote it or the import fails"))
    for missing in sorted(used - declared):
        findings.append(Finding(dcl_path, None, "S005", "ERROR", f"{missing} has no text in the .s7res"))
    for orphan in sorted(declared - used):
        findings.append(Finding(dcl_path.with_suffix(".s7res"), None, "S005", "WARNING",
                                f"{orphan} is declared but never referenced by the block"))
    return findings
