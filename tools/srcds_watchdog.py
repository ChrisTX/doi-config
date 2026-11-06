#!/usr/bin/env python3
"""Run SRCDS under systemd's watchdog.

The main process of doi-server@.service (Type=notify): it starts SRCDS as its child and queries it
with A2S. Once the server first answers, it tells systemd that the service is ready, and after every
answer it pings systemd's watchdog. A server that stops answering for WatchdogSec= is restarted by
systemd (Restart=), within the limits of StartLimitBurst=.

Usage: srcds_watchdog.py [--host HOST] [--port PORT] [--interval SECONDS] [--timeout SECONDS] -- COMMAND...
"""

import argparse
import os
import signal
import socket
import subprocess
import sys
import time

import a2s


def notify(message: str) -> None:
    """Send a message to systemd's notification socket, if there's one."""
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    # An abstract socket's name starts with a null byte
    if address.startswith("@"):
        address = "\0" + address[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.connect(address)
        sock.sendall(message.encode())


def parse_args() -> argparse.Namespace:
    """Parse the command line, the command of the server after --."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=os.getenv("SERVER_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("SERVER_PORT", "27015"))
    )
    parser.add_argument(
        "--interval", type=float, default=10, help="seconds between queries"
    )
    parser.add_argument(
        "--timeout", type=float, default=5, help="seconds to wait for an answer"
    )
    parser.add_argument("command", nargs="+", help="the server's command line")
    return parser.parse_args()


def main() -> int:
    """Run the server and watch it until it exits."""
    args = parse_args()
    server = subprocess.Popen(args.command)

    # systemd stops the service with KillMode=mixed: the signal goes to this process only, which passes
    # it on, so the server shuts down once. The watchdog's SIGABRT too, so that the hung server dumps
    # its core rather than this process.
    def forward(signum: int, _frame: object) -> None:
        server.send_signal(signum)

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGABRT):
        signal.signal(signum, forward)

    ready = False
    while server.poll() is None:
        try:
            info = a2s.info((args.host, args.port), timeout=args.timeout)
        # Whatever goes wrong with the query, the server didn't answer; the watchdog decides when
        # that's too long. Before the first answer, the server is still starting.
        except Exception as e:  # noqa: BLE001
            if ready:
                print(
                    f"No answer from {args.host}:{args.port}: {e!r}",
                    file=sys.stderr,
                    flush=True,
                )
        else:
            status = f"{info.map_name}, {info.player_count}/{info.max_players} players"
            if not ready:
                notify(f"READY=1\nSTATUS={status}")
                ready = True
            else:
                notify(f"WATCHDOG=1\nSTATUS={status}")
        time.sleep(args.interval)

    # The server's exit status, as a shell would report it
    return server.returncode if server.returncode >= 0 else 128 - server.returncode


if __name__ == "__main__":
    sys.exit(main())
