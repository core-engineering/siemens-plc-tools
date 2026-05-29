"""Resolve doc-map block references against SCL and XML tag sources."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from plc_code.analyzer.logic_dependency.tag_parser import (
    IOTag,
    TagCollection,
    parse_tag_directory,
)
from plc_code.docmap.schema import BlockRef, StructuredBlockRef

# Regex that matches a leading project-prefix like "021-" at the start of a comment.
_PREFIX_RE = re.compile(r"^\d+-")

# Regex that matches a FUNCTION_BLOCK declaration and captures its name.
# TIA Portal SCL: FUNCTION_BLOCK "BlockName"  or  FUNCTION_BLOCK BlockName
_FB_BLOCK_RE = re.compile(r'^\s*FUNCTION_BLOCK\s+"?(\w+)"?', re.MULTILINE)

# Regex that matches a VAR-section instance declaration of either form:
#   instanceName : "FbType";        (quoted — user-defined FB in TIA Portal)
#   instanceName : _.FbType;        (library-reference — TIA Portal library FB)
# Named groups: ``quoted`` for the first form, ``libref`` for the second.
_VAR_INSTANCE_RE = re.compile(
    r'(?P<name>\w+)\s*:\s*(?:"(?P<quoted>\w+)"|_\.(?P<libref>\w+))\s*;',
    re.MULTILINE,
)


class ResolutionError(LookupError):
    """A doc-map block reference could not be resolved against any source."""


@dataclass
class ResolvedBlock:
    """A resolved block reference with its source kind and metadata.

    Attributes
    ----------
    identifier : str
        The original block identifier from the doc-map (preserved as-is).
    kind : {"instrument_tag", "fb_instance", "signal", "combined"}
        Source kind of the resolved block.
    children : list[ResolvedBlock]
        Child blocks for ``kind="combined"`` structured refs.
    combine : {"or", "and"} or None
        Logical combination operator for structured refs.
    annotation : str or None
        Optional annotation from the doc-map structured ref.
    metadata : dict[str, str]
        Tag metadata: ``plc_name``, ``address``, ``data_type``, ``comment``,
        ``category``, ``direction``.
    """

    identifier: str
    kind: Literal["instrument_tag", "fb_instance", "signal", "combined"]
    children: list[ResolvedBlock] = field(default_factory=list)
    combine: Literal["or", "and"] | None = None
    annotation: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


def _strip_project_prefix(comment: str) -> str:
    """Remove the leading numeric project prefix (e.g. ``021-``) from a comment.

    Examples
    --------
    >>> _strip_project_prefix("021-HS-6052A")
    'HS-6052A'
    >>> _strip_project_prefix("HS-6052A")
    'HS-6052A'
    """
    return _PREFIX_RE.sub("", comment, count=1)


def _match_instrument_tag(identifier: str, tag_collection: TagCollection) -> IOTag | None:
    """Find a tag whose comment matches *identifier* as an instrument tag.

    The comment stored in TIA Portal XML may have a leading project prefix
    (e.g. ``021-HS-102``).  The user's doc-map may write either the full
    form or the bare instrument tag (e.g. ``HS-102``).  This function strips
    the leading ``NNN-`` prefix from both sides before comparing, so both
    ``HS-102`` and ``021-HS-102`` resolve to the same tag.

    Parameters
    ----------
    identifier : str
        Identifier from the doc-map (e.g. ``HS-102`` or ``021-HS-102``).
    tag_collection : TagCollection
        Parsed tag collection to search.

    Returns
    -------
    IOTag or None
        The first matching tag, or ``None`` if not found.
    """
    needle = _strip_project_prefix(identifier).upper()
    for tag in tag_collection.tags:
        comment_stripped = _strip_project_prefix(tag.comment).upper()
        if comment_stripped == needle:
            return tag
    return None


def _tag_to_metadata(tag: IOTag) -> dict[str, str]:
    """Convert an :class:`IOTag` to the metadata dict stored in :class:`ResolvedBlock`."""
    return {
        "plc_name": tag.name,
        "address": tag.address,
        "data_type": tag.data_type,
        "comment": tag.comment,
        "category": tag.category,
        "direction": tag.direction,
    }


def _build_fb_index(scl_dir: Path) -> dict[str, tuple[str, str]]:
    """Walk all ``*.s7dcl`` files in *scl_dir* and build a FB instance index.

    The index maps each instance variable name to ``(fb_type, parent_block_name)``.
    Both declaration forms are captured:

    * ``instanceName : "FbType";``   — quoted type name (user-defined FB)
    * ``instanceName : _.FbType;``   — library-reference (TIA Portal library FB)

    Parameters
    ----------
    scl_dir : Path
        Directory to walk recursively for ``*.s7dcl`` files.

    Returns
    -------
    dict[str, tuple[str, str]]
        Mapping ``{instance_name: (fb_type, parent_block_name)}``.
    """
    index: dict[str, tuple[str, str]] = {}

    for scl_file in sorted(scl_dir.rglob("*.s7dcl")):
        text = scl_file.read_text(encoding="utf-8-sig")

        # Determine the containing FUNCTION_BLOCK name (use the file stem as fallback).
        block_match = _FB_BLOCK_RE.search(text)
        parent_block = block_match.group(1) if block_match else scl_file.stem

        # Extract only the VAR (static) section — avoid VAR_INPUT, VAR_OUTPUT, etc.
        # Strategy: find sections that start with bare "VAR" (not VAR_INPUT / VAR_OUTPUT …).
        # The regex r"\bVAR(?!_)\b(.*?)\bEND_VAR\b" matches \bVAR\b … END_VAR while
        # filtering out VAR_INPUT etc. by requiring VAR to NOT be followed by '_'.
        var_only_re = re.compile(r"\bVAR(?!_)\b(.*?)\bEND_VAR\b", re.DOTALL)
        for var_match in var_only_re.finditer(text):
            var_body = var_match.group(1)
            for inst_match in _VAR_INSTANCE_RE.finditer(var_body):
                instance_name = inst_match.group("name")
                # Whichever group matched (quoted form or library-ref form)
                fb_type = inst_match.group("quoted") or inst_match.group("libref")
                if fb_type is not None:
                    index[instance_name] = (fb_type, parent_block)

    return index


class Resolver:
    """Resolve doc-map block refs against XML tags and SCL sources.

    Lookup order for a plain identifier:

    1. Exact match on PLC tag name (e.g. ``DI_LCP_LAMP_TEST``).
    2. Instrument-tag match by stripping the leading ``NNN-`` prefix from
       tag comments and comparing case-insensitively (e.g. ``HS-102`` matches
       a tag whose comment is ``021-HS-102``).
    3. FB instance match against VAR-section declarations in SCL files
       (e.g. ``lcpHighTempAlarm`` declared as ``"MotorStarter"``).

    The user-supplied identifier is preserved in :attr:`ResolvedBlock.identifier`;
    the resolved PLC tag name is placed in ``metadata["plc_name"]`` for instrument
    tags, or ``metadata["fb_type"]`` / ``metadata["parent_block"]`` for FB instances.

    Parameters
    ----------
    xml_tags_dir : Path or None
        Directory containing TIA Portal V21 tag XML files (``*.xml``).
        Pass ``None`` to skip XML tag loading.
    scl_dir : Path or None
        Directory containing SCL source files (``*.s7dcl``) for FB instance
        resolution.  Pass ``None`` to skip SCL loading.
    """

    def __init__(
        self,
        xml_tags_dir: Path | None,
        scl_dir: Path | None,
    ) -> None:
        self._tag_collection: TagCollection | None = None
        if xml_tags_dir is not None:
            self._tag_collection = parse_tag_directory(xml_tags_dir)

        # FB instance index: {instance_name: (fb_type, parent_block_name)}
        self._fb_index: dict[str, tuple[str, str]] | None = None
        if scl_dir is not None:
            self._fb_index = _build_fb_index(scl_dir)

    def resolve(self, ref: BlockRef | dict[str, object]) -> ResolvedBlock:
        """Resolve a single block reference.

        Parameters
        ----------
        ref : str, StructuredBlockRef, or dict
            Reference from doc-map.yaml.  A plain ``str`` is resolved
            against XML tags.  A ``dict`` or ``StructuredBlockRef`` is
            treated as a structured ref whose ``inputs`` are resolved
            recursively.

        Returns
        -------
        ResolvedBlock
            The resolved block with its source kind.

        Raises
        ------
        ResolutionError
            If the reference does not match any known source.
        """
        if isinstance(ref, dict):
            ref = StructuredBlockRef.model_validate(ref)

        if isinstance(ref, str):
            return self._resolve_plain(ref)

        # Structured ref — recurse on inputs
        children = [self._resolve_plain(child) for child in ref.inputs]
        return ResolvedBlock(
            identifier=ref.id,
            kind="combined",
            children=children,
            combine=ref.combine,
            annotation=ref.annotation,
        )

    def _resolve_plain(self, identifier: str) -> ResolvedBlock:
        """Resolve a plain string identifier against loaded tag and SCL sources.

        Lookup order:

        1. Exact PLC tag name match (XML tags).
        2. Instrument-tag comment match, stripping leading ``NNN-`` prefix.
        3. FB instance match from SCL VAR-section declarations.

        Parameters
        ----------
        identifier : str
            Identifier from the doc-map (PLC name, instrument tag, or FB instance name).

        Returns
        -------
        ResolvedBlock

        Raises
        ------
        ResolutionError
            If no match is found in any loaded source.
        """
        if self._tag_collection is not None:
            # 1. Exact PLC tag name match
            tag = self._tag_collection.get(identifier)
            if tag is not None:
                return ResolvedBlock(
                    identifier=identifier,
                    kind="instrument_tag",
                    metadata=_tag_to_metadata(tag),
                )

            # 2. Instrument-tag comment match (strip leading NNN- prefix)
            tag = _match_instrument_tag(identifier, self._tag_collection)
            if tag is not None:
                return ResolvedBlock(
                    identifier=identifier,
                    kind="instrument_tag",
                    metadata=_tag_to_metadata(tag),
                )

        # 3. FB instance lookup (instrument tag lookups above take precedence)
        if self._fb_index is not None and identifier in self._fb_index:
            fb_type, parent = self._fb_index[identifier]
            return ResolvedBlock(
                identifier=identifier,
                kind="fb_instance",
                metadata={"fb_type": fb_type, "parent_block": parent},
            )

        raise ResolutionError(
            f"Cannot resolve block reference '{identifier}' " f"(not found in XML tags or SCL FB instances)"
        )
