"""Rich live dashboard for network monitoring.

Renders protocol stats, top talkers, connection matrix,
and health indicators in a live-updating terminal UI.
"""

import time

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from .monitor import MonitorState
from .protocols import PORT_MAP


def _format_bytes(b: int) -> str:
    """Format bytes to human-readable string."""
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    if b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB"
    return f"{b / (1024 * 1024 * 1024):.1f} GB"


def _format_rate(b: int, interval: float) -> str:
    """Format bytes/interval to rate string."""
    if interval <= 0:
        return "0 B/s"
    rate = b / interval
    if rate < 1024:
        return f"{rate:.0f} B/s"
    if rate < 1024 * 1024:
        return f"{rate / 1024:.1f} KB/s"
    return f"{rate / (1024 * 1024):.1f} MB/s"


def _protocol_color(name: str) -> str:
    """Get Rich color for a protocol name."""
    for proto in PORT_MAP.values():
        if proto.name == name:
            return proto.color
    return "dim"


def build_protocol_table(state: MonitorState, interval: float) -> Table:
    """Build protocol breakdown table.

    Parameters
    ----------
    state : MonitorState
        Current monitor state.
    interval : float
        Seconds since last refresh.

    Returns
    -------
    Table
        Rich table with protocol statistics.
    """
    table = Table(title="Protocol Breakdown", expand=True, border_style="dim")
    table.add_column("Protocol", style="bold", min_width=12)
    table.add_column("Packets", justify="right")
    table.add_column("Pkt/s", justify="right")
    table.add_column("Volume", justify="right")
    table.add_column("Rate", justify="right")

    with state.lock:
        sorted_protos = sorted(
            state.protocol_stats.items(),
            key=lambda x: x[1].bytes,
            reverse=True,
        )
        for name, stats in sorted_protos:
            color = _protocol_color(name)
            pps = stats.packets_delta / interval if interval > 0 else 0
            table.add_row(
                f"[{color}]{name}[/{color}]",
                str(stats.packets),
                f"{pps:.0f}",
                _format_bytes(stats.bytes),
                _format_rate(stats.bytes_delta, interval),
            )

    return table


def build_host_table(state: MonitorState) -> Table:
    """Build top talkers table.

    Parameters
    ----------
    state : MonitorState
        Current monitor state.

    Returns
    -------
    Table
        Rich table with per-host traffic.
    """
    table = Table(title="Top Hosts", expand=True, border_style="dim")
    table.add_column("Host", style="bold", min_width=15)
    table.add_column("TX", justify="right")
    table.add_column("RX", justify="right")
    table.add_column("Packets", justify="right")
    table.add_column("Connections", justify="right")

    with state.lock:
        sorted_hosts = sorted(
            state.host_stats.items(),
            key=lambda x: x[1].tx_bytes + x[1].rx_bytes,
            reverse=True,
        )[
            :10
        ]  # Top 10
        for host, stats in sorted_hosts:
            conn_count = len(state.connections.get(host, set()))
            table.add_row(
                host,
                _format_bytes(stats.tx_bytes),
                _format_bytes(stats.rx_bytes),
                str(stats.tx_packets + stats.rx_packets),
                str(conn_count),
            )

    return table


def build_connection_table(state: MonitorState) -> Table:
    """Build connection matrix table.

    Parameters
    ----------
    state : MonitorState
        Current monitor state.

    Returns
    -------
    Table
        Rich table showing who talks to who.
    """
    table = Table(title="Active Connections", expand=True, border_style="dim")
    table.add_column("Source", style="bold")
    table.add_column("→ Destinations", style="dim")

    with state.lock:
        for src, dsts in sorted(state.connections.items()):
            table.add_row(src, ", ".join(sorted(dsts)))

    return table


def build_health_panel(state: MonitorState) -> Panel:
    """Build network health indicators panel.

    Parameters
    ----------
    state : MonitorState
        Current monitor state.

    Returns
    -------
    Panel
        Rich panel with health indicators.
    """
    with state.lock:
        h = state.health
        uptime = time.time() - state.start_time

        retrans_style = "red bold" if h.tcp_retransmissions > 0 else "green"
        rst_style = "yellow bold" if h.tcp_resets > 0 else "green"
        icmp_style = "red bold" if h.icmp_unreachable > 0 else "green"

        lines = [
            f"  Uptime:             {uptime:.0f}s",
            f"  Total packets:      {state.total_packets}",
            f"  Total volume:       {_format_bytes(state.total_bytes)}",
            "",
            f"  [{retrans_style}]TCP Retransmissions: {h.tcp_retransmissions}[/{retrans_style}]",
            f"  [{rst_style}]TCP Resets (RST):    {h.tcp_resets}[/{rst_style}]",
            f"  [{icmp_style}]ICMP Unreachable:    {h.icmp_unreachable}[/{icmp_style}]",
            f"  TCP SYN:            {h.tcp_syn}",
            f"  TCP FIN:            {h.tcp_fin}",
        ]

    return Panel("\n".join(lines), title="Network Health", border_style="dim")


def run_dashboard(state: MonitorState, refresh: float = 1.0) -> None:
    """Run the live Rich dashboard (blocking).

    Parameters
    ----------
    state : MonitorState
        Shared monitor state.
    refresh : float
        Refresh interval in seconds.
    """
    console = Console()

    with Live(console=console, refresh_per_second=2, screen=True) as live:
        while True:
            start = time.time()

            layout = Layout()
            layout.split_column(
                Layout(name="top", ratio=2),
                Layout(name="bottom", ratio=1),
            )
            layout["top"].split_row(
                Layout(build_protocol_table(state, refresh), name="protocols"),
                Layout(build_host_table(state), name="hosts"),
            )
            layout["bottom"].split_row(
                Layout(build_connection_table(state), name="connections"),
                Layout(build_health_panel(state), name="health"),
            )

            live.update(layout)
            state.reset_deltas()

            elapsed = time.time() - start
            sleep_time = max(0, refresh - elapsed)
            time.sleep(sleep_time)
