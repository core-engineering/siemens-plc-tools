"""Pydantic schema for doc-map.yaml."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

_OutputPdf = Literal["process+safety", "process", "safety"]


class Document(BaseModel):
    """Document-level metadata, populated into every page's cartouche."""

    title: str
    drawing_number: str
    revision: str
    drawn_by: str
    approved_by: str
    output_pdf: list[_OutputPdf] = Field(default=["process+safety"])


class FbRendering(BaseModel):
    """Rendering mode for a function block type."""

    style: Literal["inline", "pattern", "black-box"] = "inline"
    definition_page: int | None = None
    expose: list[str] | None = None

    @model_validator(mode="after")
    def check_required_fields(self) -> FbRendering:
        if self.style == "pattern" and self.definition_page is None:
            raise ValueError("style='pattern' requires definition_page")
        if self.style == "black-box" and not self.expose:
            raise ValueError("style='black-box' requires expose=[...]")
        return self


class StructuredBlockRef(BaseModel):
    """Block reference with combination / annotation metadata."""

    id: str
    inputs: list[str] = Field(default_factory=list)
    combine: Literal["or", "and"] | None = None
    annotation: Literal["auto_acknowledge"] | None = None


BlockRef = str | StructuredBlockRef


class Page(BaseModel):
    """A single sheet in the document."""

    num: int = Field(ge=1, le=999)
    title: str
    blocks: list[BlockRef] = Field(default_factory=list)
    comments: list[str] = Field(default_factory=list)


class Chapter(BaseModel):
    """A logical chapter (group of consecutive sheets)."""

    name: str
    range: tuple[int, int]
    source_blocks: list[str] = Field(default_factory=list)
    pages: list[Page] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_range_order(self) -> Chapter:
        start, end = self.range
        if start > end:
            raise ValueError(f"Chapter range start ({start}) > end ({end})")
        return self


class DocMap(BaseModel):
    """Root model for doc-map.yaml."""

    document: Document
    fb_rendering: dict[str, FbRendering] = Field(default_factory=dict)
    chapters: list[Chapter] = Field(default_factory=list)
