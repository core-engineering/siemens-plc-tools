"""The differential over the five reference projects, when they are present.

The shipped fixtures are small and written to exercise specific shapes; the real
evidence is 649 blocks of production SCL. Those projects are read-only siblings
of this repository and are absent on CI, so this test skips rather than fails
when they are not there.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from plc_code.parser import parse_scl_file
from plc_code.parser.models import Block


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


def test_the_two_paths_agree_on_the_corpus(
    differential_old: Callable[[Block], list[tuple[str, list[str]]]],
    differential_new: Callable[[Block], list[tuple[str, list[str]]]],
) -> None:
    """The AST path and the text path must agree, byte for byte, on every real block.

    Walks the whole corpus rather than stopping at the first mismatch, so a single
    run reports every diverging unit instead of only the earliest one. A block's
    file path never lands in the repository: it only ever appears inside a pytest
    failure message, generated at run time from the corpus the environment names.

    Parameters
    ----------
    differential_old : Callable[[Block], list[tuple[str, list[str]]]]
        The text-path translator fixture.
    differential_new : Callable[[Block], list[tuple[str, list[str]]]]
        The AST-path translator fixture.
    """
    seen = 0
    divergences: list[tuple[Path, str, list[str], list[str]]] = []
    for path, block in _blocks():
        seen += 1
        for (label, old_lines), (_, new_lines) in zip(
            differential_old(block), differential_new(block), strict=True
        ):
            if old_lines != new_lines:
                divergences.append((path, label, old_lines, new_lines))
    if seen == 0:
        pytest.skip("PLC_CORPUS_ROOTS is unset or names no readable project")
    if divergences:
        summary = "\n".join(f"{path}: {label}" for path, label, _, _ in divergences)
        pytest.fail(f"{len(divergences)} unit(s) diverged out of {seen} block(s) compared:\n{summary}")
