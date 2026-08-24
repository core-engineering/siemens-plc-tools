"""Port-based protocol classification."""

from __future__ import annotations

from plc_net.protocols import PORT_MAP, UNKNOWN, classify


def test_the_destination_port_wins_over_the_source_port() -> None:
    assert classify(49152, 4840).name == "OPC-UA"
    assert classify(4840, 49152).name == "OPC-UA"
    assert classify(102, 4840).name == "OPC-UA"  # destination checked first


def test_an_unmapped_port_pair_is_other() -> None:
    assert classify(49152, 49153) is UNKNOWN


def test_the_industrial_ports_are_mapped() -> None:
    assert PORT_MAP[102].name == "S7comm"
    assert PORT_MAP[6379].name == "Redis"
