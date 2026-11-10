#!/usr/bin/env python3
"""Run SRCDS under systemd's watchdog.

The main process of doi-server@.service (Type=notify): it starts SRCDS as its child and queries it
with A2S. Once the server first answers, it tells systemd that the service is ready, and after every
answer it pings systemd's watchdog. A server that stops answering for WatchdogSec= is restarted by
systemd (Restart=), within the limits of StartLimitBurst=.

Without systemd, as in the container, it only runs the server. With --check, it queries the server once
and exits with 0 if it answered, for a container's health check.

    srcds_watchdog.py [--host HOST] [--port PORT] [--interval SECONDS] [--timeout SECONDS] -- COMMAND...
    srcds_watchdog.py [--host HOST] [--port PORT] [--timeout SECONDS] --check
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


def own_address() -> str:
    """Return the address of this machine that its traffic leaves from.

    SRCDS doesn't answer queries from 127.0.0.1, so the server is queried on this address. Connecting a
    UDP socket only picks the route, it sends nothing.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("192.0.2.1", 9))
            return sock.getsockname()[0]
        # Without a route, there's no other address to query on
        except OSError:
            return "127.0.0.1"


def parse_args() -> argparse.Namespace:
    """Parse the command line, the command of the server after --."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--host",
        default=os.getenv("SERVER_HOST") or own_address(),
        help="the server's address, by default the address this machine's traffic leaves from",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("SERVER_PORT", "27015")),
        help="the server's port, by default SERVER_PORT or 27015",
    )
    parser.add_argument(
        "--interval", type=float, default=10, help="seconds between queries"
    )
    parser.add_argument(
        "--timeout", type=float, default=5, help="seconds to wait for an answer"
    )
    parser.add_argument("--check", action="store_true", help="query the server once")
    parser.add_argument("command", nargs="*", help="the server's command line")
    return parser.parse_args()


def main() -> int:
    """Run the server and watch it until it exits."""
    args = parse_args()
    if args.check:
        try:
            a2s.info((args.host, args.port), timeout=args.timeout)
        # Whatever goes wrong with the query, the server didn't answer
        except Exception as e:  # noqa: BLE001
            print(f"No answer from {args.host}:{args.port}: {e!r}", file=sys.stderr)
            return 1
        return 0
    if not args.command:
        print("No command to run the server with", file=sys.stderr)
        return 2
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
