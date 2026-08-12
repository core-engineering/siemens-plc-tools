"""Regression tests for SCL duration literals in executable expressions.

Background
----------
:class:`ExpressionTranslator` substitutes ``#name`` -> ``self.name`` for instance
variables.  A duration literal carries the same ``#``: ``T#0s``, ``T#150ms``,
``T#1h30m``.  Hex literals were already protected from that collision by
``_translate_hex_literals`` (``16#8201`` would otherwise become ``self.8201``);
duration literals were not, so ``#stateTimer := T#0s;`` transpiled to
``self.stateTimer = T self.0 s`` and the block failed to compile with
``ValueError: Failed to compile block: invalid syntax``.

Durations only reached the harness through *declaration defaults* (parsed by
``parse_time_literal``), never through statements, so any block that reset or
compared a timer inside its logic could not be executed at all.

These tests pin:
    * the supported duration prefixes (``T#``, ``TIME#``, ``LT#``, ``LTIME#``),
    * simple, sub-second and combined component forms,
    * durations in conditions as well as assignments,
    * hex literals still translating (the neighbouring ``#`` collision),
    * end-to-end harness execution of a timer that accumulates and resets.
"""

from plc_code.executor.codegen import ExpressionTranslator, StatementTranslator
from plc_code.executor.harness import FBTestHarness
from plc_code.parser.lexer import tokenize_with_newlines
from plc_code.parser.parser import SCLParser


def _harness(scl: str) -> FBTestHarness:
    """Compile inline SCL source into a test harness."""
    block = SCLParser(tokenize_with_newlines(scl)).parse()
    return FBTestHarness.from_block(block)


# A timer that accumulates an injected cycle time and resets on demand — the
# shape used by every state machine that measures a delay without an IEC timer.
_FB_TIMER = """
FUNCTION_BLOCK "AccumulatingTimer"
    VAR_INPUT
        cycleTime : Time;
        reset : Bool;
        limit : Time;
    END_VAR
    VAR_OUTPUT
        elapsed : Time;
        reached : Bool;
    END_VAR
    VAR
        stateTimer : Time;
    END_VAR
    { S7_Language := "SCL" }
    NETWORK
        REGION Logic
            IF #reset THEN
                #stateTimer := T#0s;
            ELSE
                #stateTimer := #stateTimer + #cycleTime;
            END_IF;

            #reached := #stateTimer >= #limit;
            #elapsed := #stateTimer;
        END_REGION
    END_NETWORK
END_FUNCTION_BLOCK
"""


class TestTimeLiteralTranslation:
    """Unit level: a duration literal becomes its value in seconds."""

    def test_zero_seconds(self) -> None:
        """``T#0s`` is the reset idiom and must not become a name expression."""
        assert ExpressionTranslator().translate("T#0s") == "0.0"

    def test_whole_seconds(self) -> None:
        """``T#5s`` translates to 5 seconds."""
        assert ExpressionTranslator().translate("T#5s") == "5.0"

    def test_milliseconds(self) -> None:
        """``T#150ms`` translates to 0.15 second."""
        assert ExpressionTranslator().translate("T#150ms") == "0.15"

    def test_minutes(self) -> None:
        """``T#10m`` translates to 600 seconds."""
        assert ExpressionTranslator().translate("T#10m") == "600.0"

    def test_combined_components(self) -> None:
        """``T#1h30m`` sums its components."""
        assert ExpressionTranslator().translate("T#1h30m") == "5400.0"

    def test_time_prefix_spelled_out(self) -> None:
        """``TIME#5s`` is the long spelling of the same literal."""
        assert ExpressionTranslator().translate("TIME#5s") == "5.0"

    def test_long_time_prefixes(self) -> None:
        """``LT#`` and ``LTIME#`` carry durations too."""
        assert ExpressionTranslator().translate("LT#5s") == "5.0"
        assert ExpressionTranslator().translate("LTIME#5s") == "5.0"

    def test_lowercase_prefix(self) -> None:
        """SCL keywords are case-insensitive."""
        assert ExpressionTranslator().translate("t#5s") == "5.0"

    def test_assignment_of_a_duration(self) -> None:
        """The reset assignment translates as a whole statement."""
        result = StatementTranslator().translate_assignment("#stateTimer := T#0s;")
        assert result == "self.stateTimer = 0.0"

    def test_duration_in_a_comparison(self) -> None:
        """A duration on the right of a comparison keeps the operator intact."""
        result = ExpressionTranslator().translate("#stateTimer >= T#5s")
        assert result == "self.stateTimer >= 5.0"

    def test_instance_variable_still_translates(self) -> None:
        """The neighbouring ``#`` substitution is unaffected."""
        assert ExpressionTranslator().translate("#stateTimer") == "self.stateTimer"

    def test_hex_literal_still_translates(self) -> None:
        """Hex literals keep their existing translation."""
        assert ExpressionTranslator().translate("16#8201") == "0x8201"

    def test_hex_and_duration_together(self) -> None:
        """Both literal kinds survive in one expression."""
        result = ExpressionTranslator().translate("#mode = 16#7 AND #timer >= T#5s")
        assert "0x7" in result
        assert "5.0" in result
        assert "self.mode" in result


class TestTimeLiteralHarness:
    """End-to-end: a block using durations in its logic must run."""

    def test_timer_accumulates_cycle_time(self) -> None:
        """Two one-second cycles accumulate to two seconds."""
        h = _harness(_FB_TIMER)
        h.set_inputs(cycleTime=1.0, reset=False, limit=5.0)
        h.execute()
        h.execute()
        assert h.get_output("elapsed") == 2.0

    def test_timer_resets_to_zero(self) -> None:
        """``T#0s`` actually zeroes the accumulator.

        Before the fix this raised ``ValueError: Failed to compile block``.
        """
        h = _harness(_FB_TIMER)
        h.set_inputs(cycleTime=1.0, reset=False, limit=5.0)
        h.execute()
        h.execute()
        h.set_inputs(cycleTime=1.0, reset=True, limit=5.0)
        h.execute()
        assert h.get_output("elapsed") == 0.0

    def test_limit_not_reached_before_time(self) -> None:
        """The comparison against a duration input holds below the limit."""
        h = _harness(_FB_TIMER)
        h.set_inputs(cycleTime=1.0, reset=False, limit=5.0)
        for _ in range(4):
            h.execute()
        assert h.get_output("reached") is False

    def test_limit_reached_on_time(self) -> None:
        """The comparison fires exactly when the accumulator reaches the limit."""
        h = _harness(_FB_TIMER)
        h.set_inputs(cycleTime=1.0, reset=False, limit=5.0)
        for _ in range(5):
            h.execute()
        assert h.get_output("reached") is True
