"""Rich live dashboard for OPC UA traffic analysis.

Displays service breakdown, subscription vs polling rates,
and connection health for OPC UA communications.
"""

import time

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from .opcua import POLLING_SERVICES, SUBSCRIPTION_SERVICES, OpcuaState


def _format_bytes(b: int) -> str:
    """Format bytes to human-readable string."""
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b / (1024 * 1024):.1f} MB"


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


def build_service_table(state: OpcuaState, interval: float) -> Table:
    """Build OPC UA service breakdown table."""
    table = Table(title="OPC UA Services", expand=True, border_style="dim")
    table.add_column("Service", style="bold", min_width=20)
    table.add_column("Req", justify="right")
    table.add_column("Resp", justify="right")
    table.add_column("Req/s", justify="right")
    table.add_column("Volume", justify="right")
    table.add_column("Rate", justify="right")

    with state.lock:
        sorted_services = sorted(
            state.service_stats.items(),
            key=lambda x: x[1].request_bytes + x[1].response_bytes,
            reverse=True,
        )
        for name, stats in sorted_services:
            total_bytes = stats.request_bytes + stats.response_bytes
            delta_bytes = stats.request_bytes_delta + stats.response_bytes_delta
            rps = stats.requests_delta / interval if interval > 0 else 0

            if name in SUBSCRIPTION_SERVICES:
                color = "bright_cyan"
            elif name in POLLING_SERVICES:
                color = "bright_yellow"
            else:
                color = "dim"

            table.add_row(
                f"[{color}]{name}[/{color}]",
                str(stats.requests),
                str(stats.responses),
                f"{rps:.1f}",
                _format_bytes(total_bytes),
                _format_rate(delta_bytes, interval),
            )

    return table


def build_category_table(state: OpcuaState, interval: float) -> Table:
    """Build subscription vs polling summary table."""
    table = Table(title="Traffic Categories", expand=True, border_style="dim")
    table.add_column("Category", style="bold", min_width=14)
    table.add_column("Req", justify="right")
    table.add_column("Resp", justify="right")
    table.add_column("Volume", justify="right")
    table.add_column("Rate", justify="right")
    table.add_column("Share", justify="right")

    with state.lock:
        categories = state.get_category_summary()
        total = state.total_opcua_bytes or 1

        colors = {
            "Subscription": "bright_cyan",
            "Polling": "bright_yellow",
            "Session": "green",
            "Browse": "magenta",
            "Other": "dim",
        }

        for cat_name, cat_stats in categories.items():
            if cat_stats["requests"] == 0 and cat_stats["responses"] == 0:
                continue
            share = cat_stats["bytes"] / total * 100
            color = colors.get(cat_name, "dim")
            table.add_row(
                f"[{color}]{cat_name}[/{color}]",
                str(cat_stats["requests"]),
                str(cat_stats["responses"]),
                _format_bytes(cat_stats["bytes"]),
                _format_rate(cat_stats["bytes_delta"], interval),
                f"{share:.1f}%",
            )

    return table


def build_opcua_health_panel(state: OpcuaState) -> Panel:
    """Build OPC UA connection health panel."""
    with state.lock:
        uptime = time.time() - state.start_time

        # Calculate Publish rate (subscription data delivery)
        pub_stats = state.service_stats.get("Publish")
        pub_resp = pub_stats.responses if pub_stats else 0
        pub_rate = pub_resp / uptime if uptime > 0 else 0
        pub_bytes = pub_stats.response_bytes if pub_stats else 0

        # Calculate Read rate (polling)
        read_stats = state.service_stats.get("Read")
        read_req = read_stats.requests if read_stats else 0
        read_rate = read_req / uptime if uptime > 0 else 0

        err_style = "red bold" if state.error_count > 0 else "green"

        lines = [
            f"  Uptime:                {uptime:.0f}s",
            f"  Total OPC UA packets:  {state.total_opcua_packets}",
            f"  Total OPC UA volume:   {_format_bytes(state.total_opcua_bytes)}",
            "",
            f"  [bright_cyan]Publish notifications:  {pub_resp}  ({pub_rate:.1f}/s)[/bright_cyan]",
            f"  [bright_cyan]Subscription data:      {_format_bytes(pub_bytes)}[/bright_cyan]",
            f"  [bright_yellow]Read requests:          {read_req}  ({read_rate:.1f}/s)[/bright_yellow]",
            "",
            f"  Handshakes (HEL/ACK):  {state.handshake_count}",
            f"  Channel opens:         {state.channel_open_count}",
            f"  Channel closes:        {state.channel_close_count}",
            f"  [{err_style}]OPC UA errors:          {state.error_count}[/{err_style}]",
        ]

    return Panel("\n".join(lines), title="OPC UA Health", border_style="dim")


def run_opcua_dashboard(state: OpcuaState, refresh: float = 1.0) -> None:
    """Run the OPC UA live dashboard (blocking).

    Parameters
    ----------
    state : OpcuaState
        Shared state.
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
                Layout(build_service_table(state, refresh), name="services", ratio=3),
                Layout(build_category_table(state, refresh), name="categories", ratio=2),
            )
            layout["bottom"].update(build_opcua_health_panel(state))

            live.update(layout)
            state.reset_deltas()

            elapsed = time.time() - start
            sleep_time = max(0, refresh - elapsed)
            time.sleep(sleep_time)
