"""Compose render Sheets from doc-map pages + resolved blocks."""

from __future__ import annotations

import re

from plc_code.docmap.resolver import ResolvedBlock, Resolver
from plc_code.docmap.schema import Document, FbRendering, Page, StructuredBlockRef
from plc_code.drawio_generator.models import (
    Annotation,
    Block,
    Cartouche,
    Sheet,
)
from plc_code.drawio_generator.wiring import build_wires_for_sheet

# Layout constants — Draw.io A3 landscape ~1684×1190 px
_COL_LEFT_X = 100
_COL_CENTER_X = 500
_COL_RIGHT_X = 1200
_ROW_START_Y = 100
_ROW_HEIGHT = 100
_COMMENT_X = 100
_COMMENT_START_Y = 900

# ---------------------------------------------------------------------------
# Instrument-ID helpers
# ---------------------------------------------------------------------------

# Group 1: letters-only tag type (HS, TSH, …)
# Group 2: code starting with a digit (6020A, 55, 102, …) — ensures pure-alpha
#           strings like "WEIRD" fall through to the ('?', identifier) fallback.
_INSTRUMENT_ID_RE = re.compile(r"^([A-Za-z]+)[-_]?(\d\w*)$")

# Matches a leading project-prefix like "021-" (digits + dash)
_PROJECT_PREFIX_RE = re.compile(r"^\d+-")


def _parse_instrument_id(identifier: str) -> tuple[str, str]:
    """Split an instrument identifier into (tag_type, code).

    Examples
    --------
    >>> _parse_instrument_id("HS-6020A")
    ('HS', '6020A')
    >>> _parse_instrument_id("TSH-55")
    ('TSH', '55')
    >>> _parse_instrument_id("HS102")
    ('HS', '102')
    >>> _parse_instrument_id("WEIRD")
    ('?', 'WEIRD')
    """
    m = _INSTRUMENT_ID_RE.match(identifier)
    if m is None:
        return ("?", identifier)
    return (m.group(1), m.group(2))


def _short_description(metadata: dict[str, str]) -> str:
    """Return a human-readable description from resolved tag metadata.

    Preference order:
    1. ``metadata['comment']`` with any leading project-prefix (e.g. ``"021-"``)
       stripped → ``"021-HS-6070"`` becomes ``"HS-6070"``.
    2. ``metadata['data_type']`` (e.g. ``"Bool"``).
    3. Empty string.

    Parameters
    ----------
    metadata : dict[str, str]
        Snake-case metadata dict populated by the Resolver.

    Returns
    -------
    str
        Short description suitable for the Draw.io widget label.

    Examples
    --------
    >>> _short_description({"comment": "021-HS-6070", "data_type": "Bool"})
    'HS-6070'
    >>> _short_description({"comment": "HS-6070", "data_type": "Bool"})
    'HS-6070'
    >>> _short_description({"comment": "", "data_type": "Bool"})
    'Bool'
    >>> _short_description({})
    ''
    """
    comment = metadata.get("comment", "")
    if comment:
        return _PROJECT_PREFIX_RE.sub("", comment, count=1)
    return metadata.get("data_type", "")


def build_sheet(
    *,
    page: Page,
    document: Document,
    resolver: Resolver,
    chapter_name: str,
    section_number: int = 1,
    fb_rendering: dict[str, FbRendering] | None = None,
    dependencies: dict[str, list[str]] | None = None,
) -> Sheet:
    """Build a render Sheet from a doc-map Page.

    Parameters
    ----------
    page : Page
        The doc-map page descriptor.
    document : Document
        Document-level metadata (drawing_number, drawn_by, etc.).
    resolver : Resolver
        For resolving block references against XML tags / SCL.
    chapter_name : str
        e.g. "Chapter", used in the sheet title prefix.
    section_number : int, default 1
        The {N} in "{chapter}-{N} : {title}".
    fb_rendering : dict[str, FbRendering] or None, default None
        Mapping from FB type name to rendering spec.  If ``None``, all FB
        instances fall back to inline (placeholder) mode.
    dependencies : dict[str, list[str]] or None, default None
        Auto-wiring dependency graph: {target_id -> [source_id, ...]}.
        If provided, wires are generated connecting blocks on the sheet.
        If ``None``, no wires are generated.

    Returns
    -------
    Sheet
        Render IR ready for xml_writer.
    """
    cartouche = Cartouche(
        title=f"{chapter_name}-{section_number} : {page.title}",
        drawing_number=document.drawing_number,
        sheet_number=f"{page.num:03d}",
        drawn_by=document.drawn_by,
        approved_by=document.approved_by,
        revision=document.revision,
    )

    rendering = fb_rendering or {}
    blocks: list[Block] = []
    annotations: list[Annotation] = []

    for i, ref in enumerate(page.blocks):
        resolved = resolver.resolve(ref)
        block = _to_block(resolved, row_index=i, fb_rendering=rendering)
        blocks.append(block)
        # Emit auto_acknowledge annotation when the ref carries that annotation.
        if isinstance(ref, StructuredBlockRef) and ref.annotation == "auto_acknowledge":
            annotations.append(
                Annotation(
                    id=f"autoack_{i}",
                    kind="auto_acknowledge",
                    text=", ".join(ref.inputs) if ref.inputs else ref.id,
                    position=(_COL_CENTER_X + 250, _ROW_START_Y + i * _ROW_HEIGHT),
                )
            )

    annotations.extend(_place_annotations(page))

    wires = build_wires_for_sheet(blocks=blocks, dependencies=dependencies) if dependencies else []
    return Sheet(
        sheet_number=f"{page.num:03d}",
        cartouche=cartouche,
        blocks=blocks,
        wires=wires,
        annotations=annotations,
    )


def _to_block(
    resolved: ResolvedBlock,
    row_index: int,
    fb_rendering: dict[str, FbRendering] | None = None,
) -> Block:
    y = _ROW_START_Y + row_index * _ROW_HEIGHT
    if resolved.kind == "instrument_tag":
        tag_type, code = _parse_instrument_id(resolved.identifier)
        return Block(
            id=resolved.identifier.lower(),
            shape="instrument_tag_widget",
            position=(_COL_LEFT_X, y),
            size=(120, 60),
            properties={
                "tag_type": tag_type,
                "code": code,
                "description": _short_description(resolved.metadata),
            },
        )
    if resolved.kind == "fb_instance":
        return _fb_instance_block(resolved, y, fb_rendering or {})
    # Fallback for any kind not yet specifically rendered in MVP (combined, signal, …)
    return Block(
        id=resolved.identifier.lower(),
        shape="instrument_tag_widget",
        position=(_COL_LEFT_X, y),
        size=(120, 60),
        properties={
            "tag_type": "?",
            "code": resolved.identifier,
            "description": resolved.kind,
        },
    )


def _fb_instance_block(
    resolved: ResolvedBlock,
    y: int,
    fb_rendering: dict[str, FbRendering],
) -> Block:
    """Dispatch an FB instance to the appropriate shape based on its rendering spec."""
    fb_type = resolved.metadata.get("fb_type", "?")
    spec = fb_rendering.get(fb_type)
    style = spec.style if spec else "inline"

    if style == "pattern":
        # MVP-2A: MotorStarter has a dedicated compact shape; other FB types
        # fall back to a generic placeholder.
        shape = "acknowledge_alarm_compact" if fb_type in {"MotorStarter"} else "instrument_tag_widget"
        if shape == "acknowledge_alarm_compact":
            return Block(
                id=resolved.identifier,
                shape=shape,
                position=(_COL_CENTER_X, y),
                size=(200, 80),
                properties={"instance_name": resolved.identifier},
            )
        return Block(
            id=resolved.identifier,
            shape=shape,
            position=(_COL_CENTER_X, y),
            size=(120, 60),
            properties={"tag_type": "FB", "code": resolved.identifier, "description": fb_type},
        )

    if style == "black-box":
        exposed = ",".join(spec.expose or []) if spec else ""
        return Block(
            id=resolved.identifier,
            shape="black_box",
            position=(_COL_CENTER_X, y),
            size=(220, 100),
            properties={
                "fb_type": fb_type,
                "instance_name": resolved.identifier,
                "exposed_io": exposed,
            },
        )

    # inline mode — placeholder for Plan 2A (Plan 2B will expand inline logic)
    return Block(
        id=resolved.identifier,
        shape="instrument_tag_widget",
        position=(_COL_CENTER_X, y),
        size=(180, 60),
        properties={"tag_type": "FB", "code": fb_type, "description": resolved.identifier},
    )


def _place_annotations(page: Page) -> list[Annotation]:
    return [
        Annotation(
            id=f"note_{i}",
            kind="comment",
            text=text,
            position=(_COMMENT_X + i * 260, _COMMENT_START_Y),
        )
        for i, text in enumerate(page.comments)
    ]
