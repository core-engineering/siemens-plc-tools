"""Regression tests for SCL duration literals in executable expressions.

Background
----------
A duration literal carries a ``#``: ``T#0s``, ``T#150ms``, ``T#1h30m`` -- the same
character a local-variable reference (``#name``) uses. Unit-level pins of how the
renderer resolves that ambiguity for a bare expression
(``renderer._render_typed_literal``, e.g. ``T#0s`` -> ``0.0``) live in
``test_renderer_references.py``; this file keeps only the end-to-end regression a
duration literal inside real, running SCL logic once caused: durations only reached
the harness through *declaration defaults* before this was fixed, never through
statements, so any block that reset or compared a timer inside its own logic could
not be executed at all (``#stateTimer := T#0s;`` used to transpile to invalid Python
that failed to compile).

This test pins: end-to-end harness execution of a timer that accumulates an
injected cycle time and resets to zero on demand.
"""

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
