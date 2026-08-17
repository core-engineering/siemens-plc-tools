"""Report where the boundary between safety and standard code is crossed.

Why this is not a quality rule: ``Rule.check(self, block)`` receives one block
and ``AnalysisRunner`` loops per block, so a check of the form "this standard
block calls a safety block" cannot reach the callee's flag. The repository's
existing shape for cross-block analysis is a pure function over the block list —
``build_db_crossref``, ``build_call_graph`` — and that is what this follows.

Codes use the prefix ``F``, Siemens' own vocabulary for fail-safe, so ``F001``
reads without a glossary to a PLC engineer.

Subjects are identified by **source path**, never by block name. Every safety UDT
in the observed corpus parsed with an empty name before the parser fix, and paths
are unique regardless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from plc_code.analyzer.graph_builder import build_call_graph
from plc_code.analyzer.quality.models import Severity, Violation
from plc_code.parser.models import Block

#: Block kinds that participate in call-boundary checks. A DATA_BLOCK is not called.
_CALLABLE_KINDS = {"FUNCTION_BLOCK", "FUNCTION"}


@dataclass
class SafetyReport:
    """What the boundary checks found.

    Attributes
    ----------
    violations : list[Violation]
        One entry per finding, in code order F001, F002, F003.
    safety_blocks : int
        Blocks and types declaring ``S7_Safety`` truthy.
    standard_blocks : int
        Everything else examined.
    """

    violations: list[Violation] = field(default_factory=list)
    safety_blocks: int = 0
    standard_blocks: int = 0


def is_safety_block(block: Block) -> bool:
    """Whether ``block`` declares itself safety.

    A ``TYPE`` carries the flag on its ``UserDataType``; every other kind carries
    it on ``attributes``. Resolving that here keeps the three checks from each
    repeating it.

    Parameters
    ----------
    block : Block
        Parsed block, of any kind.

    Returns
    -------
    bool
        True when the declaration is truthy, False otherwise.
    """
    if block.user_data_type is not None:
        return block.user_data_type.is_safety
    return block.attributes.is_safety


def build_safety_report(
    blocks: list[tuple[Path, Block]],
    safety_path_pattern: str = "safety",
) -> SafetyReport:
    """Check the safety boundary across a whole project.

    Parameters
    ----------
    blocks : list[tuple[Path, Block]]
        Source path and parsed block. Paths carry identity because a UDT's name
        may be absent.
    safety_path_pattern : str
        Case-insensitive substring marking a directory as safety territory. Matched
        against the block's containing directory, not the full path — a standard
        block's own name often contains "Safety" too. Used by F003 only.

    Returns
    -------
    SafetyReport
        The violations found (F001, F002, F003) plus safety/standard block counts.
    """
    report = SafetyReport()
    by_name: dict[str, Block] = {}
    paths: dict[str, Path] = {}

    for path, block in blocks:
        if is_safety_block(block):
            report.safety_blocks += 1
        else:
            report.standard_blocks += 1
        if block.name:
            by_name[block.name] = block
            paths[block.name] = path

    graph = build_call_graph([b for _p, b in blocks if b.name])

    for name, node in graph.nodes.items():
        caller = by_name.get(name)
        if caller is None or node.block_type not in _CALLABLE_KINDS:
            continue
        caller_safe = is_safety_block(caller)
        for callee_name in node.calls:
            callee = by_name.get(callee_name)
            if callee is None:
                continue
            callee_safe = is_safety_block(callee)
            if caller_safe == callee_safe:
                continue
            code = "F002" if caller_safe else "F001"
            direction = (
                "a safety block calls a standard block"
                if caller_safe
                else "a standard block calls a safety block"
            )
            report.violations.append(
                Violation(
                    rule_code=code,
                    message=f"{direction}: {name!r} calls {callee_name!r}",
                    severity=Severity.ERROR,
                    context=str(paths.get(name, "")),
                    suggestion=(
                        "Check whether this call is intended; a safety boundary "
                        "crossing is normally routed through a dedicated interface."
                    ),
                )
            )

    pattern = safety_path_pattern.lower()
    for path, block in blocks:
        in_safety_path = pattern in str(path.parent).lower()
        declared = is_safety_block(block)
        if in_safety_path == declared:
            continue
        if declared:
            message = f"declared S7_Safety but its path does not contain {safety_path_pattern!r}"
        else:
            message = f"path contains {safety_path_pattern!r} but the block does not declare S7_Safety"
        report.violations.append(
            Violation(
                rule_code="F003",
                message=message,
                severity=Severity.WARNING,
                context=str(path),
                suggestion=(
                    "Either mark the block with S7_Safety or move it out of the "
                    "safety tree; adjust code.quality.safety_path_pattern if this "
                    "project organises F code differently."
                ),
            )
        )

    report.violations.sort(key=lambda v: (v.rule_code, v.context))
    return report
