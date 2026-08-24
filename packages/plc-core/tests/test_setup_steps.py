"""A baseline made only of levels cannot reach a state machine that latches.

``setup.yaml`` writes values. Values are levels, and a retentive state machine
whose only exit is a timed button combination — press select while holding
unlock, release unlock, hold select past a delay, release — has no level that
reaches it. A suite whose baseline is levels-only therefore inherits whatever
such a machine was left in by whichever scenario ran last, and reports every
following verdict as if the baseline held.

``setup.steps`` closes that gap: the same step vocabulary a scenario uses,
running after both value phases. A step that fails aborts the setup rather
than letting the next scenario answer a question about a state nobody asked
for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plc_core.testing.schema import parse_setup


def _setup(tmp_path: Path, body: str) -> Path:
    (tmp_path / "setup.yaml").write_text(f"setup:\n{body}", encoding="utf-8")
    return tmp_path


class TestParsingSetupSteps:
    def test_steps_are_parsed_into_typed_steps(self, tmp_path: Path) -> None:
        setup = parse_setup(
            _setup(
                tmp_path,
                """  description: "baseline"
  values:
    Some.tag: false
  steps:
    - step: write
      description: "select + unlock"
      values:
        Lcp.input.armSelection.[1]: true
        Lcp.input.armUnlock: true
    - step: wait
      duration: 200ms
    - step: assert
      values:
        Arm.[1].status.userState: 0
""",
            )
        )

        assert setup is not None
        assert [s.step_type for s in setup.steps] == ["write", "wait", "assert"]
        assert setup.steps[0].description == "select + unlock"
        assert setup.steps[1].duration_s == pytest.approx(0.2)
        assert setup.steps[2].values == {"Arm.[1].status.userState": 0}

    def test_absent_steps_is_an_empty_list_not_none(self, tmp_path: Path) -> None:
        """The runner iterates this unconditionally; None would raise."""
        setup = parse_setup(_setup(tmp_path, "  values:\n    Some.tag: false\n"))

        assert setup is not None
        assert setup.steps == []

    def test_steps_may_be_the_only_content(self, tmp_path: Path) -> None:
        """A baseline can be all gesture and no level.

        The runner used to return early on an empty ``values``; a setup file
        carrying only steps would have been silently ignored.
        """
        setup = parse_setup(
            _setup(
                tmp_path,
                """  steps:
    - step: wait
      duration: 1s
""",
            )
        )

        assert setup is not None
        assert setup.values == {}
        assert len(setup.steps) == 1

    def test_an_unknown_step_type_is_rejected_at_parse_time(self, tmp_path: Path) -> None:
        """Not at run time, once per scenario, buried in setup output."""
        with pytest.raises(ValueError):
            parse_setup(_setup(tmp_path, "  steps:\n    - step: teleport\n"))
