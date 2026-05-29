"""API routes for the Cross-Reference Explorer."""

from fastapi import APIRouter, HTTPException, Query

from ..schemas_xref import (
    XrefAuditResponse,
    XrefAuditStatistics,
    XrefAuditViolation,
    XrefBlockGlobalsResponse,
    XrefDBListResponse,
    XrefDBSummary,
    XrefDBTreeResponse,
    XrefReference,
    XrefTreeNode,
    XrefVariableDetail,
    XrefVariableListResponse,
    XrefVariableSummary,
    XrefViolation,
)
from ..services import AnalysisService, get_service

router = APIRouter(prefix="/api/xref", tags=["xref"])


def _build_occurrence_refs(
    service: AnalysisService,
    var_refs: list,
    db_name: str,
    normalized_path: str,
) -> list[XrefReference]:
    """Build per-occurrence XrefReference list with resolved indices.

    Expands one VariableReference per block into multiple XrefReferences
    when the block accesses the variable at different array indices.
    """
    results: list[XrefReference] = []
    for ref in sorted(var_refs, key=lambda r: r.block_name):
        occurrences = service.find_all_reference_lines(
            ref.block_name,
            db_name,
            normalized_path,
        )
        if occurrences:
            for line, resolved_index in occurrences:
                results.append(
                    XrefReference(
                        block_name=ref.block_name,
                        line_number=line,
                        original_indices=[resolved_index] if resolved_index else [],
                    )
                )
        else:
            # Fallback: no match found in raw source
            results.append(
                XrefReference(
                    block_name=ref.block_name,
                    line_number=0,
                    original_indices=ref.original_indices,
                )
            )
    return results


@router.get("/variables", response_model=XrefVariableListResponse)
async def list_variables(
    db: str | None = Query(None, description="Filter by DB name"),
    search: str | None = Query(None, description="Search in full reference"),
    access: str | None = Query(None, description="Filter by access type: R, W, R/W"),
    has_violations: bool | None = Query(None, description="Only with violations"),
) -> XrefVariableListResponse:
    """List all global variables with cross-reference data."""
    service = get_service()
    crossref = service.get_crossref()
    audit = service.get_audit()

    # Index violations by full_reference for fast lookup
    violation_counts: dict[str, int] = {}
    for v in audit.violations:
        violation_counts[v.full_reference] = violation_counts.get(v.full_reference, 0) + 1

    variables: list[XrefVariableSummary] = []
    for var in crossref.variables.values():
        # Apply filters
        if db and var.db_name != db:
            continue
        if search and search.lower() not in var.full_reference.lower():
            continue
        if access and var.access_type != access:
            continue

        viol_count = violation_counts.get(var.full_reference, 0)
        if has_violations is True and viol_count == 0:
            continue
        if has_violations is False and viol_count > 0:
            continue

        variables.append(
            XrefVariableSummary(
                full_reference=var.full_reference,
                db_name=var.db_name,
                normalized_path=var.normalized_path,
                access_type=var.access_type,
                reader_count=len(var.readers),
                writer_count=len(var.writers),
                violation_count=viol_count,
            )
        )

    # Sort by full_reference
    variables.sort(key=lambda v: v.full_reference)
    db_names = sorted(crossref.by_db.keys())

    return XrefVariableListResponse(
        variables=variables,
        total=len(variables),
        dbs=db_names,
    )


@router.get("/variables/{full_reference:path}", response_model=XrefVariableDetail)
async def get_variable_detail(full_reference: str) -> XrefVariableDetail:
    """Get detailed cross-reference for a single variable."""
    service = get_service()
    crossref = service.get_crossref()

    var = crossref.variables.get(full_reference)
    if not var:
        raise HTTPException(status_code=404, detail=f"Variable not found: {full_reference}")

    violations = service.get_violations_for_variable(full_reference)

    # Resolve real line numbers and per-occurrence indices from raw source files
    writers = _build_occurrence_refs(service, var.writers, var.db_name, var.normalized_path)
    readers = _build_occurrence_refs(service, var.readers, var.db_name, var.normalized_path)

    return XrefVariableDetail(
        full_reference=var.full_reference,
        db_name=var.db_name,
        normalized_path=var.normalized_path,
        access_type=var.access_type,
        writers=writers,
        readers=readers,
        violations=[
            XrefViolation(
                rule_id=v.rule_id,
                severity=v.severity.value,
                message=v.message,
                details=v.details,
            )
            for v in violations
        ],
    )


@router.get("/dbs", response_model=XrefDBListResponse)
async def list_dbs() -> XrefDBListResponse:
    """List all data blocks with summary statistics."""
    service = get_service()
    crossref = service.get_crossref()
    audit = service.get_audit()

    # Index violations by db_name
    violation_counts: dict[str, int] = {}
    for v in audit.violations:
        violation_counts[v.db_name] = violation_counts.get(v.db_name, 0) + 1

    dbs: list[XrefDBSummary] = []
    for db_name, variables in sorted(crossref.by_db.items()):
        reader_blocks: set[str] = set()
        writer_blocks: set[str] = set()
        for var in variables:
            for r in var.readers:
                reader_blocks.add(r.block_name)
            for w in var.writers:
                writer_blocks.add(w.block_name)

        dbs.append(
            XrefDBSummary(
                name=db_name,
                variable_count=len(variables),
                reader_blocks=len(reader_blocks),
                writer_blocks=len(writer_blocks),
                violation_count=violation_counts.get(db_name, 0),
            )
        )

    return XrefDBListResponse(dbs=dbs)


@router.get("/dbs/{db_name}/tree", response_model=XrefDBTreeResponse)
async def get_db_tree(db_name: str) -> XrefDBTreeResponse:
    """Get hierarchical tree structure for a data block."""
    service = get_service()
    crossref = service.get_crossref()

    variables = crossref.by_db.get(db_name)
    if variables is None:
        raise HTTPException(status_code=404, detail=f"Data block not found: {db_name}")

    audit = service.get_audit()
    violation_refs = {v.full_reference for v in audit.violations}

    # Build tree from normalized paths
    tree = _build_tree(db_name, variables, violation_refs)

    return XrefDBTreeResponse(db_name=db_name, tree=tree)


def _build_tree(
    db_name: str,
    variables: list,
    violation_refs: set[str],
) -> XrefTreeNode:
    """Build a hierarchical tree from variable paths."""
    root = XrefTreeNode(name=db_name)

    for var in variables:
        parts = var.normalized_path.split(".")
        current = root

        for i, part in enumerate(parts):
            # Find or create child
            child = None
            for c in current.children:
                if c.name == part:
                    child = c
                    break

            if child is None:
                child = XrefTreeNode(name=part)
                current.children.append(child)

            if i == len(parts) - 1:
                # Leaf node
                child.is_leaf = True
                child.access_type = var.access_type
                child.reader_count = len(var.readers)
                child.writer_count = len(var.writers)
                child.full_reference = var.full_reference
                child.violation_count = 1 if var.full_reference in violation_refs else 0

            current = child

    # Sort children recursively
    _sort_tree(root)

    return root


def _sort_tree(node: XrefTreeNode) -> None:
    """Sort tree children alphabetically, leaves last."""
    node.children.sort(key=lambda c: (c.is_leaf, c.name))
    for child in node.children:
        _sort_tree(child)


@router.get("/audit", response_model=XrefAuditResponse)
async def get_audit(
    severity: str | None = Query(None, description="Filter: error, warning"),
    rule: str | None = Query(None, description="Filter by rule ID"),
    db: str | None = Query(None, description="Filter by DB name"),
) -> XrefAuditResponse:
    """Get audit results."""
    service = get_service()
    audit = service.get_audit()

    violations = audit.violations

    # Apply filters
    if severity:
        violations = [v for v in violations if v.severity.value == severity]
    if rule:
        violations = [v for v in violations if v.rule_id == rule]
    if db:
        violations = [v for v in violations if v.db_name == db]

    return XrefAuditResponse(
        violations=[
            XrefAuditViolation(
                rule_id=v.rule_id,
                severity=v.severity.value,
                db_name=v.db_name,
                variable_path=v.variable_path,
                full_reference=v.full_reference,
                message=v.message,
                details=v.details,
            )
            for v in violations
        ],
        statistics=XrefAuditStatistics(
            total_variables=audit.statistics.total_variables,
            total_violations=audit.statistics.total_violations,
            errors=audit.statistics.errors,
            warnings=audit.statistics.warnings,
            by_rule=audit.statistics.by_rule,
        ),
    )


@router.get("/blocks/{block_name}/globals", response_model=XrefBlockGlobalsResponse)
async def get_block_globals(block_name: str) -> XrefBlockGlobalsResponse:
    """Get all global variable accesses for a specific block."""
    service = get_service()
    deps = service.get_block_db_deps(block_name)

    if deps is None:
        raise HTTPException(status_code=404, detail=f"Block not found: {block_name}")

    reads = []
    writes = []
    for ref in deps.references:
        occurrences = service.find_all_reference_lines(
            deps.block_name,
            ref.db_name,
            ref.field_path,
        )
        if occurrences:
            for line, resolved_index in occurrences:
                xref = XrefReference(
                    block_name=deps.block_name,
                    line_number=line,
                    region_name=ref.full_reference,
                    original_indices=[resolved_index] if resolved_index else [],
                )
                if ref.is_write:
                    writes.append(xref)
                else:
                    reads.append(xref)
        else:
            xref = XrefReference(
                block_name=deps.block_name,
                line_number=0,
                region_name=ref.full_reference,
            )
            if ref.is_write:
                writes.append(xref)
            else:
                reads.append(xref)

    return XrefBlockGlobalsResponse(
        block_name=deps.block_name,
        reads=reads,
        writes=writes,
        dbs_read=sorted(deps.read_dbs),
        dbs_written=sorted(deps.write_dbs),
    )
