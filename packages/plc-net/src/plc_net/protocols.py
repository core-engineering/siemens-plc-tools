"""Protocol classification based on port numbers.

Maps well-known ports to industrial protocol names.
Custom mappings can be added for project-specific services.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Protocol:
    """Network protocol definition."""

    name: str
    color: str  # Rich color for display


# Port → Protocol mapping (TCP and UDP)
PORT_MAP: dict[int, Protocol] = {
    # Industrial
    4840: Protocol("OPC-UA", "bright_cyan"),
    102: Protocol("S7comm", "bright_magenta"),
    # Supervision
    8000: Protocol("API/WS", "bright_green"),
    5173: Protocol("Vite-HMR", "green"),
    6379: Protocol("Redis", "red"),
    5432: Protocol("PostgreSQL", "yellow"),
    # Infrastructure
    22: Protocol("SSH", "bright_white"),
    53: Protocol("DNS", "bright_blue"),
    123: Protocol("NTP", "cyan"),
    514: Protocol("Syslog", "magenta"),
    6514: Protocol("Syslog-PLC", "bright_magenta"),
    443: Protocol("HTTPS", "bright_green"),
    80: Protocol("HTTP", "green"),
    # AD / Kerberos
    88: Protocol("Kerberos", "bright_yellow"),
    389: Protocol("LDAP", "yellow"),
    636: Protocol("LDAPS", "bright_yellow"),
    445: Protocol("SMB", "bright_white"),
}

UNKNOWN = Protocol("Other", "dim")


def classify(sport: int, dport: int) -> Protocol:
    """Classify a packet by source/destination port.

    Parameters
    ----------
    sport : int
        Source port.
    dport : int
        Destination port.

    Returns
    -------
    Protocol
        Matched protocol, or UNKNOWN.
    """
    return PORT_MAP.get(dport) or PORT_MAP.get(sport) or UNKNOWN
