"""The OPC UA binary dissector, fed hand-built frames through fake scapy packets.

No capture, no socket, no root: `OpcuaState.process_packet` receives objects that
answer `haslayer`/`[...]` the way scapy packets do, with the payload bytes built
here from the message layout documented at the top of `opcua.py`.
"""

from __future__ import annotations

import struct
from typing import Any

from plc_net.opcua import OpcuaState
from scapy.all import IP, TCP  # type: ignore[attr-defined]

OPC_PORT = 4840


def _frame(
    msg_type: bytes,
    *,
    service_id: int | None = None,
    encoding: int = 0x01,
    body: bytes = b"",
) -> bytes:
    """One complete OPC UA message: header, then a service NodeId when asked for."""
    payload = bytearray()
    payload += struct.pack("<III", 1, 1, 1)  # SecureChannelId, TokenId, SequenceNumber
    payload += struct.pack("<I", 7)  # RequestId
    if service_id is not None:
        if encoding == 0x01:  # FourByte NodeId: encoding, namespace, uint16 id
            payload += bytes([0x01, 0x00]) + struct.pack("<H", service_id)
        elif encoding == 0x00:  # TwoByte NodeId: encoding, byte id
            payload += bytes([0x00, service_id])
        else:  # Numeric NodeId: encoding, uint16 namespace, uint32 id
            payload += bytes([0x02, 0x00, 0x00]) + struct.pack("<I", service_id)
    payload += body
    size = 8 + len(payload)
    return msg_type + b"F" + struct.pack("<I", size) + bytes(payload)


class _Layer:
    def __init__(self, **attributes: Any) -> None:
        for name, value in attributes.items():
            setattr(self, name, value)


class _FakePacket:
    """Answers `haslayer(TCP/IP)` and `pkt[TCP]`/`pkt[IP]` like a captured packet."""

    def __init__(self, payload: bytes, sport: int, dport: int) -> None:
        self._layers = {
            TCP: _Layer(payload=payload, sport=sport, dport=dport),
            IP: _Layer(src="10.0.0.1", dst="10.0.0.2"),
        }

    def haslayer(self, layer: Any) -> bool:
        return layer in self._layers

    def __getitem__(self, layer: Any) -> Any:
        return self._layers[layer]


def _feed(state: OpcuaState, payload: bytes, *, to_server: bool = True) -> None:
    sport, dport = (49152, OPC_PORT) if to_server else (OPC_PORT, 49152)
    state.process_packet(_FakePacket(payload, sport, dport))


class TestMessageTypes:
    def test_handshake_channel_and_error_frames_are_counted(self) -> None:
        state = OpcuaState()
        for msg_type in (b"HEL", b"ACK", b"OPN", b"CLO", b"ERR"):
            _feed(state, _frame(msg_type))
        assert state.handshake_count == 2
        assert state.channel_open_count == 1
        assert state.channel_close_count == 1
        assert state.error_count == 1
        assert state.total_opcua_packets == 5

    def test_an_unknown_message_type_is_counted_not_crashed_on(self) -> None:
        state = OpcuaState()
        _feed(state, _frame(b"XXX"))
        assert state.unknown_msg_count == 1


class TestServiceClassification:
    def test_a_read_request_to_the_server_port_counts_as_a_request(self) -> None:
        state = OpcuaState()
        _feed(state, _frame(b"MSG", service_id=631), to_server=True)
        stats = state.service_stats["Read"]
        assert (stats.requests, stats.responses) == (1, 0)
        assert stats.request_bytes == len(_frame(b"MSG", service_id=631))

    def test_a_read_response_from_the_server_port_counts_as_a_response(self) -> None:
        state = OpcuaState()
        _feed(state, _frame(b"MSG", service_id=634), to_server=False)
        assert state.service_stats["Read"].responses == 1

    def test_every_nodeid_encoding_reaches_the_same_service(self) -> None:
        state = OpcuaState()
        _feed(state, _frame(b"MSG", service_id=826, encoding=0x01))
        _feed(state, _frame(b"MSG", service_id=205, encoding=0x00))  # TwoByte: one-byte id
        _feed(state, _frame(b"MSG", service_id=826, encoding=0x02))
        assert state.service_stats["Publish"].requests == 2
        assert state.service_stats["Unknown(205)"].requests == 1

    def test_an_unmapped_service_id_is_reported_by_number(self) -> None:
        state = OpcuaState()
        _feed(state, _frame(b"MSG", service_id=9999))
        assert "Unknown(9999)" in state.service_stats


class TestReassembly:
    def test_a_frame_split_across_two_tcp_segments_is_reassembled(self) -> None:
        state = OpcuaState()
        frame = _frame(b"MSG", service_id=631)
        _feed(state, frame[:10])
        assert state.service_stats == {}  # nothing complete yet
        _feed(state, frame[10:])
        assert state.service_stats["Read"].requests == 1

    def test_two_frames_in_one_segment_are_both_read(self) -> None:
        state = OpcuaState()
        _feed(state, _frame(b"MSG", service_id=631) + _frame(b"MSG", service_id=673))
        assert state.service_stats["Read"].requests == 1
        assert state.service_stats["Write"].requests == 1

    def test_a_nonsense_size_field_drops_the_buffer_instead_of_wedging_it(self) -> None:
        state = OpcuaState()
        garbage = b"MSGF" + struct.pack("<I", 4)  # size below the 8-byte minimum
        _feed(state, garbage)
        _feed(state, _frame(b"MSG", service_id=631))
        assert state.service_stats["Read"].requests == 1

    def test_flows_are_buffered_independently(self) -> None:
        state = OpcuaState()
        frame = _frame(b"MSG", service_id=631)
        _feed(state, frame[:10], to_server=True)
        _feed(state, frame, to_server=False)  # the other direction is its own flow
        assert state.service_stats["Read"].responses == 1
        assert state.service_stats["Read"].requests == 0


class TestSummaries:
    def test_categories_add_up_and_deltas_reset(self) -> None:
        state = OpcuaState()
        _feed(state, _frame(b"MSG", service_id=826))  # Publish -> Subscription
        _feed(state, _frame(b"MSG", service_id=631))  # Read -> Polling
        _feed(state, _frame(b"MSG", service_id=461))  # CreateSession -> Session
        _feed(state, _frame(b"MSG", service_id=527))  # Browse -> Browse
        summary = state.get_category_summary()
        assert {name: c["requests"] for name, c in summary.items()} == {
            "Subscription": 1,
            "Polling": 1,
            "Session": 1,
            "Browse": 1,
            "Other": 0,
        }
        assert summary["Polling"]["bytes_delta"] > 0
        state.reset_deltas()
        assert state.get_category_summary()["Polling"]["bytes_delta"] == 0
        assert state.service_stats["Read"].requests == 1  # totals survive the reset
