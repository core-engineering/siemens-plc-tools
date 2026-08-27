"""The ``hw:`` section of plc.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from plc_core.config.loader import find_config_file, load_yaml

from plc_hw.normalize import DEFAULT_VOLATILE


@dataclass(frozen=True)
class HwConfig:
    """Hardware-dump configuration.

    Attributes
    ----------
    dump_dir : str
        Dump root, relative to the project root.
    project : str | None
        TIA project file to open. ``None`` means attach to a running session.
    volatile_attributes : tuple[str, ...]
        Attribute names dropped from every dump.
    anonymize : bool
        Whether ``--record`` scrubs identities by default.
    """

    dump_dir: str = "deliverables/hardware-parameters"
    project: str | None = None
    volatile_attributes: tuple[str, ...] = field(default=DEFAULT_VOLATILE)
    anonymize: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HwConfig:
        """Build from the raw ``hw`` mapping.

        Parameters
        ----------
        data : dict[str, Any]
            The ``hw`` mapping from plc.yaml, or an empty dict.

        Returns
        -------
        HwConfig
            Config built from ``data``, falling back to defaults for every
            absent key.
        """
        paths = data.get("paths") or {}
        volatile = data.get("volatile_attributes")
        return cls(
            dump_dir=paths.get("dump", cls.dump_dir),
            project=data.get("project"),
            volatile_attributes=tuple(volatile) if volatile else DEFAULT_VOLATILE,
            anonymize=bool(data.get("anonymize", True)),
        )


def load_hw_config(start_path: Path | None = None) -> tuple[HwConfig, Path]:
    """Load the ``hw`` section and the project root.

    Parameters
    ----------
    start_path : Path | None
        Where to start searching upward for plc.yaml. Defaults to the cwd.

    Returns
    -------
    tuple[HwConfig, Path]
        The config and the directory holding plc.yaml (or ``start_path`` when
        there is none).
    """
    base = start_path or Path.cwd()
    config_file = find_config_file(base)
    if config_file is None:
        return HwConfig(), base
    raw = load_yaml(config_file) or {}
    return HwConfig.from_dict(raw.get("hw") or {}), config_file.parent


__all__ = ["HwConfig", "load_hw_config"]
