"""Pydantic schemas for the Cross-Reference Explorer API."""

from pydantic import BaseModel, Field


class XrefReference(BaseModel):
    """A single read or write reference to a global variable."""

    block_name: str
    line_number: int = 0
    region_name: str = ""
    original_indices: list[str] = Field(default_factory=list)


class XrefViolation(BaseModel):
    """An audit violation on a global variable."""

    rule_id: str
    severity: str  # error, warning, info
    message: str
    details: dict = Field(default_factory=dict)


class XrefVariableSummary(BaseModel):
    """Variable in list view (counts only)."""

    full_reference: str
    db_name: str
    normalized_path: str
    access_type: str  # R, W, R/W
    reader_count: int = 0
    writer_count: int = 0
    violation_count: int = 0


class XrefVariableDetail(BaseModel):
    """Variable with full readers, writers, and violations."""

    full_reference: str
    db_name: str
    normalized_path: str
    access_type: str
    writers: list[XrefReference] = Field(default_factory=list)
    readers: list[XrefReference] = Field(default_factory=list)
    violations: list[XrefViolation] = Field(default_factory=list)


class XrefVariableListResponse(BaseModel):
    """Response for variable list endpoint."""

    variables: list[XrefVariableSummary]
    total: int
    dbs: list[str] = Field(default_factory=list)


class XrefDBSummary(BaseModel):
    """Data block in list view."""

    name: str
    variable_count: int = 0
    reader_blocks: int = 0
    writer_blocks: int = 0
    violation_count: int = 0


class XrefTreeNode(BaseModel):
    """A node in the hierarchical DB tree."""

    name: str
    is_leaf: bool = False
    access_type: str = ""
    reader_count: int = 0
    writer_count: int = 0
    violation_count: int = 0
    full_reference: str = ""
    children: list["XrefTreeNode"] = Field(default_factory=list)


class XrefDBTreeResponse(BaseModel):
    """Response for DB tree endpoint."""

    db_name: str
    tree: XrefTreeNode


class XrefDBListResponse(BaseModel):
    """Response for DB list endpoint."""

    dbs: list[XrefDBSummary]


class XrefAuditStatistics(BaseModel):
    """Summary statistics from the audit."""

    total_variables: int = 0
    total_violations: int = 0
    errors: int = 0
    warnings: int = 0
    by_rule: dict[str, int] = Field(default_factory=dict)


class XrefAuditViolation(BaseModel):
    """A violation in the audit results list."""

    rule_id: str
    severity: str
    db_name: str
    variable_path: str
    full_reference: str
    message: str
    details: dict = Field(default_factory=dict)


class XrefAuditResponse(BaseModel):
    """Response for audit endpoint."""

    violations: list[XrefAuditViolation]
    statistics: XrefAuditStatistics


class XrefBlockGlobalsResponse(BaseModel):
    """Response for block-centric global access view."""

    block_name: str
    reads: list[XrefReference] = Field(default_factory=list)
    writes: list[XrefReference] = Field(default_factory=list)
    dbs_read: list[str] = Field(default_factory=list)
    dbs_written: list[str] = Field(default_factory=list)


# Enable forward reference resolution
XrefTreeNode.model_rebuild()
