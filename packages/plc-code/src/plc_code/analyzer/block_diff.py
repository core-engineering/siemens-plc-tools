"""Semantic diff between two SCL exports.

A text diff of ``.s7dcl`` files drowns the real change in TIA's re-exports:
reordered attributes, re-spaced expressions, shifted comments. This module
compares what the code *means*: blocks by name, interfaces variable by variable,
and bodies statement by statement on the shared statement AST -- so whitespace,
comments and formatting never show up as changes, and a one-line logic edit is
reported as exactly that, with its region and line.

Entry points: :func:`diff_blocks` for two parsed blocks, :func:`diff_trees` for
two directories (or single files), both returning a :class:`DiffReport`.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from plc_code.parser import parse_scl_file
from plc_code.parser.expressions import Expression
from plc_code.parser.lexer import Token
from plc_code.parser.models import Block, VariableDeclaration
from plc_code.parser.scl_text import expression_text
from plc_code.parser.statement_parser import parse_statements
from plc_code.parser.statements import Assignment as StmtAssignment
from plc_code.parser.statements import Call, Case, Exit, For, If, Return, Statement, While


@dataclass(frozen=True)
class InterfaceChange:
    """One variable added, removed or altered in a block's interface.

    Attributes
    ----------
    section : str
        The section it belongs to (``VAR_INPUT``, ``VAR``, ...).
    name : str
        The variable's name.
    kind : str
        ``added``, ``removed``, ``retyped``, ``redefaulted`` or ``reattributed``.
    old : str | None
        The old type (``retyped``) or default (``redefaulted``); ``None`` for
        ``added``.
    new : str | None
        The new type or default; ``None`` for ``removed``.
    """

    section: str
    name: str
    kind: str
    old: str | None = None
    new: str | None = None


@dataclass(frozen=True)
class StatementChange:
    """One statement added, removed or replaced in a region.

    Attributes
    ----------
    region : str
        The region (or ``"<network N>"``) the statement lives in.
    kind : str
        ``added`` or ``removed``. A replacement is one of each.
    line : int
        Source line in the export the statement belongs to (the new file for
        ``added``, the old one for ``removed``).
    text : str
        The statement's SCL, one line, whitespace-normalized.
    """

    region: str
    kind: str
    line: int
    text: str


@dataclass
class BlockDiff:
    """Everything that changed in one block.

    ``kind`` is ``added``, ``removed`` or ``changed``; an unchanged block never
    appears in a report. ``notes`` carries block-level changes that are neither
    interface nor statements (block type, return type, base UDT).
    """

    name: str
    kind: str
    notes: list[str] = field(default_factory=list)
    interface: list[InterfaceChange] = field(default_factory=list)
    statements: list[StatementChange] = field(default_factory=list)
    parse_problems: list[str] = field(default_factory=list)

    @property
    def is_change(self) -> bool:
        return bool(self.notes or self.interface or self.statements or self.kind != "changed")


@dataclass
class DiffReport:
    """The changed blocks of a comparison; empty means semantically identical."""

    blocks: list[BlockDiff] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.blocks or self.errors)


# -- block-level --------------------------------------------------------------------


def diff_blocks(old: Block, new: Block) -> BlockDiff:
    """What changed between two parses of the same block."""
    diff = BlockDiff(name=new.name or old.name, kind="changed")
    if old.block_type != new.block_type:
        diff.notes.append(f"block type: {old.block_type} -> {new.block_type}")
    if old.return_type != new.return_type:
        diff.notes.append(f"return type: {old.return_type} -> {new.return_type}")
    if old.base_type != new.base_type:
        diff.notes.append(f"base type: {old.base_type} -> {new.base_type}")
    diff.interface = _diff_interface(old, new, diff.parse_problems)
    diff.statements = _diff_bodies(old, new, diff.parse_problems)
    if not diff.is_change and _opaque(old) and _opaque(new) and _raw_differs(old, new):
        # A TYPE or DATA_BLOCK whose members the parser does not expose: the two
        # sides' text differs, so say "changed, not semantically compared" rather
        # than the false "identical".
        diff.notes.append(f"{new.block_type} content differs (members not semantically compared)")
    return diff


def _opaque(block: Block) -> bool:
    """A block the parser exposes no members or code for (an instance DB, some TYPEs)."""
    has_members = any(section.variables for section in block.variable_sections) or (
        block.user_data_type is not None and block.user_data_type.fields
    )
    has_code = any(network.tokens or network.regions or network.ladder_elements for network in block.networks)
    return block.block_type in ("TYPE", "DATA_BLOCK") and not has_members and not has_code


def _raw_differs(old: Block, new: Block) -> bool:
    try:
        old_text = Path(old.source_file).read_text(encoding="utf-8-sig")
        new_text = Path(new.source_file).read_text(encoding="utf-8-sig")
    except OSError:
        return False

    def normalize(text: str) -> list[str]:
        return [" ".join(line.split()) for line in text.splitlines() if line.strip()]

    return normalize(old_text) != normalize(new_text)


def _variables(block: Block, problems: list[str]) -> dict[tuple[str, str, int], VariableDeclaration]:
    """Every declared variable, keyed by section, name and occurrence.

    The occurrence index keeps duplicates apart: the parser flattens inline
    ``STRUCT`` members into their enclosing section, so two structs may both
    declare an ``x`` -- collapsing them would hide a retype of the shadowed one.
    """
    variables: dict[tuple[str, str, int], VariableDeclaration] = {}
    seen: dict[tuple[str, str], int] = {}
    for section in block.variable_sections:
        for variable in section.variables:
            occurrence = seen.get((section.section_type, variable.name), 0)
            seen[(section.section_type, variable.name)] = occurrence + 1
            variables[(section.section_type, variable.name, occurrence)] = variable
    if block.user_data_type is not None:
        for position, struct_field in enumerate(block.user_data_type.fields):
            variables[("TYPE", struct_field.name, 0)] = VariableDeclaration(
                name=struct_field.name, data_type=struct_field.data_type
            )
            del position
    return variables


def _diff_interface(old: Block, new: Block, problems: list[str]) -> list[InterfaceChange]:
    old_vars, new_vars = _variables(old, problems), _variables(new, problems)
    changes: list[InterfaceChange] = []
    for key in old_vars.keys() - new_vars.keys():
        changes.append(
            InterfaceChange(section=key[0], name=key[1], kind="removed", old=old_vars[key].data_type)
        )
    for key in new_vars.keys() - old_vars.keys():
        changes.append(
            InterfaceChange(section=key[0], name=key[1], kind="added", new=new_vars[key].data_type)
        )
    for key in old_vars.keys() & new_vars.keys():
        before, after = old_vars[key], new_vars[key]
        if before.data_type != after.data_type:
            changes.append(
                InterfaceChange(
                    section=key[0], name=key[1], kind="retyped", old=before.data_type, new=after.data_type
                )
            )
        if (before.default_value or None) != (after.default_value or None):
            changes.append(
                InterfaceChange(
                    section=key[0],
                    name=key[1],
                    kind="redefaulted",
                    old=before.default_value,
                    new=after.default_value,
                )
            )
        if before.attributes != after.attributes:
            # Retain, S7_Access, setpoint flags: semantic on the PLC even though
            # they never touch the body.
            changes.append(
                InterfaceChange(
                    section=key[0],
                    name=key[1],
                    kind="reattributed",
                    old=str(before.attributes),
                    new=str(after.attributes),
                )
            )
    changes.sort(key=lambda change: (change.section, change.name, change.kind))
    return changes


# -- body-level ---------------------------------------------------------------------


def _regions(block: Block) -> dict[tuple[int, str], list[Token]]:
    """Every SCL token slice of the block, keyed by position and name.

    The position keeps two same-named regions apart; the name alone is what the
    report shows.
    """
    slices: dict[tuple[int, str], list[Token]] = {}
    index = 0
    for position, network in enumerate(block.networks, 1):
        if network.tokens:
            slices[(index, f"<network {position}>")] = network.tokens
            index += 1
        for region in network.regions:
            if region.tokens:
                slices[(index, region.name)] = region.tokens
                index += 1
    return slices


def _ladder_units(block: Block) -> dict[tuple[int, str], list[_Comparable]]:
    """One unit per ladder element, per network: the parser's canonical element text.

    A rewired rung diffs as the changed elements; wire markers ride along, so a
    re-parallelled branch shows too.
    """
    units: dict[tuple[int, str], list[_Comparable]] = {}
    for position, network in enumerate(block.networks, 1):
        if network.ladder_elements:
            units[(position, f"<network {position} (LAD)>")] = [
                _Comparable(text=element, line=position) for element in network.ladder_elements
            ]
    return units


@dataclass(frozen=True)
class _Comparable:
    """One flattened line of a region: a simple statement or a control header.

    Compared by its normalized SCL text alone -- comments and layout are already
    gone (the lexer drops them from the statement slices), so two spellings of
    one line compare equal and any real edit compares different. The line number
    rides along for reporting and stays out of the comparison.
    """

    text: str
    line: int

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Comparable) and self.text == other.text

    def __hash__(self) -> int:
        return hash(self.text)


def _flatten(statements: list[Statement], out: list[_Comparable]) -> None:
    """One :class:`_Comparable` per simple statement and per control header/footer.

    Flattening (instead of comparing a whole ``IF`` as one unit) keeps the diff
    at the granularity a reader edits at: a change in one branch reports that
    branch's line, not the whole construct.
    """
    for statement in statements:
        if isinstance(statement, StmtAssignment):
            target = _expr(statement.target_expr, statement.target)
            value = _expr(statement.value_expr, statement.value)
            out.append(_line(statement.line, f"{target} := {value};"))
        elif isinstance(statement, Call):
            arguments = ", ".join(
                (f"{a.name} {'=>' if a.is_output else ':='} " if a.name else "")
                + _expr(a.value_expr, a.value)
                for a in statement.arguments
            )
            out.append(
                _line(statement.line, f"{_expr(statement.callee_expr, statement.callee)}({arguments});")
            )
        elif isinstance(statement, If):
            for position, branch in enumerate(statement.branches):
                keyword = "IF" if position == 0 else "ELSIF"
                line = branch.condition[0].line if branch.condition else statement.line
                out.append(_line(line, keyword, _expr(branch.condition_expr, branch.condition), "THEN"))
                _flatten(branch.body, out)
            if statement.else_body:
                out.append(_line(statement.line, "ELSE"))
                _flatten(statement.else_body, out)
            out.append(_line(statement.line, "END_IF;"))
        elif isinstance(statement, Case):
            out.append(
                _line(statement.line, "CASE", _expr(statement.selector_expr, statement.selector), "OF")
            )
            for arm in statement.branches:
                labels = ", ".join(
                    _expr(value, raw) for value, raw in zip(arm.values_expr, arm.values, strict=False)
                )
                out.append(_line(statement.line, f"{labels}:"))
                _flatten(arm.body, out)
            if statement.default:
                out.append(_line(statement.line, "ELSE"))
                _flatten(statement.default, out)
            out.append(_line(statement.line, "END_CASE;"))
        elif isinstance(statement, For):
            parts = [
                "FOR",
                _tokens_text(statement.variable),
                ":=",
                _expr(statement.start_expr, statement.start),
                "TO",
                _expr(statement.end_expr, statement.end),
            ]
            if statement.step or statement.step_expr:
                parts += ["BY", _expr(statement.step_expr, statement.step)]
            out.append(_line(statement.line, *parts, "DO"))
            _flatten(statement.body, out)
            out.append(_line(statement.line, "END_FOR;"))
        elif isinstance(statement, While):
            out.append(
                _line(statement.line, "WHILE", _expr(statement.condition_expr, statement.condition), "DO")
            )
            _flatten(statement.body, out)
            out.append(_line(statement.line, "END_WHILE;"))
        elif isinstance(statement, Return):
            out.append(_line(statement.line, "RETURN;"))
        elif isinstance(statement, Exit):
            out.append(_line(statement.line, "EXIT;"))
        else:  # a statement kind this differ does not know: compare it opaquely
            out.append(_line(statement.line, type(statement).__name__))


def _line(line: int, *parts: str) -> _Comparable:
    return _Comparable(text=" ".join(part for part in parts if part), line=line)


def _expr(expression: Expression | None, tokens: list[Token]) -> str:
    """The expression's canonical spelling; its raw tokens when it did not parse."""
    if expression is not None:
        return expression_text(expression)
    return _tokens_text(tokens)


def _tokens_text(tokens: list[Token]) -> str:
    return " ".join(token.value for token in tokens)


def _diff_bodies(old: Block, new: Block, problems: list[str]) -> list[StatementChange]:
    old_units = {key: _units(tokens, key[1], problems, "old") for key, tokens in _regions(old).items()}
    new_units = {key: _units(tokens, key[1], problems, "new") for key, tokens in _regions(new).items()}
    old_units.update(_ladder_units(old))
    new_units.update(_ladder_units(new))
    changes: list[StatementChange] = []
    for key in old_units.keys() - new_units.keys():
        for unit in old_units[key]:
            changes.append(StatementChange(region=key[1], kind="removed", line=unit.line, text=unit.text))
    for key in new_units.keys() - old_units.keys():
        for unit in new_units[key]:
            changes.append(StatementChange(region=key[1], kind="added", line=unit.line, text=unit.text))
    for key in old_units.keys() & new_units.keys():
        before, after = old_units[key], new_units[key]
        matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
        for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
            if tag == "equal":
                continue
            for unit in before[old_start:old_end]:
                changes.append(StatementChange(region=key[1], kind="removed", line=unit.line, text=unit.text))
            for unit in after[new_start:new_end]:
                changes.append(StatementChange(region=key[1], kind="added", line=unit.line, text=unit.text))
    changes.sort(key=lambda change: (change.region, change.line, change.kind))
    return changes


def _units(tokens: list[Token], region: str, problems: list[str], side: str) -> list[_Comparable]:
    result = parse_statements(tokens)
    for error in result.errors:
        problems.append(f"{side} {region}: {error.message}")
    units: list[_Comparable] = []
    _flatten(result.statements, units)
    return units


# -- tree-level ---------------------------------------------------------------------


def diff_trees(old_path: Path, new_path: Path) -> DiffReport:
    """Compare two exports: directories (recursively) or single ``.s7dcl`` files."""
    report = DiffReport()
    old_blocks = _load(old_path, report.errors, "old")
    new_blocks = _load(new_path, report.errors, "new")
    for name in sorted(old_blocks.keys() - new_blocks.keys()):
        report.blocks.append(BlockDiff(name=name, kind="removed"))
    for name in sorted(new_blocks.keys() - old_blocks.keys()):
        report.blocks.append(BlockDiff(name=name, kind="added"))
    for name in sorted(old_blocks.keys() & new_blocks.keys()):
        diff = diff_blocks(old_blocks[name], new_blocks[name])
        if diff.is_change:
            report.blocks.append(diff)
        elif diff.parse_problems:
            # Nothing readable changed, but part of the block was not compared:
            # that is an unreadable-input condition, not a difference.
            for problem in diff.parse_problems:
                report.errors.append(f"{name}: {problem}")
    return report


def _load(path: Path, errors: list[str], side: str) -> dict[str, Block]:
    files = [path] if path.is_file() else sorted(path.rglob("*.s7dcl"))
    blocks: dict[str, Block] = {}
    for file in files:
        try:
            block = parse_scl_file(file)
        except Exception as error:  # a broken export is reported, not fatal
            errors.append(f"{side}: {file.name}: {error}")
            continue
        if block is not None and block.name:
            if block.name in blocks:
                errors.append(f"{side}: block {block.name!r} appears in more than one file; last kept")
            blocks[block.name] = block
    return blocks
