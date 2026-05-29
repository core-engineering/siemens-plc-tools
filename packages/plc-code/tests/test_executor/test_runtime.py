"""Tests for PLC runtime simulation."""

from dataclasses import dataclass

import pytest

from plc_code.executor.runtime import MockClock, PLCRuntime


class TestMockClock:
    """Tests for the MockClock class."""

    def test_initial_time_is_zero(self) -> None:
        """Test that clock starts at zero."""
        clock = MockClock()
        assert clock.get_time() == 0.0

    def test_advance_time(self) -> None:
        """Test advancing the clock."""
        clock = MockClock()
        clock.advance(1.5)
        assert clock.get_time() == 1.5

    def test_advance_time_cumulative(self) -> None:
        """Test that advances are cumulative."""
        clock = MockClock()
        clock.advance(1.0)
        clock.advance(0.5)
        clock.advance(0.25)
        assert clock.get_time() == 1.75

    def test_advance_ms(self) -> None:
        """Test advancing by milliseconds."""
        clock = MockClock()
        clock.advance_ms(150)
        assert clock.get_time() == 0.150

    def test_advance_negative_raises(self) -> None:
        """Test that negative advance raises error."""
        clock = MockClock()
        with pytest.raises(ValueError, match="negative"):
            clock.advance(-1.0)

    def test_set_time(self) -> None:
        """Test setting absolute time."""
        clock = MockClock()
        clock.set_time(5.0)
        assert clock.get_time() == 5.0

    def test_set_time_negative_raises(self) -> None:
        """Test that negative set_time raises error."""
        clock = MockClock()
        with pytest.raises(ValueError, match="negative"):
            clock.set_time(-1.0)

    def test_reset(self) -> None:
        """Test resetting the clock."""
        clock = MockClock()
        clock.advance(10.0)
        clock.reset()
        assert clock.get_time() == 0.0


class TestPLCRuntime:
    """Tests for the PLCRuntime class."""

    def test_default_cycle_time(self) -> None:
        """Test default cycle time is 10ms."""
        runtime = PLCRuntime()
        assert runtime.cycle_time == 0.010

    def test_execute_cycle_advances_clock(self) -> None:
        """Test that execute_cycle advances the clock."""
        runtime = PLCRuntime()
        runtime.execute_cycle()
        assert runtime.clock.get_time() == 0.010

    def test_execute_cycle_increments_count(self) -> None:
        """Test that execute_cycle increments cycle count."""
        runtime = PLCRuntime()
        assert runtime.cycle_count == 0
        runtime.execute_cycle()
        assert runtime.cycle_count == 1
        runtime.execute_cycle()
        assert runtime.cycle_count == 2

    def test_custom_cycle_time(self) -> None:
        """Test custom cycle time."""
        runtime = PLCRuntime(cycle_time=0.020)  # 20ms
        runtime.execute_cycle()
        assert runtime.clock.get_time() == 0.020

    def test_current_time_property(self) -> None:
        """Test current_time property."""
        runtime = PLCRuntime()
        runtime.clock.advance(5.0)
        assert runtime.current_time == 5.0


class TestPLCRuntimeDataBlocks:
    """Tests for data block management."""

    def test_register_db(self) -> None:
        """Test registering a data block."""

        @dataclass
        class MockDB:
            value: int = 0

        runtime = PLCRuntime()
        db = MockDB(value=42)
        runtime.register_db("TestDB", db)

        assert "TestDB" in runtime.global_dbs
        assert runtime.global_dbs["TestDB"].value == 42

    def test_get_db(self) -> None:
        """Test getting a registered data block."""

        @dataclass
        class MockDB:
            value: int = 0

        runtime = PLCRuntime()
        db = MockDB(value=100)
        runtime.register_db("MyDB", db)

        retrieved = runtime.get_db("MyDB")
        assert retrieved.value == 100

    def test_get_db_not_found_raises(self) -> None:
        """Test that getting unregistered DB raises error."""
        runtime = PLCRuntime()
        with pytest.raises(KeyError, match="not registered"):
            runtime.get_db("NonExistent")


class TestPLCRuntimeFunctionBlocks:
    """Tests for function block instance management."""

    def test_register_fb(self) -> None:
        """Test registering a function block instance."""

        class MockFB:
            def __init__(self) -> None:
                self.value = 0

        runtime = PLCRuntime()
        fb = MockFB()
        runtime.register_fb("myInstance", fb)

        assert "myInstance" in runtime.fb_instances

    def test_get_fb(self) -> None:
        """Test getting a registered function block."""

        class MockFB:
            def __init__(self) -> None:
                self.value = 123

        runtime = PLCRuntime()
        fb = MockFB()
        runtime.register_fb("inst1", fb)

        retrieved = runtime.get_fb("inst1")
        assert retrieved.value == 123

    def test_get_fb_not_found_raises(self) -> None:
        """Test that getting unregistered FB raises error."""
        runtime = PLCRuntime()
        with pytest.raises(KeyError, match="not registered"):
            runtime.get_fb("NonExistent")

    def test_create_fb_instance(self) -> None:
        """Test creating a function block instance."""
        from dataclasses import dataclass, field

        @dataclass
        class MockFB:
            _runtime: PLCRuntime = field(repr=False)
            value: int = 0

        runtime = PLCRuntime()
        instance = runtime.create_fb_instance("myFB", MockFB)

        assert instance._runtime is runtime
        assert instance.value == 0
        assert runtime.fb_instances["myFB"] is instance


class TestPLCRuntimeReset:
    """Tests for runtime reset functionality."""

    def test_reset_clears_clock(self) -> None:
        """Test that reset clears the clock."""
        runtime = PLCRuntime()
        runtime.clock.advance(100.0)
        runtime.reset()
        assert runtime.clock.get_time() == 0.0

    def test_reset_clears_cycle_count(self) -> None:
        """Test that reset clears cycle count."""
        runtime = PLCRuntime()
        runtime.execute_cycle()
        runtime.execute_cycle()
        runtime.reset()
        assert runtime.cycle_count == 0

    def test_reset_clears_dbs(self) -> None:
        """Test that reset clears data blocks."""
        runtime = PLCRuntime()
        runtime.register_db("DB1", {"test": True})
        runtime.reset()
        assert len(runtime.global_dbs) == 0

    def test_reset_clears_fbs(self) -> None:
        """Test that reset clears function block instances."""
        runtime = PLCRuntime()
        runtime.register_fb("FB1", object())
        runtime.reset()
        assert len(runtime.fb_instances) == 0
