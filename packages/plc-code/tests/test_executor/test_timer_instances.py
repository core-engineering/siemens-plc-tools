"""An FB instance call gets the ``clock=`` argument by declared type, not by name.

A timer's ``__call__`` takes the harness clock explicitly; a generated FB's
``__call__(**kwargs)`` would store a stray ``clock`` attribute without complaint.
The old rule keyed on substrings of the instance's name (``"timer"``, ``"ton"``,
``"tof"``, ``"tp"``): it missed 13 timer instances across five production projects
(``TypeError`` at the call) and matched FB instances that merely contained ``"tp"``.
"""

from __future__ import annotations

from pathlib import Path

from plc_code.executor.generator import generate_statements
from plc_code.executor.harness import create_harness
from plc_code.executor.timers import timer_class_name
from plc_code.parser.lexer import TokenType, tokenize
from plc_code.parser.statement_parser import parse_statements
from plc_code.parser.statements import Statement

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _statements(source: str) -> list[Statement]:
    tokens = [t for t in tokenize(source) if t.type is not TokenType.EOF]
    result = parse_statements(tokens)
    assert result.errors == [], result.errors
    return result.statements


class TestTheTypeTable:
    def test_every_iec_spelling_names_its_timer_class(self) -> None:
        assert timer_class_name("TON") == "TON_TIME"
        assert timer_class_name("TON_TIME") == "TON_TIME"
        assert timer_class_name("tof") == "TOF_TIME"
        assert timer_class_name("TP") == "TP_TIME"
        assert timer_class_name("Bool") is None
        assert timer_class_name(None) is None


class TestTheGeneratorDecision:
    def test_a_declared_timer_gets_the_clock_whatever_its_name(self) -> None:
        lines = generate_statements(
            _statements("#delay(IN := #a, PT := #t);"), timer_instances=frozenset({"delay"})
        )
        assert lines == ["self.delay(IN=self.a, PT=self.t, clock=self._runtime.clock)"]

    def test_a_non_timer_gets_no_clock_even_when_its_name_contains_a_marker(self) -> None:
        lines = generate_statements(_statements("#setpointCtrl(x := #a);"), timer_instances=frozenset())
        assert lines == ["self.setpointCtrl(x=self.a)"]

    def test_a_global_db_member_counts_as_a_timer_only_by_exact_type_name(self) -> None:
        assert generate_statements(_statements('"Db".TON(IN := #a, PT := #t);')) == [
            'self._runtime.global_dbs["Db"].TON(IN=self.a, PT=self.t, clock=self._runtime.clock)'
        ]
        assert generate_statements(_statements('"Db".stopTimer(IN := #a, PT := #t);')) == [
            'self._runtime.global_dbs["Db"].stopTimer(IN=self.a, PT=self.t)'
        ]


class TestEndToEnd:
    def test_timers_declared_as_ton_and_tp_time_run_on_the_harness_clock(self) -> None:
        harness = create_harness(FIXTURES / "TimerByType.s7dcl")
        harness.set_inputs(input=True)
        harness.execute()
        assert harness.get_output("output") is False
        assert harness.get_output("pulse") is True
        harness.advance_time_ms(120)
        harness.execute()
        assert harness.get_output("output") is True
        assert harness.get_output("pulse") is False
