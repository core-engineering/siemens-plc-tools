"""Tests for state machine detection and diagram generation."""

from pathlib import Path

import pytest

from plc_code.analyzer.state_machine import (
    StateConstant,
    StateMachine,
    StateTransition,
    extract_state_machine,
    generate_state_diagram,
    generate_state_diagram_block,
    has_state_machine,
)
from plc_code.parser.parser import parse_scl_file


class TestStateMachineDetection:
    """Tests for state machine detection."""

    def test_detect_simple_alarm_state_machine(self) -> None:
        """Test detection of ValveControl state machine."""
        fixture_path = Path(__file__).parent / "fixtures" / "ValveControl.s7dcl"
        if not fixture_path.exists():
            pytest.skip("ValveControl.s7dcl fixture not found")

        block = parse_scl_file(fixture_path)
        assert has_state_machine(block) is True

    def test_detect_acknowledged_alarm_state_machine(self) -> None:
        """Test detection of MotorStarter state machine."""
        fixture_path = Path(__file__).parent / "fixtures" / "MotorStarter.s7dcl"
        if not fixture_path.exists():
            pytest.skip("MotorStarter.s7dcl fixture not found")

        block = parse_scl_file(fixture_path)
        assert has_state_machine(block) is True

    def test_no_state_machine_in_function(self) -> None:
        """Test that functions don't have state machines (no static vars)."""
        fixture_path = Path(__file__).parent / "fixtures" / "CalculateVelocity.s7dcl"
        if not fixture_path.exists():
            pytest.skip("CalculateVelocity.s7dcl fixture not found")

        block = parse_scl_file(fixture_path)
        # Functions cannot have state machines (no static variables)
        assert has_state_machine(block) is False


class TestSCLExtraction:
    """Tests for SCL state machine extraction."""

    def test_extract_acknowledged_alarm(self) -> None:
        """Test extracting MotorStarter state machine."""
        fixture_path = Path(__file__).parent / "fixtures" / "MotorStarter.s7dcl"
        if not fixture_path.exists():
            pytest.skip("MotorStarter.s7dcl fixture not found")

        block = parse_scl_file(fixture_path)
        sm = extract_state_machine(block)

        assert sm is not None
        assert sm.block_name == "MotorStarter"
        assert sm.state_variable == "activeState"
        assert sm.language == "SCL"

        # Check states
        state_names = [s.name for s in sm.states]
        assert "STOPPED" in state_names
        assert "RUNNING" in state_names
        assert "FAULT" in state_names

        # Check initial state
        assert sm.initial_state == "STOPPED"

        # Check some transitions exist
        assert len(sm.transitions) > 0


class TestMermaidGeneration:
    """Tests for Mermaid state diagram generation."""

    def test_generate_simple_diagram(self) -> None:
        """Test generating a simple state diagram."""
        sm = StateMachine(
            state_variable="activeState",
            state_type="USInt",
            states=[
                StateConstant(name="NO_ALARM", value=0),
                StateConstant(name="ALARM", value=1),
            ],
            transitions=[
                StateTransition(
                    from_state="NO_ALARM",
                    to_state="ALARM",
                    condition="trigger",
                ),
                StateTransition(
                    from_state="ALARM",
                    to_state="NO_ALARM",
                    condition="NOT trigger",
                ),
            ],
            initial_state="NO_ALARM",
            block_name="TestBlock",
        )

        diagram = generate_state_diagram(sm)

        assert "stateDiagram-v2" in diagram
        assert "direction LR" in diagram
        assert "[*] --> NO_ALARM" in diagram
        assert "NO_ALARM --> ALARM : trigger" in diagram
        assert "ALARM --> NO_ALARM : NOT trigger" in diagram

    def test_generate_diagram_block(self) -> None:
        """Test generating a complete Mermaid code block."""
        sm = StateMachine(
            state_variable="activeState",
            state_type="USInt",
            states=[
                StateConstant(name="STATE_A", value=0),
                StateConstant(name="STATE_B", value=1),
            ],
            transitions=[
                StateTransition(
                    from_state="STATE_A",
                    to_state="STATE_B",
                    condition="go",
                ),
            ],
            initial_state="STATE_A",
        )

        block = generate_state_diagram_block(sm)

        assert block.startswith("```mermaid\n")
        assert block.endswith("\n```")
        assert "stateDiagram-v2" in block

    def test_diagram_without_initial_state(self) -> None:
        """Test generating diagram without initial state marker."""
        sm = StateMachine(
            state_variable="state",
            state_type="Int",
            states=[
                StateConstant(name="A", value=0),
                StateConstant(name="B", value=1),
            ],
            transitions=[],
            initial_state=None,
        )

        diagram = generate_state_diagram(sm, include_initial=True)

        # Should not have initial state transition since initial_state is None
        assert "[*] -->" not in diagram

    def test_diagram_direction(self) -> None:
        """Test setting diagram direction."""
        sm = StateMachine(
            state_variable="state",
            state_type="Int",
            states=[StateConstant(name="A", value=0)],
            transitions=[],
            initial_state="A",
        )

        lr_diagram = generate_state_diagram(sm, direction="LR")
        tb_diagram = generate_state_diagram(sm, direction="TB")

        assert "direction LR" in lr_diagram
        assert "direction TB" in tb_diagram


class TestStateMachineModels:
    """Tests for state machine model classes."""

    def test_state_machine_properties(self) -> None:
        """Test StateMachine convenience properties."""
        sm = StateMachine(
            state_variable="state",
            state_type="USInt",
            states=[
                StateConstant(name="A", value=0),
                StateConstant(name="B", value=1),
                StateConstant(name="C", value=2),
            ],
            transitions=[
                StateTransition(from_state="A", to_state="B", condition="x"),
                StateTransition(from_state="B", to_state="C", condition="y"),
            ],
        )

        assert sm.state_count == 3
        assert sm.transition_count == 2
        assert sm.state_names == ["A", "B", "C"]

    def test_get_transitions_from(self) -> None:
        """Test getting transitions from a specific state."""
        sm = StateMachine(
            state_variable="state",
            state_type="Int",
            states=[
                StateConstant(name="A", value=0),
                StateConstant(name="B", value=1),
                StateConstant(name="C", value=2),
            ],
            transitions=[
                StateTransition(from_state="A", to_state="B", condition="x"),
                StateTransition(from_state="A", to_state="C", condition="y"),
                StateTransition(from_state="B", to_state="C", condition="z"),
            ],
        )

        from_a = sm.get_transitions_from("A")
        assert len(from_a) == 2
        assert all(t.from_state == "A" for t in from_a)

        from_b = sm.get_transitions_from("B")
        assert len(from_b) == 1

        from_c = sm.get_transitions_from("C")
        assert len(from_c) == 0

    def test_get_transitions_to(self) -> None:
        """Test getting transitions to a specific state."""
        sm = StateMachine(
            state_variable="state",
            state_type="Int",
            states=[
                StateConstant(name="A", value=0),
                StateConstant(name="B", value=1),
                StateConstant(name="C", value=2),
            ],
            transitions=[
                StateTransition(from_state="A", to_state="B", condition="x"),
                StateTransition(from_state="A", to_state="C", condition="y"),
                StateTransition(from_state="B", to_state="C", condition="z"),
            ],
        )

        to_c = sm.get_transitions_to("C")
        assert len(to_c) == 2
        assert all(t.to_state == "C" for t in to_c)

        to_b = sm.get_transitions_to("B")
        assert len(to_b) == 1

        to_a = sm.get_transitions_to("A")
        assert len(to_a) == 0


class TestIntegrationWithRealFiles:
    """Integration tests using actual program-listings files."""

    def test_all_scl_state_machines_detected(self) -> None:
        """Test that all known SCL state machine blocks are detected."""
        base_path = Path(__file__).parent.parent / "program-listings"
        if not base_path.exists():
            pytest.skip("program-listings directory not found")

        # Known SCL state machine blocks
        known_state_machines = [
            "PLC blocks/100 - Process/150 - Utilities/151 - Alarms/ValveControl.s7dcl",
            "PLC blocks/100 - Process/150 - Utilities/151 - Alarms/MotorStarter.s7dcl",
            "PLC blocks/100 - Process/150 - Utilities/151 - Alarms/PumpControl.s7dcl",
            "PLC blocks/100 - Process/150 - Utilities/151 - Alarms/TankLevelMonitor.s7dcl",
            "PLC blocks/100 - Process/110 - Station/111 - ProcessController/MotionMode.s7dcl",
            "PLC blocks/100 - Process/110 - Station/111 - ProcessController/UserMode.s7dcl",
            "PLC blocks/100 - Process/130 - Unit/131 - Unit Process/ConveyorMode.s7dcl",
            "PLC blocks/100 - Process/120 - Physical Interfaces/MotorStarter.s7dcl",
        ]

        for rel_path in known_state_machines:
            file_path = base_path / rel_path
            if not file_path.exists():
                continue

            block = parse_scl_file(file_path)
            assert has_state_machine(block), f"Expected state machine in {rel_path}"

            sm = extract_state_machine(block)
            assert sm is not None, f"Failed to extract state machine from {rel_path}"
            assert sm.state_count >= 2, f"Expected at least 2 states in {rel_path}"
            assert sm.transition_count >= 1, f"Expected at least 1 transition in {rel_path}"

    def test_ladder_state_machines_detected(self) -> None:
        """Test that LADDER state machine blocks are detected."""
        base_path = Path(__file__).parent.parent / "program-listings"
        if not base_path.exists():
            pytest.skip("program-listings directory not found")

        # Known LADDER state machine blocks
        ladder_blocks = [
            "PLC blocks/200 - Safety/210 - Safety Station/"
            "211 - Safety Station Process/SafetySequenceNoSil.s7dcl",
            "PLC blocks/200 - Safety/230 - Safety Unit/UnitErsStateNoSil.s7dcl",
        ]

        for rel_path in ladder_blocks:
            file_path = base_path / rel_path
            if not file_path.exists():
                continue

            block = parse_scl_file(file_path)
            assert has_state_machine(block), f"Expected state machine in {rel_path}"

            sm = extract_state_machine(block)
            assert sm is not None, f"Failed to extract state machine from {rel_path}"
            assert sm.language == "LAD", f"Expected LAD language in {rel_path}"
