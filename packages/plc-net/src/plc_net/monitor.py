"""Packet capture and statistics engine.

Captures packets with scapy and maintains rolling statistics
for protocol distribution, host traffic, and network health.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from scapy.all import ICMP, IP, TCP, UDP, conf, sniff  # type: ignore[attr-defined]

from .protocols import UNKNOWN, Protocol, classify

# Suppress scapy warnings
conf.verb = 0


@dataclass
class ProtocolStats:
    """Rolling statistics for a single protocol."""

    packets: int = 0
    bytes: int = 0
    # Per-second counters (reset each display cycle)
    packets_delta: int = 0
    bytes_delta: int = 0


@dataclass
class HostStats:
    """Traffic statistics for a single host."""

    tx_bytes: int = 0
    rx_bytes: int = 0
    tx_packets: int = 0
    rx_packets: int = 0


@dataclass
class ConnectionKey:
    """Unique connection identifier."""

    src: str
    dst: str
    proto: str


@dataclass
class NetworkHealth:
    """Network health indicators."""

    tcp_retransmissions: int = 0
    tcp_resets: int = 0
    icmp_unreachable: int = 0
    tcp_syn: int = 0
    tcp_fin: int = 0


@dataclass
class MonitorState:
    """Shared state for the packet capture thread."""

    lock: Lock = field(default_factory=Lock)
    protocol_stats: dict[str, ProtocolStats] = field(default_factory=lambda: defaultdict(ProtocolStats))
    host_stats: dict[str, HostStats] = field(default_factory=lambda: defaultdict(HostStats))
    connections: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    health: NetworkHealth = field(default_factory=NetworkHealth)
    total_packets: int = 0
    total_bytes: int = 0
    start_time: float = field(default_factory=time.time)
    # Track sequence numbers for retransmission detection
    _seen_seqs: dict[str, int] = field(default_factory=dict)

    def reset_deltas(self) -> None:
        """Reset per-interval counters."""
        with self.lock:
            for stats in self.protocol_stats.values():
                stats.packets_delta = 0
                stats.bytes_delta = 0

    def process_packet(self, pkt: Any) -> None:
        """Process a captured packet and update statistics.

        Parameters
        ----------
        pkt : scapy packet
            Raw captured packet.
        """
        if not pkt.haslayer(IP):
            return

        ip = pkt[IP]
        size = len(pkt)
        src = ip.src
        dst = ip.dst
        sport = 0
        dport = 0
        proto = UNKNOWN

        with self.lock:
            self.total_packets += 1
            self.total_bytes += size

            # Classify protocol
            if pkt.haslayer(TCP):
                tcp = pkt[TCP]
                sport = tcp.sport
                dport = tcp.dport
                proto = classify(sport, dport)

                # TCP health indicators
                flags = tcp.flags
                if flags & 0x04:  # RST
                    self.health.tcp_resets += 1
                if flags & 0x02:  # SYN
                    self.health.tcp_syn += 1
                if flags & 0x01:  # FIN
                    self.health.tcp_fin += 1

                # Retransmission detection (same seq number seen again)
                flow_key = f"{src}:{sport}->{dst}:{dport}"
                seq = tcp.seq
                if flow_key in self._seen_seqs and self._seen_seqs[flow_key] == seq and size > 0:
                    self.health.tcp_retransmissions += 1
                self._seen_seqs[flow_key] = seq

            elif pkt.haslayer(UDP):
                udp = pkt[UDP]
                sport = udp.sport
                dport = udp.dport
                proto = classify(sport, dport)

            elif pkt.haslayer(ICMP):
                icmp = pkt[ICMP]
                proto = Protocol("ICMP", "bright_red")
                if icmp.type == 3:  # Destination unreachable
                    self.health.icmp_unreachable += 1

            # Update protocol stats
            ps = self.protocol_stats[proto.name]
            ps.packets += 1
            ps.bytes += size
            ps.packets_delta += 1
            ps.bytes_delta += size

            # Update host stats
            self.host_stats[src].tx_bytes += size
            self.host_stats[src].tx_packets += 1
            self.host_stats[dst].rx_bytes += size
            self.host_stats[dst].rx_packets += 1

            # Track connections
            self.connections[src].add(dst)


def start_capture(
    state: MonitorState,
    interface: str | None = None,
    bpf_filter: str = "ip",
) -> None:
    """Start packet capture in the current thread (blocking).

    Parameters
    ----------
    state : MonitorState
        Shared state object to update.
    interface : str, optional
        Network interface to capture on. None = all interfaces.
    bpf_filter : str
        BPF filter string for packet capture.
    """
    sniff(
        iface=interface,
        filter=bpf_filter,
        prn=state.process_packet,
        store=False,
    )
