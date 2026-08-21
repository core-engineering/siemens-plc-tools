"""The differential over the five reference projects, when they are present.

The shipped fixtures are small and written to exercise specific shapes; the real
evidence is production SCL. Those projects are read-only siblings of this
repository and are absent on CI, so this test skips rather than fails when they
are not there.

A full corpus sweep found 45 diverging code units, resolving into six distinct
root causes -- every one of them a bug in the *old* text-path translator
(dropped ``CASE`` branches, comment text leaked or lost, a garbled
compound-assignment translation, a silently-dropped statement, and so on).
None was a case where the new AST-based path was wrong. Byte-identity between
the two paths was therefore dropped as this test's bar: it is not this test's
job to keep the old path's bugs alive. Instead this is a ratchet on the
*count* of diverging units, never on which ones -- no block name may live in
this public repository, so there is nothing to key an exception list on. The
count may only go down (as the AST path or the differential's scope changes);
if a corpus run ever finds more divergences than ``KNOWN_DIVERGENCES``, a
human must look at what grew before raising it. A larger count could be a
real regression in the AST path, or simply a new, not-yet-classified bug in
the old one -- either way it deserves a look, not a rubber stamp.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from plc_code.parser import parse_scl_file
from plc_code.parser.models import Block

#: Diverging code units measured across the full reference corpus, as of the
#: sweep that classified them into six root causes (see the module docstring).
#: This is a ratchet: it may only be lowered by a human who re-measures and
#: finds fewer, never raised to make a new failure disappear.
KNOWN_DIVERGENCES = 45


def _roots() -> list[Path]:
    """Corpus roots, from ``PLC_CORPUS_ROOTS`` (os.pathsep-separated).

    Read from the environment rather than written down: the directories are
    customer projects and this repository is public.

    Returns
    -------
    list[Path]
        One entry per non-empty segment of ``PLC_CORPUS_ROOTS``.
    """
    raw = os.environ.get("PLC_CORPUS_ROOTS", "")
    return [Path(part) for part in raw.split(os.pathsep) if part]


def _blocks() -> Iterator[tuple[Path, Block]]:
    """Every parsable, named block under the configured corpus roots.

    Yields
    ------
    tuple[Path, Block]
        The source file and the block it parsed to.
    """
    for root in _roots():
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.s7dcl")):
            try:
                block = parse_scl_file(path)
            except Exception:  # noqa: BLE001 - a corpus file that fails to parse is skipped, not fatal
                continue
            if block is not None and block.name:
                yield path, block


def test_the_corpus_has_no_more_than_the_known_divergences(
    differential_old: Callable[[Block], list[tuple[str, list[str]]]],
    differential_new: Callable[[Block], list[tuple[str, list[str]]]],
) -> None:
    """The count of diverging units must never exceed ``KNOWN_DIVERGENCES``.

    This does not assert the two paths agree -- they are known not to, in 45
    already-classified places, every one a bug in the old path. It only
    ratchets the *count*, so a new, unclassified divergence is caught without
    the test naming any block (a customer identifier) to tell the known ones
    apart from a new one. On failure, every diverging unit's label is printed
    (computed at run time from the corpus the environment names, never stored
    in this repository) so a human can see what changed.

    Parameters
    ----------
    differential_old : Callable[[Block], list[tuple[str, list[str]]]]
        The text-path translator fixture.
    differential_new : Callable[[Block], list[tuple[str, list[str]]]]
        The AST-path translator fixture.
    """
    seen = 0
    labels: list[str] = []
    for path, block in _blocks():
        seen += 1
        for (label, old_lines), (_, new_lines) in zip(
            differential_old(block), differential_new(block), strict=True
        ):
            if old_lines != new_lines:
                labels.append(f"{path}: {label}")
    if seen == 0:
        pytest.skip("PLC_CORPUS_ROOTS is unset or names no readable project")
    if len(labels) > KNOWN_DIVERGENCES:
        summary = "\n".join(labels)
        pytest.fail(
            f"{len(labels)} unit(s) diverged out of {seen} block(s) compared, "
            f"more than the known {KNOWN_DIVERGENCES}:\n{summary}"
        )
