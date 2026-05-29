"""Tests for timer implementations."""

from plc_code.executor.runtime import MockClock
from plc_code.executor.timers import TOF_TIME, TON_TIME, TP_TIME


class TestTON_TIME:
    """Tests for the On-Delay Timer (TON)."""

    def test_initial_state(self) -> None:
        """Test initial timer state."""
        timer = TON_TIME()
        assert timer.IN is False
        assert timer.Q is False
        assert timer.ET == 0.0

    def test_output_off_when_input_false(self) -> None:
        """Test output stays off when input is false."""
        timer = TON_TIME()
        clock = MockClock()

        timer(IN=False, PT=1.0, clock=clock)
        assert timer.Q is False
        assert timer.ET == 0.0

    def test_output_off_before_preset_time(self) -> None:
        """Test output stays off before preset time elapsed."""
        timer = TON_TIME()
        clock = MockClock()

        # Enable timer
        timer(IN=True, PT=1.0, clock=clock)
        assert timer.Q is False
        assert timer.ET == 0.0

        # Advance less than preset time
        clock.advance(0.5)
        timer(IN=True, PT=1.0, clock=clock)
        assert timer.Q is False
        assert timer.ET == 0.5

    def test_output_on_after_preset_time(self) -> None:
        """Test output turns on after preset time."""
        timer = TON_TIME()
        clock = MockClock()

        # Enable timer
        timer(IN=True, PT=0.5, clock=clock)

        # Advance past preset time
        clock.advance(0.6)
        timer(IN=True, PT=0.5, clock=clock)

        assert timer.Q is True
        assert timer.ET >= 0.5

    def test_output_off_when_input_goes_false(self) -> None:
        """Test output turns off immediately when input goes false."""
        timer = TON_TIME()
        clock = MockClock()

        # Enable and trigger timer
        timer(IN=True, PT=0.5, clock=clock)
        clock.advance(0.6)
        timer(IN=True, PT=0.5, clock=clock)
        assert timer.Q is True

        # Disable timer
        timer(IN=False, PT=0.5, clock=clock)
        assert timer.Q is False
        assert timer.ET == 0.0

    def test_elapsed_time_resets_on_input_false(self) -> None:
        """Test elapsed time resets when input goes false."""
        timer = TON_TIME()
        clock = MockClock()

        timer(IN=True, PT=1.0, clock=clock)
        clock.advance(0.3)
        timer(IN=True, PT=1.0, clock=clock)
        assert timer.ET == 0.3

        # Input goes false
        timer(IN=False, PT=1.0, clock=clock)
        assert timer.ET == 0.0

    def test_retrigger_after_reset(self) -> None:
        """Test timer can be retriggered after reset."""
        timer = TON_TIME()
        clock = MockClock()

        # First cycle
        timer(IN=True, PT=0.5, clock=clock)
        clock.advance(0.6)
        timer(IN=True, PT=0.5, clock=clock)
        assert timer.Q is True

        # Reset
        timer(IN=False, PT=0.5, clock=clock)

        # Second cycle
        clock.advance(0.1)
        timer(IN=True, PT=0.5, clock=clock)
        assert timer.Q is False  # Just started

        clock.advance(0.6)
        timer(IN=True, PT=0.5, clock=clock)
        assert timer.Q is True

    def test_reset_method(self) -> None:
        """Test the reset method."""
        timer = TON_TIME()
        clock = MockClock()

        timer(IN=True, PT=0.5, clock=clock)
        clock.advance(0.6)
        timer(IN=True, PT=0.5, clock=clock)

        timer.reset()

        assert timer.IN is False
        assert timer.Q is False
        assert timer.ET == 0.0


class TestTOF_TIME:
    """Tests for the Off-Delay Timer (TOF)."""

    def test_initial_state(self) -> None:
        """Test initial timer state."""
        timer = TOF_TIME()
        assert timer.IN is False
        assert timer.Q is False
        assert timer.ET == 0.0

    def test_output_on_immediately_when_input_true(self) -> None:
        """Test output turns on immediately when input is true."""
        timer = TOF_TIME()
        clock = MockClock()

        timer(IN=True, PT=1.0, clock=clock)
        assert timer.Q is True
        assert timer.ET == 0.0

    def test_output_stays_on_during_delay(self) -> None:
        """Test output stays on during off-delay."""
        timer = TOF_TIME()
        clock = MockClock()

        # Enable
        timer(IN=True, PT=1.0, clock=clock)
        assert timer.Q is True

        # Disable - starts delay
        timer(IN=False, PT=1.0, clock=clock)
        assert timer.Q is True
        assert timer.ET == 0.0

        # During delay
        clock.advance(0.5)
        timer(IN=False, PT=1.0, clock=clock)
        assert timer.Q is True
        assert timer.ET == 0.5

    def test_output_off_after_delay(self) -> None:
        """Test output turns off after delay."""
        timer = TOF_TIME()
        clock = MockClock()

        # Enable then disable
        timer(IN=True, PT=0.5, clock=clock)
        timer(IN=False, PT=0.5, clock=clock)

        # Wait for delay
        clock.advance(0.6)
        timer(IN=False, PT=0.5, clock=clock)

        assert timer.Q is False
        assert timer.ET >= 0.5

    def test_delay_cancels_on_input_true(self) -> None:
        """Test delay is cancelled if input goes true."""
        timer = TOF_TIME()
        clock = MockClock()

        # Enable then disable
        timer(IN=True, PT=1.0, clock=clock)
        timer(IN=False, PT=1.0, clock=clock)

        # Partial delay
        clock.advance(0.3)
        timer(IN=False, PT=1.0, clock=clock)
        assert timer.Q is True

        # Re-enable cancels delay
        timer(IN=True, PT=1.0, clock=clock)
        assert timer.Q is True
        assert timer.ET == 0.0

    def test_reset_method(self) -> None:
        """Test the reset method."""
        timer = TOF_TIME()
        clock = MockClock()

        timer(IN=True, PT=1.0, clock=clock)
        timer(IN=False, PT=1.0, clock=clock)
        clock.advance(0.3)
        timer(IN=False, PT=1.0, clock=clock)

        timer.reset()

        assert timer.IN is False
        assert timer.Q is False
        assert timer.ET == 0.0


class TestTP_TIME:
    """Tests for the Pulse Timer (TP)."""

    def test_initial_state(self) -> None:
        """Test initial timer state."""
        timer = TP_TIME()
        assert timer.IN is False
        assert timer.Q is False
        assert timer.ET == 0.0

    def test_pulse_on_rising_edge(self) -> None:
        """Test pulse starts on rising edge."""
        timer = TP_TIME()
        clock = MockClock()

        # Rising edge starts pulse
        timer(IN=True, PT=1.0, clock=clock)
        assert timer.Q is True

    def test_pulse_duration(self) -> None:
        """Test pulse lasts for preset time."""
        timer = TP_TIME()
        clock = MockClock()

        # Start pulse
        timer(IN=True, PT=0.5, clock=clock)
        assert timer.Q is True

        # During pulse
        clock.advance(0.3)
        timer(IN=True, PT=0.5, clock=clock)
        assert timer.Q is True
        assert timer.ET == 0.3

        # Pulse ends
        clock.advance(0.3)
        timer(IN=True, PT=0.5, clock=clock)
        assert timer.Q is False

    def test_pulse_not_retriggerable_during_pulse(self) -> None:
        """Test pulse cannot be retriggered during pulse."""
        timer = TP_TIME()
        clock = MockClock()

        # Start pulse
        timer(IN=True, PT=1.0, clock=clock)
        assert timer.Q is True

        # Input goes false then true again during pulse
        timer(IN=False, PT=1.0, clock=clock)
        clock.advance(0.3)
        timer(IN=True, PT=1.0, clock=clock)

        # Pulse continues, not restarted
        assert timer.Q is True
        assert timer.ET == 0.3  # Same elapsed time

    def test_pulse_retriggerable_after_complete(self) -> None:
        """Test pulse can be retriggered after completion."""
        timer = TP_TIME()
        clock = MockClock()

        # First pulse
        timer(IN=True, PT=0.5, clock=clock)
        clock.advance(0.6)
        timer(IN=True, PT=0.5, clock=clock)
        assert timer.Q is False

        # Reset input
        timer(IN=False, PT=0.5, clock=clock)

        # Second pulse
        clock.advance(0.1)
        timer(IN=True, PT=0.5, clock=clock)
        assert timer.Q is True

    def test_pulse_ignores_input_changes(self) -> None:
        """Test pulse continues regardless of input."""
        timer = TP_TIME()
        clock = MockClock()

        # Start pulse
        timer(IN=True, PT=0.5, clock=clock)

        # Input goes false during pulse
        timer(IN=False, PT=0.5, clock=clock)
        assert timer.Q is True  # Pulse continues

        clock.advance(0.3)
        timer(IN=False, PT=0.5, clock=clock)
        assert timer.Q is True  # Still in pulse

    def test_reset_method(self) -> None:
        """Test the reset method."""
        timer = TP_TIME()
        clock = MockClock()

        timer(IN=True, PT=1.0, clock=clock)
        clock.advance(0.3)
        timer(IN=True, PT=1.0, clock=clock)

        timer.reset()

        assert timer.IN is False
        assert timer.Q is False
        assert timer.ET == 0.0


class TestTimerIntegration:
    """Integration tests for timers with PLCRuntime."""

    def test_ton_with_cycle_execution(self) -> None:
        """Test TON timer with cycle-based execution."""
        from plc_code.executor.runtime import PLCRuntime

        runtime = PLCRuntime(cycle_time=0.010)  # 10ms cycles
        timer = TON_TIME()

        # Run for 11 cycles (110ms) with PT=100ms
        # Using 11 cycles to account for floating point precision
        timer(IN=True, PT=0.100, clock=runtime.clock)
        assert timer.Q is False

        for _ in range(11):
            runtime.execute_cycle()
            timer(IN=True, PT=0.100, clock=runtime.clock)

        assert timer.Q is True  # 110ms > 100ms, so timer triggered

    def test_antibouncing_pattern(self) -> None:
        """Test the anti-bouncing pattern from the plan example."""
        from plc_code.executor.runtime import PLCRuntime

        runtime = PLCRuntime()
        timer = TON_TIME()
        delay = 0.150  # T#150ms

        # Input goes high
        timer(IN=True, PT=delay, clock=runtime.clock)
        output = timer.Q
        assert output is False

        # Advance 100ms - still bouncing
        runtime.clock.advance(0.100)
        timer(IN=True, PT=delay, clock=runtime.clock)
        output = timer.Q
        assert output is False

        # Input goes low before delay - false trigger
        timer(IN=False, PT=delay, clock=runtime.clock)
        output = timer.Q
        assert output is False

        # New press, wait full 160ms
        timer(IN=True, PT=delay, clock=runtime.clock)
        runtime.clock.advance(0.160)
        timer(IN=True, PT=delay, clock=runtime.clock)
        output = timer.Q
        assert output is True
