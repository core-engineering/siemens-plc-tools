"""MkDocs generation module.

This module provides tools to generate MkDocs-compatible markdown files
and navigation structures from extracted SCL documentation.
"""

from plc_code.generator.markdown import (
    MarkdownGenerator,
    MarkdownOptions,
    NavEntry,
    generate_block_markdown,
    generate_markdown,
    generate_nav_entry,
)

__all__ = [
    "MarkdownGenerator",
    "MarkdownOptions",
    "NavEntry",
    "generate_block_markdown",
    "generate_markdown",
    "generate_nav_entry",
]
