"""End-to-end integration: doc-map.yaml + XML tags → .drawio file."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from click.testing import CliRunner

from plc_code.cli import cli

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "drawio_e2e"


def test_full_pipeline_produces_valid_drawio(tmp_path: Path, simple_xml_tags_dir: Path) -> None:
    runner = CliRunner()
    out_dir = tmp_path / "out"
    result = runner.invoke(
        cli,
        [
            "drawio",
            "--doc-map",
            str(FIXTURE_DIR / "doc-map.yaml"),
            "--xml-tags",
            str(simple_xml_tags_dir),
            "--out",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output

    station = out_dir / "station.drawio"
    assert station.exists()

    tree = ET.parse(station)
    root = tree.getroot()
    assert root.tag == "mxfile"

    diagrams = root.findall("diagram")
    assert len(diagrams) == 2  # two pages in fixture

    content = station.read_text(encoding="utf-8")
    assert "DI" in content
    assert "Station-1 : Station input" in content
    assert "Station-2 : Steering" in content
    assert "Station mode is AUTO" in content
