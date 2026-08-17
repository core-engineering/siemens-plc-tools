"""How `skip` / `skip_reason` survive YAML's own type coercion.

Two defects found reviewing the feature before it merged, both in the same two
lines, and both the same shape as a bug fixed in the SCL resource parser the same
day: trusting a YAML scalar to be the type the annotation claims.

- `skip_reason:` left empty is the natural way to skip without writing a note.
  YAML reads that as None, and `str(None)` rendered the literal `"None"` into the
  console, the Markdown report and the JUnit `message` attribute.
- `skip: "false"` — quoted by hand or by a generator that quotes every scalar —
  went through `bool("false")`, which is True. The scenario was skipped by a file
  that says not to.

The reporter test covers the JUnit `<skipped/>` element, which had no test at all
and is the output a CI dashboard actually consumes.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from plc_core.testing.models import Outcome, ScenarioResult, TestSuiteResult
from plc_core.testing.reporter import generate_junit_xml
from plc_core.testing.schema import parse_scenario


def _scenario(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "test_case.yaml"
    path.write_text(f'scenario:\n  name: "Case"\n{body}  steps: []\n', encoding="utf-8")
    return path


class TestSkipReasonCoercion:
    def test_an_empty_reason_is_empty_not_the_string_none(self, tmp_path: Path) -> None:
        scenario = parse_scenario(_scenario(tmp_path, "  skip: true\n  skip_reason:\n"))
        assert scenario.skip is True
        assert scenario.skip_reason == ""

    def test_an_absent_reason_is_empty(self, tmp_path: Path) -> None:
        scenario = parse_scenario(_scenario(tmp_path, "  skip: true\n"))
        assert scenario.skip_reason == ""

    def test_a_numeric_reason_becomes_its_text(self, tmp_path: Path) -> None:
        """A ticket number is a plausible reason and must not stay an int."""
        scenario = parse_scenario(_scenario(tmp_path, "  skip: true\n  skip_reason: 47\n"))
        assert scenario.skip_reason == "47"


class TestSkipFlagCoercion:
    def test_a_quoted_false_does_not_skip(self, tmp_path: Path) -> None:
        scenario = parse_scenario(_scenario(tmp_path, '  skip: "false"\n'))
        assert scenario.skip is False

    def test_the_other_spellings_yaml_treats_as_false(self, tmp_path: Path) -> None:
        for spelling in ('"no"', '"off"', '"0"', '""'):
            scenario = parse_scenario(_scenario(tmp_path, f"  skip: {spelling}\n"))
            assert scenario.skip is False, f"skip: {spelling} should not skip"

    def test_unquoted_false_still_does_not_skip(self, tmp_path: Path) -> None:
        assert parse_scenario(_scenario(tmp_path, "  skip: false\n")).skip is False

    def test_true_still_skips(self, tmp_path: Path) -> None:
        assert parse_scenario(_scenario(tmp_path, "  skip: true\n")).skip is True

    def test_a_quoted_true_still_skips(self, tmp_path: Path) -> None:
        assert parse_scenario(_scenario(tmp_path, '  skip: "true"\n')).skip is True


class TestJunitRendersSkips:
    def test_a_skipped_scenario_emits_a_skipped_element(self, tmp_path: Path) -> None:
        """CI dashboards read this; a skipped scenario has no steps to report."""
        suite = TestSuiteResult(
            scenario_results=[
                ScenarioResult(
                    name="Waiting on a recompile",
                    source_file=None,
                    outcome=Outcome.SKIPPED,
                    skip_reason="tag not on the target yet",
                )
            ]
        )
        out = tmp_path / "junit.xml"
        generate_junit_xml(suite, out)

        root = ElementTree.parse(out).getroot()
        skipped = root.findall(".//skipped")
        assert len(skipped) == 1
        assert skipped[0].get("message") == "tag not on the target yet"

    def test_a_skipped_scenario_counts_as_one_test_not_zero(self, tmp_path: Path) -> None:
        suite = TestSuiteResult(
            scenario_results=[ScenarioResult(name="Skipped", source_file=None, outcome=Outcome.SKIPPED)]
        )
        out = tmp_path / "junit.xml"
        generate_junit_xml(suite, out)

        testsuite = ElementTree.parse(out).getroot().find("testsuite")
        assert testsuite is not None
        assert testsuite.get("tests") == "1"
        assert testsuite.get("failures") == "0"

    def test_an_empty_reason_does_not_render_as_none(self, tmp_path: Path) -> None:
        suite = TestSuiteResult(
            scenario_results=[ScenarioResult(name="Skipped", source_file=None, outcome=Outcome.SKIPPED)]
        )
        out = tmp_path / "junit.xml"
        generate_junit_xml(suite, out)

        message = ElementTree.parse(out).getroot().findall(".//skipped")[0].get("message")
        assert message == "no reason given"
