"""Tests for `plc code drawio` CLI subcommand."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from plc_code.cli import cli  # cli is an alias for code_group


def test_drawio_subcommand_exists():
    runner = CliRunner()
    result = runner.invoke(cli, ["drawio", "--help"])
    assert result.exit_code == 0
    assert "doc-map" in result.output.lower()


def test_drawio_subcommand_generates_file(tmp_path: Path, simple_xml_tags_dir: Path):
    runner = CliRunner()
    doc_map = tmp_path / "doc-map.yaml"
    doc_map.write_text(
        """
document:
  title: "Test"
  drawing_number: "TEST-001"
  revision: "1"
  drawn_by: "Tester"
  approved_by: "Reviewer"
  output_pdf: ["process+safety"]
chapters:
  - name: "Station"
    range: [10, 39]
    source_blocks: []
    pages:
      - num: 10
        title: "Station input"
        blocks: ["DI-001"]
        comments: ["Station input is the lamp test signal"]
""",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    result = runner.invoke(
        cli,
        [
            "drawio",
            "--doc-map",
            str(doc_map),
            "--xml-tags",
            str(simple_xml_tags_dir),
            "--out",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (out_dir / "station.drawio").exists()


def test_drawio_chapter_filter_generates_only_one_chapter(
    tmp_path: Path, simple_xml_tags_dir: Path, simple_scl_dir: Path
):
    import textwrap

    runner = CliRunner()
    doc_map = tmp_path / "doc-map.yaml"
    doc_map.write_text(
        textwrap.dedent("""\
        document:
          title: "Test"
          drawing_number: "T-1"
          revision: "1"
          drawn_by: "T"
          approved_by: "R"
          output_pdf: ["process+safety"]
        chapters:
          - name: "Station"
            range: [10, 39]
            source_blocks: []
            pages:
              - { num: 10, title: "Station input", blocks: ["DI-001"], comments: [] }
          - name: "PumpControl"
            range: [40, 59]
            source_blocks: []
            pages:
              - { num: 41, title: "Alarms", blocks: ["motorStartCmd"], comments: [] }
        fb_rendering:
          MotorStarter:
            style: pattern
            definition_page: 4
        """),
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    result = runner.invoke(
        cli,
        [
            "drawio",
            "--doc-map",
            str(doc_map),
            "--xml-tags",
            str(simple_xml_tags_dir),
            "--scl",
            str(simple_scl_dir),
            "--out",
            str(out_dir),
            "--chapter",
            "PumpControl",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (out_dir / "pumpcontrol.drawio").exists()
    assert not (out_dir / "station.drawio").exists()


def test_cli_drawio_with_scl_does_not_crash_on_unparseable_scl(
    tmp_path: Path, simple_xml_tags_dir: Path, simple_scl_dir: Path
):
    """When --scl is provided but the SCL cannot be parsed by the real parser
    (e.g. synthetic fixture content), the CLI must not crash and must still
    produce the output .drawio with the expected blocks.

    The old regex extractor would produce spurious wires in this scenario;
    the new analyzer-based extractor silently skips unparseable files and
    produces no edges — which is the correct behaviour.
    """
    import textwrap

    runner = CliRunner()
    doc_map = tmp_path / "doc-map.yaml"
    doc_map.write_text(
        textwrap.dedent("""\
        document: { title: "T", drawing_number: "T-1", revision: "1",
                    drawn_by: "T", approved_by: "R", output_pdf: ["process+safety"] }
        chapters:
          - name: "PumpControl"
            range: [40, 59]
            source_blocks: ["PumpControl.s7dcl"]
            pages:
              - { num: 41, title: "Alarms",
                  blocks: ["DI-001", "motorStartCmd"], comments: [] }
        fb_rendering:
          MotorStarter: { style: pattern, definition_page: 4 }
        """),
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    result = runner.invoke(
        cli,
        [
            "drawio",
            "--doc-map",
            str(doc_map),
            "--xml-tags",
            str(simple_xml_tags_dir),
            "--scl",
            str(simple_scl_dir),
            "--out",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    content = (out_dir / "pumpcontrol.drawio").read_text("utf-8")
    # Both blocks must appear as vertices regardless of dependency resolution
    assert 'id="di-001"' in content
    assert 'id="motorStartCmd"' in content


def test_drawio_emits_no_front_matter_when_fb_not_in_scl(
    tmp_path: Path, simple_xml_tags_dir: Path, simple_scl_dir: Path
):
    """With the new analyzer-based emission, front-matter.drawio is only written
    when the pattern FB's *definition* block is found in the parsed SCL.

    The synthetic simple_scl_dir only contains a PumpControl block that *uses*
    MotorStarter as an instance — it does not define it.  Therefore the
    CLI should emit a warning ("not found in SCL") and produce no
    front-matter.drawio, while still exiting cleanly.
    """
    import textwrap

    runner = CliRunner()
    doc_map = tmp_path / "doc-map.yaml"
    doc_map.write_text(
        textwrap.dedent("""\
        document:
          title: "Test"
          drawing_number: "T-1"
          revision: "1"
          drawn_by: "T"
          approved_by: "R"
          output_pdf: ["process+safety"]
        chapters:
          - name: "PumpControl"
            range: [40, 59]
            source_blocks: []
            pages:
              - { num: 41, title: "Alarms", blocks: ["motorStartCmd"], comments: [] }
        fb_rendering:
          MotorStarter:
            style: pattern
            definition_page: 4
        """),
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    result = runner.invoke(
        cli,
        [
            "drawio",
            "--doc-map",
            str(doc_map),
            "--xml-tags",
            str(simple_xml_tags_dir),
            "--scl",
            str(simple_scl_dir),
            "--out",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    # PumpControl chapter must still be produced.
    assert (out_dir / "pumpcontrol.drawio").exists()
    # No front-matter: the pattern FB definition was not found in the SCL.
    assert not (out_dir / "front-matter.drawio").exists()
