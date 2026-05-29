"""Code metrics calculations for SCL blocks.

This module provides functions to calculate various code metrics
including cyclomatic complexity, nesting depth, and line counts.
"""

import re
from dataclasses import dataclass

from plc_code.parser.models import Block, Region

# Patterns to strip comments before analysis
BLOCK_COMMENT_PATTERN = re.compile(r"\(\*.*?\*\)", re.DOTALL)
LINE_COMMENT_PATTERN = re.compile(r"//[^\n]*")


def _strip_comments(content: str) -> str:
    """Remove comments from content before analysis.

    Parameters
    ----------
    content : str
        The content to process.

    Returns
    -------
    str
        Content with block comments (* *) and line comments (//) removed.
    """
    content = BLOCK_COMMENT_PATTERN.sub("", content)
    content = LINE_COMMENT_PATTERN.sub("", content)
    return content


@dataclass
class BlockMetrics:
    """Computed metrics for a block.

    Attributes
    ----------
    cyclomatic_complexity : int
        McCabe cyclomatic complexity (decision points + 1).
    max_nesting_depth : int
        Maximum nesting depth of control structures.
    total_lines : int
        Total number of lines in the block.
    code_lines : int
        Non-empty, non-comment lines.
    variable_count : int
        Total number of variables declared.
    input_count : int
        Number of input parameters.
    output_count : int
        Number of output parameters.
    network_count : int
        Number of NETWORK blocks.
    region_count : int
        Number of REGION blocks.
    """

    cyclomatic_complexity: int = 1
    max_nesting_depth: int = 0
    total_lines: int = 0
    code_lines: int = 0
    variable_count: int = 0
    input_count: int = 0
    output_count: int = 0
    network_count: int = 0
    region_count: int = 0


# Patterns for control flow statements that increase complexity
COMPLEXITY_PATTERNS = [
    re.compile(r"\bIF\b", re.IGNORECASE),
    re.compile(r"\bELSIF\b", re.IGNORECASE),
    re.compile(r"\bCASE\b", re.IGNORECASE),
    re.compile(r"\bFOR\b", re.IGNORECASE),
    re.compile(r"\bWHILE\b", re.IGNORECASE),
    re.compile(r"\bREPEAT\b", re.IGNORECASE),
]

# Patterns for logical operators in conditions (add to complexity)
LOGICAL_OPERATOR_PATTERNS = [
    re.compile(r"\bAND\b", re.IGNORECASE),
    re.compile(r"\bOR\b", re.IGNORECASE),
]

# Patterns for CASE branch labels (each adds complexity)
CASE_BRANCH_PATTERN = re.compile(r"^\s*(\d+|#\w+|'\w+')\s*:", re.MULTILINE)

# Patterns for nesting - opening constructs
NESTING_OPEN_PATTERNS = [
    re.compile(r"\bIF\b(?!\s*\bTHEN\b.*\bEND_IF\b)", re.IGNORECASE),  # IF not on single line
    re.compile(r"\bFOR\b", re.IGNORECASE),
    re.compile(r"\bWHILE\b", re.IGNORECASE),
    re.compile(r"\bREPEAT\b", re.IGNORECASE),
    re.compile(r"\bCASE\b", re.IGNORECASE),
]

# Patterns for nesting - closing constructs
NESTING_CLOSE_PATTERNS = [
    re.compile(r"\bEND_IF\b", re.IGNORECASE),
    re.compile(r"\bEND_FOR\b", re.IGNORECASE),
    re.compile(r"\bEND_WHILE\b", re.IGNORECASE),
    re.compile(r"\bUNTIL\b", re.IGNORECASE),
    re.compile(r"\bEND_CASE\b", re.IGNORECASE),
]


def calculate_cyclomatic_complexity(content: str) -> int:
    """Calculate McCabe cyclomatic complexity for code content.

    Complexity = 1 + number of decision points

    Decision points include:
    - IF statements
    - ELSIF branches
    - CASE branches
    - FOR loops
    - WHILE loops
    - REPEAT loops
    - AND/OR operators in conditions

    Comments are excluded from the calculation.

    Parameters
    ----------
    content : str
        The source code content.

    Returns
    -------
    int
        The cyclomatic complexity (minimum 1).
    """
    # Strip comments to avoid false positives
    content = _strip_comments(content)

    complexity = 1  # Base complexity

    for pattern in COMPLEXITY_PATTERNS:
        complexity += len(pattern.findall(content))

    # Count CASE branches (each label adds a decision point)
    # Subtract 1 for the CASE keyword itself which was already counted
    case_branches = len(CASE_BRANCH_PATTERN.findall(content))
    if case_branches > 0:
        complexity += case_branches - 1  # -1 because first branch doesn't add complexity

    # Count logical operators (AND, OR add decision points)
    for pattern in LOGICAL_OPERATOR_PATTERNS:
        complexity += len(pattern.findall(content))

    return complexity


def calculate_max_nesting_depth(content: str) -> int:
    """Calculate maximum nesting depth of control structures.

    Comments are excluded from the calculation.

    Parameters
    ----------
    content : str
        The source code content.

    Returns
    -------
    int
        Maximum nesting depth (0 if no control structures).
    """
    # Strip comments to avoid false positives
    content = _strip_comments(content)

    lines = content.split("\n")
    current_depth = 0
    max_depth = 0

    for line in lines:
        # Count opening constructs
        for pattern in NESTING_OPEN_PATTERNS:
            if pattern.search(line):
                current_depth += 1
                max_depth = max(max_depth, current_depth)

        # Count closing constructs
        for pattern in NESTING_CLOSE_PATTERNS:
            if pattern.search(line):
                current_depth = max(0, current_depth - 1)

    return max_depth


def count_code_lines(content: str) -> tuple[int, int]:
    """Count total and code-only lines.

    Parameters
    ----------
    content : str
        The source code content.

    Returns
    -------
    tuple[int, int]
        (total_lines, code_lines) where code_lines excludes
        empty lines and comment-only lines.
    """
    lines = content.split("\n")
    total = len(lines)
    code = 0

    for line in lines:
        stripped = line.strip()
        # Skip empty lines
        if not stripped:
            continue
        # Skip comment-only lines
        if stripped.startswith("//"):
            continue
        # Skip lines with only braces or parentheses
        if stripped in ("{", "}", "(", ")", "{}", "()"):
            continue
        code += 1

    return total, code


def count_regions(block: Block) -> int:
    """Count total REGION blocks in a block.

    Parameters
    ----------
    block : Block
        The parsed block.

    Returns
    -------
    int
        Total count of REGION blocks (including nested).
    """

    def count_nested(region: Region) -> int:
        count = 1
        for nested in region.nested_regions:
            count += count_nested(nested)
        return count

    total = 0
    for network in block.networks:
        for region in network.regions:
            total += count_nested(region)

    return total


def calculate_block_metrics(block: Block) -> BlockMetrics:
    """Calculate all metrics for a block.

    Parameters
    ----------
    block : Block
        The parsed block.

    Returns
    -------
    BlockMetrics
        Computed metrics.
    """
    # Gather all code content from networks
    all_content = []
    for network in block.networks:
        all_content.append(network.content)
        for region in network.regions:
            all_content.append(region.content)

    content = "\n".join(all_content)

    # Calculate metrics
    total_lines, code_lines = count_code_lines(content)

    return BlockMetrics(
        cyclomatic_complexity=calculate_cyclomatic_complexity(content),
        max_nesting_depth=calculate_max_nesting_depth(content),
        total_lines=total_lines,
        code_lines=code_lines,
        variable_count=sum(len(s.variables) for s in block.variable_sections),
        input_count=len(block.inputs),
        output_count=len(block.outputs),
        network_count=len(block.networks),
        region_count=count_regions(block),
    )


__all__ = [
    "BlockMetrics",
    "calculate_cyclomatic_complexity",
    "calculate_max_nesting_depth",
    "count_code_lines",
    "count_regions",
    "calculate_block_metrics",
]
