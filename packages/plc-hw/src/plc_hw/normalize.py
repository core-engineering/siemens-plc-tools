"""Canonicalisation rules.

Two dumps of an unchanged project must be byte-identical, so every value that
reaches YAML passes through here first.
"""

from __future__ import annotations

import enum
import re

#: Attributes dropped from every dump. Explicit by design.
#:
#: No suffix heuristic. A filter on ``*Time`` would swallow ``F_Monitoring_Time``
#: -- exactly the parameter this package exists to track. Dropping too much,
#: silently, is the worst failure available here.
DEFAULT_VOLATILE: tuple[str, ...] = ("InstallationDate",)

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\s.]+')
_ORDER_NUMBER = re.compile(r"^OrderNumber:")


def format_value(value: object) -> object:
    """Render one attribute value in a form that serialises identically every run.

    Parameters
    ----------
    value : object
        Raw value as the source returned it.

    Returns
    -------
    object
        A bool, int, float, str or None.
    """
    if isinstance(value, enum.Enum):
        return value.name
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return f"<{type(value).__name__}: {value}>"


def strip_order_number_prefix(value: str) -> str:
    """Drop the ``OrderNumber:`` prefix TIA puts on module type identifiers."""
    return _ORDER_NUMBER.sub("", value)


def slugify(name: str) -> str:
    """Turn a TIA name into a filesystem-safe fragment.

    The slug is a filename only. The node's ``name`` field keeps the verbatim TIA
    name, which stays the source of truth.

    Parameters
    ----------
    name : str
        TIA name.

    Returns
    -------
    str
        Safe fragment, never empty.
    """
    slug = _FORBIDDEN.sub("-", name).strip("-")
    return slug or "item"


def disambiguate(slugs: list[str]) -> list[str]:
    """Make a list of slugs unique under case-insensitive comparison.

    NTFS folds case, so two items differing only in case would write to the same
    file and one would silently vanish from the dump.

    Parameters
    ----------
    slugs : list[str]
        Slugs in their final order.

    Returns
    -------
    list[str]
        Same length and order; later duplicates get a ``-<n>`` suffix, bumped
        until the candidate is actually free -- a generated suffix can itself
        collide with a slug already present in the list.
    """
    seen: set[str] = set()
    out: list[str] = []
    for index, slug in enumerate(slugs, start=1):
        candidate = slug
        bump = index
        while candidate.lower() in seen:
            candidate = f"{slug}-{bump}"
            bump += 1
        seen.add(candidate.lower())
        out.append(candidate)
    return out
