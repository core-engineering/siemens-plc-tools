"""Global variable audit functionality.

This module provides audit rules for detecting issues with global data block
variable usage patterns, such as multiple writers, write-only variables, etc.
"""

from dataclasses import dataclass, field
from enum import Enum

from plc_code.analyzer.db_crossref import DBCrossReference, GlobalVariable
from plc_code.analyzer.db_extractor import BlockDBDependencies


class AuditSeverity(Enum):
    """Severity levels for audit violations."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class AuditRule:
    """Definition of an audit rule.

    Attributes
    ----------
    rule_id : str
        Unique identifier (e.g., "GV001").
    name : str
        Short name for the rule.
    description : str
        Detailed description of what the rule checks.
    severity : AuditSeverity
        Default severity level.
    """

    rule_id: str
    name: str
    description: str
    severity: AuditSeverity


# Define all audit rules
AUDIT_RULES: dict[str, AuditRule] = {
    "GV001": AuditRule(
        rule_id="GV001",
        name="Multiple writers",
        description="Variable is written by more than one block. "
        "This can lead to race conditions and unpredictable behavior.",
        severity=AuditSeverity.ERROR,
    ),
    "GV002": AuditRule(
        rule_id="GV002",
        name="Multiple writes in single block",
        description="Variable is written multiple times within the same block. "
        "This may indicate redundant code or potential logic errors.",
        severity=AuditSeverity.WARNING,
    ),
    "GV003": AuditRule(
        rule_id="GV003",
        name="Write-only variable",
        description="Variable is written but never read. "
        "This may indicate dead code or incomplete implementation.",
        severity=AuditSeverity.WARNING,
    ),
    "GV004": AuditRule(
        rule_id="GV004",
        name="Read without write",
        description="Variable is read but never written in the analyzed code. "
        "This may be intentional (external input/parameter) or indicate missing initialization.",
        severity=AuditSeverity.WARNING,
    ),
}


@dataclass
class AuditViolation:
    """A single audit violation.

    Attributes
    ----------
    rule_id : str
        The rule that was violated.
    severity : AuditSeverity
        Severity of the violation.
    db_name : str
        Name of the data block.
    variable_path : str
        Normalized path of the variable.
    full_reference : str
        Full reference (e.g., '"ProcessData".arms[*].status.parked').
    message : str
        Human-readable description of the violation.
    details : dict
        Additional context (e.g., list of writers).
    """

    rule_id: str
    severity: AuditSeverity
    db_name: str
    variable_path: str
    full_reference: str
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class BlockWriteInfo:
    """Information about writes from a specific block.

    Attributes
    ----------
    block_name : str
        Name of the block.
    write_count : int
        Number of times this block writes to the variable.
    doc_path : str
        Path to the block's documentation.
    """

    block_name: str
    write_count: int = 1
    doc_path: str = ""


@dataclass
class AuditStatistics:
    """Statistics from the audit run.

    Attributes
    ----------
    total_variables : int
        Total number of variables analyzed.
    total_violations : int
        Total number of violations found.
    errors : int
        Number of error-level violations.
    warnings : int
        Number of warning-level violations.
    info : int
        Number of info-level violations.
    by_rule : dict[str, int]
        Violation count per rule.
    """

    total_variables: int = 0
    total_violations: int = 0
    errors: int = 0
    warnings: int = 0
    info: int = 0
    by_rule: dict[str, int] = field(default_factory=dict)


@dataclass
class AuditResult:
    """Complete result of an audit run.

    Attributes
    ----------
    violations : list[AuditViolation]
        All violations found.
    statistics : AuditStatistics
        Summary statistics.
    """

    violations: list[AuditViolation] = field(default_factory=list)
    statistics: AuditStatistics = field(default_factory=AuditStatistics)

    @property
    def has_errors(self) -> bool:
        """Check if there are any error-level violations."""
        return self.statistics.errors > 0

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warning-level violations."""
        return self.statistics.warnings > 0


class GlobalVariableAuditor:
    """Auditor for global variable usage patterns.

    Parameters
    ----------
    crossref : DBCrossReference
        The cross-reference data to audit.
    all_deps : list[BlockDBDependencies]
        Original dependencies for detailed analysis.
    """

    def __init__(
        self,
        crossref: DBCrossReference,
        all_deps: list[BlockDBDependencies],
    ) -> None:
        self.crossref = crossref
        self.all_deps = all_deps
        self._write_counts: dict[str, dict[str, BlockWriteInfo]] = {}
        self._build_write_counts()

    def _build_write_counts(self) -> None:
        """Build detailed write count information per variable per block."""
        for deps in self.all_deps:
            block_name = deps.block_name

            for ref in deps.references:
                if not ref.is_write:
                    continue

                # Use the full reference as key
                full_ref = ref.full_reference

                if full_ref not in self._write_counts:
                    self._write_counts[full_ref] = {}

                if block_name not in self._write_counts[full_ref]:
                    self._write_counts[full_ref][block_name] = BlockWriteInfo(
                        block_name=block_name,
                        write_count=1,
                    )
                else:
                    self._write_counts[full_ref][block_name].write_count += 1

    def run_audit(self) -> AuditResult:
        """Run all audit rules and return results.

        Returns
        -------
        AuditResult
            Complete audit results with violations and statistics.
        """
        result = AuditResult()
        result.statistics.total_variables = len(self.crossref.variables)

        # Run each rule
        for var in self.crossref.variables.values():
            self._check_gv001_multiple_writers(var, result)
            self._check_gv002_multiple_writes_in_block(var, result)
            self._check_gv003_write_only(var, result)
            self._check_gv004_read_without_write(var, result)

        # Calculate statistics
        self._calculate_statistics(result)

        return result

    def _check_gv001_multiple_writers(self, var: GlobalVariable, result: AuditResult) -> None:
        """Check GV001: Variable written by multiple blocks."""
        if len(var.writers) <= 1:
            return

        writer_names = sorted([w.block_name for w in var.writers])
        violation = AuditViolation(
            rule_id="GV001",
            severity=AuditSeverity.ERROR,
            db_name=var.db_name,
            variable_path=var.normalized_path,
            full_reference=var.full_reference,
            message=f"Written by {len(var.writers)} blocks: {', '.join(writer_names)}",
            details={
                "writers": [{"block": w.block_name, "doc_path": w.doc_path} for w in var.writers],
            },
        )
        result.violations.append(violation)

    def _check_gv002_multiple_writes_in_block(self, var: GlobalVariable, result: AuditResult) -> None:
        """Check GV002: Variable written multiple times in same block."""
        # Check write counts for this variable
        write_info = self._write_counts.get(var.full_reference, {})

        for block_name, info in write_info.items():
            if info.write_count > 1:
                violation = AuditViolation(
                    rule_id="GV002",
                    severity=AuditSeverity.WARNING,
                    db_name=var.db_name,
                    variable_path=var.normalized_path,
                    full_reference=var.full_reference,
                    message=f"Written {info.write_count} times in block '{block_name}'",
                    details={
                        "block": block_name,
                        "write_count": info.write_count,
                    },
                )
                result.violations.append(violation)

    def _check_gv003_write_only(self, var: GlobalVariable, result: AuditResult) -> None:
        """Check GV003: Variable written but never read."""
        if len(var.writers) > 0 and len(var.readers) == 0:
            writer_names = sorted([w.block_name for w in var.writers])
            violation = AuditViolation(
                rule_id="GV003",
                severity=AuditSeverity.WARNING,
                db_name=var.db_name,
                variable_path=var.normalized_path,
                full_reference=var.full_reference,
                message=f"Written by {', '.join(writer_names)} but never read",
                details={
                    "writers": writer_names,
                },
            )
            result.violations.append(violation)

    def _check_gv004_read_without_write(self, var: GlobalVariable, result: AuditResult) -> None:
        """Check GV004: Variable read but never written."""
        if len(var.readers) > 0 and len(var.writers) == 0:
            reader_names = sorted([r.block_name for r in var.readers])
            violation = AuditViolation(
                rule_id="GV004",
                severity=AuditSeverity.WARNING,
                db_name=var.db_name,
                variable_path=var.normalized_path,
                full_reference=var.full_reference,
                message=f"Read by {', '.join(reader_names)} but never written",
                details={
                    "readers": reader_names,
                },
            )
            result.violations.append(violation)

    def _calculate_statistics(self, result: AuditResult) -> None:
        """Calculate summary statistics from violations."""
        result.statistics.total_violations = len(result.violations)

        for violation in result.violations:
            # Count by severity
            if violation.severity == AuditSeverity.ERROR:
                result.statistics.errors += 1
            elif violation.severity == AuditSeverity.WARNING:
                result.statistics.warnings += 1
            else:
                result.statistics.info += 1

            # Count by rule
            rule_id = violation.rule_id
            result.statistics.by_rule[rule_id] = result.statistics.by_rule.get(rule_id, 0) + 1


def run_global_variable_audit(
    crossref: DBCrossReference,
    all_deps: list[BlockDBDependencies],
) -> AuditResult:
    """Run the global variable audit.

    Parameters
    ----------
    crossref : DBCrossReference
        The cross-reference data to audit.
    all_deps : list[BlockDBDependencies]
        Original dependencies for detailed analysis.

    Returns
    -------
    AuditResult
        Complete audit results.
    """
    auditor = GlobalVariableAuditor(crossref, all_deps)
    return auditor.run_audit()


def generate_audit_markdown(
    result: AuditResult,
    base_path: str = "",
) -> str:
    """Generate markdown report for audit results.

    Parameters
    ----------
    result : AuditResult
        The audit results to report.
    base_path : str
        Base path for computing relative links.

    Returns
    -------
    str
        Markdown content.
    """
    lines = [
        "# Global Variable Audit Report",
        "",
        "This report identifies potential issues with global variable usage patterns.",
        "",
    ]

    # Summary badge
    if result.has_errors:
        status = ":x: **Errors Found**"
    elif result.has_warnings:
        status = ":warning: **Warnings Found**"
    else:
        status = ":white_check_mark: **All Checks Passed**"

    lines.extend(
        [
            f"**Status:** {status}",
            "",
            "## Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Variables Analyzed | {result.statistics.total_variables} |",
            f"| Total Issues | {result.statistics.total_violations} |",
            f"| Errors | {result.statistics.errors} |",
            f"| Warnings | {result.statistics.warnings} |",
            f"| Info | {result.statistics.info} |",
            "",
        ]
    )

    # Issues by rule
    if result.statistics.by_rule:
        lines.extend(
            [
                "### Issues by Rule",
                "",
                "| Rule | Description | Count |",
                "|------|-------------|-------|",
            ]
        )

        for rule_id in sorted(result.statistics.by_rule.keys()):
            count = result.statistics.by_rule[rule_id]
            rule = AUDIT_RULES.get(rule_id)
            if rule:
                severity_icon = _get_severity_icon(rule.severity)
                lines.append(f"| {severity_icon} **{rule_id}** | {rule.name} | {count} |")

        lines.append("")

    # Detailed violations grouped by severity
    if result.violations:
        # Errors first
        error_violations = [v for v in result.violations if v.severity == AuditSeverity.ERROR]
        if error_violations:
            lines.extend(
                [
                    "## :x: Errors",
                    "",
                    "These issues should be fixed as they may cause runtime problems.",
                    "",
                ]
            )
            _add_violations_section(lines, error_violations, base_path)

        # Warnings
        warning_violations = [v for v in result.violations if v.severity == AuditSeverity.WARNING]
        if warning_violations:
            lines.extend(
                [
                    "## :warning: Warnings",
                    "",
                    "These issues should be reviewed and may indicate problems.",
                    "",
                ]
            )
            _add_violations_section(lines, warning_violations, base_path)

        # Info
        info_violations = [v for v in result.violations if v.severity == AuditSeverity.INFO]
        if info_violations:
            lines.extend(
                [
                    "## :information_source: Info",
                    "",
                    "These are informational findings that may be of interest.",
                    "",
                ]
            )
            _add_violations_section(lines, info_violations, base_path)

    # Rules reference
    lines.extend(
        [
            "## Audit Rules Reference",
            "",
            "| Rule | Severity | Description |",
            "|------|----------|-------------|",
        ]
    )

    for rule_id in sorted(AUDIT_RULES.keys()):
        rule = AUDIT_RULES[rule_id]
        severity_icon = _get_severity_icon(rule.severity)
        lines.append(
            f"| **{rule_id}** | {severity_icon} {rule.severity.value.capitalize()} | " f"{rule.description} |"
        )

    lines.append("")

    return "\n".join(lines)


def _get_severity_icon(severity: AuditSeverity) -> str:
    """Get the icon for a severity level."""
    if severity == AuditSeverity.ERROR:
        return ":x:"
    elif severity == AuditSeverity.WARNING:
        return ":warning:"
    else:
        return ":information_source:"


def _add_violations_section(
    lines: list[str],
    violations: list[AuditViolation],
    base_path: str,
) -> None:
    """Add a section of violations to the output.

    Groups violations by rule for better organization.
    """
    # Group by rule
    by_rule: dict[str, list[AuditViolation]] = {}
    for v in violations:
        if v.rule_id not in by_rule:
            by_rule[v.rule_id] = []
        by_rule[v.rule_id].append(v)

    for rule_id in sorted(by_rule.keys()):
        rule = AUDIT_RULES.get(rule_id)
        rule_violations = by_rule[rule_id]

        lines.append(f"### {rule_id}: {rule.name if rule else 'Unknown'}")
        lines.append("")

        if rule:
            lines.append(f"*{rule.description}*")
            lines.append("")

        # Table of violations
        lines.append("| Variable | Message |")
        lines.append("|----------|---------|")

        for v in sorted(rule_violations, key=lambda x: x.full_reference):
            # Create link to the variable in the cross-reference
            var_link = f"[`{v.full_reference}`]({v.db_name}.md#{_path_to_anchor(v.variable_path)})"
            lines.append(f"| {var_link} | {v.message} |")

        lines.append("")


def _path_to_anchor(normalized_path: str) -> str:
    """Convert a normalized path to an HTML anchor ID."""
    import re

    anchor = re.sub(r"\[\*\]", "", normalized_path)
    anchor = anchor.replace(".", "-").lower()
    anchor = anchor.strip("-")
    anchor = re.sub(r"-+", "-", anchor)
    return anchor
