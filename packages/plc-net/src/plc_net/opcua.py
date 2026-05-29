"""OPC UA binary protocol dissector and traffic analyzer.

Parses OPC UA TCP packets to classify service types (Read, Publish,
Browse, etc.) and track subscription vs polling traffic.

OPC UA binary message layout:
  [0:3]   MessageType ("MSG", "OPN", "CLO", "HEL", "ACK", "ERR")
  [3:4]   Reserved ('F' for final)
  [4:8]   MessageSize (uint32 LE)
  [8:12]  SecureChannelId (uint32 LE) — for MSG/OPN/CLO
  [12:16] TokenId (uint32 LE)
  [16:20] SequenceNumber (uint32 LE)
  [20:24] RequestId (uint32 LE)
  [24:]   Body — starts with TypeId (NodeId of the service)
"""

import struct
import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from scapy.all import IP, TCP, conf, sniff  # type: ignore[attr-defined]

conf.verb = 0

# OPC UA service NodeIds (namespace 0) — request/response pairs
SERVICE_MAP: dict[int, str] = {
    # Session
    461: "CreateSession",
    464: "CreateSession",
    467: "ActivateSession",
    470: "ActivateSession",
    473: "CloseSession",
    476: "CloseSession",
    # Browse
    527: "Browse",
    530: "Browse",
    533: "BrowseNext",
    536: "BrowseNext",
    # Read / Write
    631: "Read",
    634: "Read",
    673: "Write",
    676: "Write",
    # Subscription management
    787: "CreateSubscription",
    790: "CreateSubscription",
    793: "ModifySubscription",
    796: "ModifySubscription",
    799: "DeleteSubscriptions",
    802: "DeleteSubscriptions",
    # Monitored items
    751: "CreateMonitoredItems",
    754: "CreateMonitoredItems",
    763: "ModifyMonitoredItems",
    766: "ModifyMonitoredItems",
    # Publish (subscription data delivery)
    826: "Publish",
    829: "Publish",
    # Republish
    832: "Republish",
    835: "Republish",
    # SetPublishingMode
    805: "SetPublishingMode",
    808: "SetPublishingMode",
    # TranslateBrowsePathsToNodeIds
    554: "TranslateBrowsePaths",
    557: "TranslateBrowsePaths",
}

# Categorize services
SUBSCRIPTION_SERVICES = {
    "Publish",
    "CreateSubscription",
    "ModifySubscription",
    "DeleteSubscriptions",
    "CreateMonitoredItems",
    "ModifyMonitoredItems",
    "SetPublishingMode",
    "Republish",
}
POLLING_SERVICES = {"Read", "Write"}
SESSION_SERVICES = {"CreateSession", "ActivateSession", "CloseSession"}
BROWSE_SERVICES = {"Browse", "BrowseNext", "TranslateBrowsePaths"}


@dataclass
class ServiceStats:
    """Statistics for a single OPC UA service type."""

    requests: int = 0
    responses: int = 0
    request_bytes: int = 0
    response_bytes: int = 0
    # Per-interval deltas
    requests_delta: int = 0
    responses_delta: int = 0
    request_bytes_delta: int = 0
    response_bytes_delta: int = 0


@dataclass
class OpcuaState:
    """Shared state for OPC UA traffic analysis."""

    lock: Lock = field(default_factory=Lock)
    service_stats: dict[str, ServiceStats] = field(default_factory=lambda: defaultdict(ServiceStats))
    # Connection-level stats
    handshake_count: int = 0
    channel_open_count: int = 0
    channel_close_count: int = 0
    error_count: int = 0
    unknown_msg_count: int = 0
    total_opcua_bytes: int = 0
    total_opcua_packets: int = 0
    start_time: float = field(default_factory=time.time)
    # TCP reassembly buffer per flow
    _buffers: dict[str, bytes] = field(default_factory=dict)

    def reset_deltas(self) -> None:
        """Reset per-interval counters."""
        with self.lock:
            for stats in self.service_stats.values():
                stats.requests_delta = 0
                stats.responses_delta = 0
                stats.request_bytes_delta = 0
                stats.response_bytes_delta = 0

    def process_packet(self, pkt: Any) -> None:
        """Process a captured TCP packet on the OPC UA port.

        Parameters
        ----------
        pkt : scapy packet
            Raw captured packet (filtered on port 4840).
        """
        if not pkt.haslayer(TCP) or not pkt.haslayer(IP):
            return

        tcp = pkt[TCP]
        payload = bytes(tcp.payload)
        if not payload:
            return

        ip = pkt[IP]
        flow = f"{ip.src}:{tcp.sport}->{ip.dst}:{tcp.dport}"

        # Append to reassembly buffer
        with self.lock:
            buf = self._buffers.get(flow, b"") + payload
            # Process complete OPC UA messages from buffer
            while len(buf) >= 8:
                msg_type = buf[0:3]
                try:
                    msg_size = struct.unpack_from("<I", buf, 4)[0]
                except struct.error:
                    break

                if msg_size < 8 or msg_size > 65536:
                    # Invalid size — discard buffer
                    buf = b""
                    break

                if len(buf) < msg_size:
                    # Incomplete message — wait for more data
                    break

                msg_data = buf[:msg_size]
                buf = buf[msg_size:]
                self._process_message(msg_type, msg_data, tcp.sport, tcp.dport)

            self._buffers[flow] = buf

    def _process_message(self, msg_type: bytes, data: bytes, sport: int, dport: int) -> None:
        """Process a single complete OPC UA message.

        Parameters
        ----------
        msg_type : bytes
            3-byte message type (b"MSG", b"HEL", etc.)
        data : bytes
            Complete message data including header.
        sport : int
            Source TCP port.
        dport : int
            Destination TCP port.
        """
        size = len(data)
        self.total_opcua_bytes += size
        self.total_opcua_packets += 1

        if msg_type == b"HEL" or msg_type == b"ACK":
            self.handshake_count += 1
            return
        if msg_type == b"OPN":
            self.channel_open_count += 1
            return
        if msg_type == b"CLO":
            self.channel_close_count += 1
            return
        if msg_type == b"ERR":
            self.error_count += 1
            return
        if msg_type != b"MSG":
            self.unknown_msg_count += 1
            return

        # Parse MSG body — extract service TypeId
        if len(data) < 26:
            return

        # TypeId starts at offset 24 (after 12-byte msg header + 12-byte security/seq header)
        encoding_byte = data[24]
        service_id = 0

        if encoding_byte == 0x01:
            # FourByte NodeId: namespace(1) + id(2)
            if len(data) >= 28:
                service_id = struct.unpack_from("<H", data, 26)[0]
        elif encoding_byte == 0x00:
            # TwoByte NodeId: id(1)
            if len(data) >= 26:
                service_id = data[25]
        elif encoding_byte == 0x02:
            # Numeric NodeId: namespace(2) + id(4)
            if len(data) >= 31:
                service_id = struct.unpack_from("<I", data, 27)[0]

        service_name = SERVICE_MAP.get(service_id, f"Unknown({service_id})")
        is_request = dport == 4840  # Request goes TO the server

        stats = self.service_stats[service_name]
        if is_request:
            stats.requests += 1
            stats.request_bytes += size
            stats.requests_delta += 1
            stats.request_bytes_delta += size
        else:
            stats.responses += 1
            stats.response_bytes += size
            stats.responses_delta += 1
            stats.response_bytes_delta += size

    def get_category_summary(self) -> dict[str, dict[str, int]]:
        """Get traffic summary by category.

        Returns
        -------
        dict
            Category → {requests, responses, bytes} mapping.
        """
        categories: dict[str, dict[str, int]] = {
            "Subscription": {"requests": 0, "responses": 0, "bytes": 0, "bytes_delta": 0},
            "Polling": {"requests": 0, "responses": 0, "bytes": 0, "bytes_delta": 0},
            "Session": {"requests": 0, "responses": 0, "bytes": 0, "bytes_delta": 0},
            "Browse": {"requests": 0, "responses": 0, "bytes": 0, "bytes_delta": 0},
            "Other": {"requests": 0, "responses": 0, "bytes": 0, "bytes_delta": 0},
        }

        for name, stats in self.service_stats.items():
            if name in SUBSCRIPTION_SERVICES:
                cat = "Subscription"
            elif name in POLLING_SERVICES:
                cat = "Polling"
            elif name in SESSION_SERVICES:
                cat = "Session"
            elif name in BROWSE_SERVICES:
                cat = "Browse"
            else:
                cat = "Other"

            categories[cat]["requests"] += stats.requests
            categories[cat]["responses"] += stats.responses
            categories[cat]["bytes"] += stats.request_bytes + stats.response_bytes
            categories[cat]["bytes_delta"] += stats.request_bytes_delta + stats.response_bytes_delta

        return categories


def start_opcua_capture(
    state: OpcuaState,
    interface: str | None = None,
    port: int = 4840,
    host: str | None = None,
) -> None:
    """Start OPC UA packet capture (blocking).

    Parameters
    ----------
    state : OpcuaState
        Shared state object.
    interface : str, optional
        Network interface.
    port : int
        OPC UA TCP port.
    host : str, optional
        Filter on specific host IP.
    """
    bpf = f"tcp port {port}"
    if host:
        bpf += f" and host {host}"

    sniff(
        iface=interface,
        filter=bpf,
        prn=state.process_packet,
        store=False,
    )
