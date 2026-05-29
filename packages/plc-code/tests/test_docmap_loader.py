"""Tests for doc-map.yaml loader."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from plc_code.docmap.loader import load_docmap

FIXTURES = Path(__file__).parent / "fixtures" / "docmap"


def test_load_minimal_valid_yaml():
    dm = load_docmap(FIXTURES / "minimal.yaml")
    assert dm.document.title == "Example Plant — Control Logic"
    assert dm.chapters[0].name == "Station"
    assert dm.chapters[0].pages[0].num == 10
    assert dm.fb_rendering["MotorStarter"].style == "pattern"


def test_load_invalid_yaml_raises():
    with pytest.raises(ValidationError):
        load_docmap(FIXTURES / "invalid.yaml")


def test_load_nonexistent_file_raises():
    with pytest.raises(FileNotFoundError):
        load_docmap(FIXTURES / "does-not-exist.yaml")
