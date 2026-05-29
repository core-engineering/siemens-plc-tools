"""Load and validate doc-map.yaml from disk."""

from __future__ import annotations

from pathlib import Path

import yaml

from plc_code.docmap.schema import DocMap


def load_docmap(path: Path | str) -> DocMap:
    """Load a doc-map.yaml file and validate it against the schema.

    Parameters
    ----------
    path : Path or str
        Path to the YAML file.

    Returns
    -------
    DocMap
        Validated doc-map model.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    pydantic.ValidationError
        If the YAML content does not match the schema.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"doc-map file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return DocMap.model_validate(raw)
