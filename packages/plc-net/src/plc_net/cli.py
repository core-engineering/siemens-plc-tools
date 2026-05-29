"""CLI commands for plc-net: plc net monitor, plc net opcua."""

import threading

import click

from .display import run_dashboard
from .monitor import MonitorState, start_capture
from .opcua import OpcuaState, start_opcua_capture
from .opcua_display import run_opcua_dashboard


@click.group("net")
def net_group() -> None:
    """Industrial network monitoring tools."""
    pass


def main() -> None:
    """Standalone entry point: plc-net monitor."""
    net_group()


@net_group.command()
@click.option("-i", "--interface", default=None, help="Network interface (default: all)")
@click.option("-f", "--filter", "bpf_filter", default="ip", help="BPF filter (default: ip)")
@click.option("-r", "--refresh", default=1.0, help="Dashboard refresh interval in seconds")
def monitor(interface: str | None, bpf_filter: str, refresh: float) -> None:
    """Live network traffic dashboard.

    Captures packets and displays protocol breakdown, top hosts,
    connection matrix, and network health indicators.

    Requires root/sudo for packet capture.

    Examples:

        plc net monitor

        plc net monitor -i eth0

        plc net monitor -f "host 192.168.1.50"

        plc net monitor -f "port 4840"
    """
    state = MonitorState()

    # Start capture in background thread
    capture_thread = threading.Thread(
        target=start_capture,
        args=(state,),
        kwargs={"interface": interface, "bpf_filter": bpf_filter},
        daemon=True,
    )
    capture_thread.start()

    click.echo(
        f"Capturing on {'all interfaces' if not interface else interface} "
        f"(filter: {bpf_filter}) — Ctrl+C to stop\n"
    )

    try:
        run_dashboard(state, refresh=refresh)
    except KeyboardInterrupt:
        click.echo("\nCapture stopped.")


@net_group.command()
@click.option("-i", "--interface", default=None, help="Network interface (default: all)")
@click.option("-p", "--port", default=4840, help="OPC UA TCP port (default: 4840)")
@click.option("-H", "--host", default=None, help="Filter on specific host IP")
@click.option("-r", "--refresh", default=1.0, help="Dashboard refresh interval in seconds")
def opcua(interface: str | None, port: int, host: str | None, refresh: float) -> None:
    """OPC UA traffic analyzer.

    Deep inspection of OPC UA binary protocol. Shows service types
    (Publish, Read, Browse...), subscription vs polling breakdown,
    and data rates per service.

    Requires root/sudo for packet capture.

    Examples:

        plc-net opcua

        plc-net opcua -H 192.168.1.50

        plc-net opcua -p 4840 -i eth0
    """
    state = OpcuaState()

    capture_thread = threading.Thread(
        target=start_opcua_capture,
        args=(state,),
        kwargs={"interface": interface, "port": port, "host": host},
        daemon=True,
    )
    capture_thread.start()

    target = f"host {host}" if host else "all hosts"
    click.echo(f"Analyzing OPC UA on port {port} ({target}) — Ctrl+C to stop\n")

    try:
        run_opcua_dashboard(state, refresh=refresh)
    except KeyboardInterrupt:
        click.echo("\nCapture stopped.")
