"""Adapter: analyzer.logic_dependency chains → flat wire dict.

Walks each chain's tree and emits direct (parent → child) edges, filtered
to keep only those whose endpoints are on the current page.
"""

from __future__ import annotations

from typing import Protocol


class _NodeLike(Protocol):
    name: str
    children: list  # list[_NodeLike]


class _ChainLike(Protocol):
    root: _NodeLike


def extract_dependencies(
    *,
    chains: list[_ChainLike],
    page_block_ids: set[str],
) -> dict[str, list[str]]:
    """Flatten a list of dependency chains into a wire dict.

    Parameters
    ----------
    chains : list of DependencyChain-like objects
        Output of analyzer.logic_dependency.build_all_chains, or a stub
        with the same .root.children shape.
    page_block_ids : set of str
        Block IDs that will appear on the current page. Edges whose
        endpoints are not in this set are dropped.

    Returns
    -------
    dict[target_id -> list[source_id]]
        One entry per target with at least one on-page source.
    """
    deps: dict[str, list[str]] = {}
    for chain in chains:
        _walk(chain.root, page_block_ids, deps)
    return deps


def _walk(
    node: _NodeLike,
    page_ids: set[str],
    deps: dict[str, list[str]],
) -> None:
    """Recursively flatten direct edges, filtering by page membership."""
    if node.name in page_ids and node.children:
        for child in node.children:
            if child.name in page_ids:
                deps.setdefault(node.name, []).append(child.name)
            _walk(child, page_ids, deps)
    elif node.children:
        # node off-page, but children may still produce edges among themselves
        for child in node.children:
            _walk(child, page_ids, deps)
