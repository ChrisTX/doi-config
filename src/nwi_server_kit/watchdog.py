"""Run SRCDS under systemd's watchdog.

The main process of nwi-server@.service (Type=notify), in nwi-server start (launch.py): it starts SRCDS as its child and queries it
with A2S. Once the server first answers, it tells systemd that the service is ready, and after every
answer it pings systemd's watchdog. A server that stops answering for WatchdogSec= is restarted by
systemd (Restart=), within the limits of StartLimitBurst=.

With NWI_HEALTH, a folder, it writes how the server goes to NWI_HEALTH/status.json after every answer,
for the trial of new versions of its layers (nwi_server_kit.health): its run (INVOCATION_ID), whether
it answered yet, its map, the seconds it was busy, with at least NWI_BLESS_PLAYERS human players (4 by
default; A2S counts the bots as players too), and the maps played to their end while busy, those it
changed from to another.

Without systemd, as in the container, it only runs the server. With --check, it queries the server once
and exits with 0 if it answered, for a container's health check.

    nwi-server watchdog [--host HOST] [--port PORT] [--interval SECONDS] [--timeout SECONDS] -- COMMAND...
    nwi-server watchdog [--host HOST] [--port PORT] [--timeout SECONDS] --check
"""

import argparse
import json
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


class Health:
    """How the server goes, written to NWI_HEALTH/status.json, see the module's documentation."""

    def __init__(self, folder: str) -> None:
        self.path = os.path.join(folder, "status.json")
        self.players = int(os.environ.get("NWI_BLESS_PLAYERS", "4"))
        self.status: dict = {
            "invocation": os.environ.get("INVOCATION_ID"),
            "ready": False,
            "map": None,
            "busy_seconds": 0.0,
            "completed": [],
        }
        # Whether the current map was busy at some point
        self.map_busy = False

    def answered(self, map_name: str, humans: int, seconds: float) -> None:
        """Record an answer, SECONDS after the one before."""
        busy = humans >= self.players
        if self.status["map"] is not None and map_name != self.status["map"]:
            if self.map_busy:
                self.status["completed"].append(self.status["map"])
            self.map_busy = False
        self.map_busy = self.map_busy or busy
        self.status.update(ready=True, map=map_name)
        if busy:
            self.status["busy_seconds"] += seconds
        temporary = f"{self.path}.new"
        with open(temporary, "w") as file:
            json.dump(self.status, file)
        os.replace(temporary, self.path)


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


def check(host: str, port: int, timeout: float) -> int:
    """Query the server once: 0 if it answered."""
    try:
        a2s.info((host, port), timeout=timeout)
    # Whatever goes wrong with the query, the server didn't answer
    except Exception as e:  # noqa: BLE001
        print(f"No answer from {host}:{port}: {e!r}", file=sys.stderr)
        return 1
    return 0


def default_host() -> str:
    return os.getenv("SERVER_HOST") or own_address()


def default_port() -> int:
    return int(os.getenv("SERVER_PORT", "27015"))


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command line, the command of the server after --."""
    parser = argparse.ArgumentParser(
        prog="nwi-server watchdog",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host",
        default=default_host(),
        help="the server's address, by default the address this machine's traffic leaves from",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=default_port(),
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.check:
        return check(args.host, args.port, args.timeout)
    if not args.command:
        print("No command to run the server with", file=sys.stderr)
        return 2
    return watch(args.command, args.host, args.port, args.interval, args.timeout)


def watch(
    command: list[str],
    host: str,
    port: int,
    interval: float = 10,
    timeout: float = 5,
    env: dict[str, str] | None = None,
) -> int:
    """Run the server, with ENV as its environment if given, and watch it until it exits; its exit
    status."""
    server = subprocess.Popen(command, env=env)

    # systemd stops the service with KillMode=mixed: the signal goes to this process only, which passes
    # it on, so the server shuts down once. The watchdog's SIGABRT too, so that the hung server dumps
    # its core rather than this process.
    def forward(signum: int, _frame: object) -> None:
        server.send_signal(signum)

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGABRT):
        signal.signal(signum, forward)

    health = Health(os.environ["NWI_HEALTH"]) if os.environ.get("NWI_HEALTH") else None
    ready = False
    last = time.monotonic()
    while server.poll() is None:
        try:
            info = a2s.info((host, port), timeout=timeout)
        # Whatever goes wrong with the query, the server didn't answer; the watchdog decides when
        # that's too long. Before the first answer, the server is still starting.
        except Exception as e:  # noqa: BLE001
            if ready:
                print(
                    f"No answer from {host}:{port}: {e!r}",
                    file=sys.stderr,
                    flush=True,
                )
        else:
            status = f"{info.map_name}, {info.player_count}/{info.max_players} players"
            now = time.monotonic()
            if health is not None:
                try:
                    # A time without answers doesn't count, at most the time to the next query
                    seconds = min(now - last, interval + timeout)
                    health.answered(
                        info.map_name, info.player_count - info.bot_count, seconds
                    )
                # The server runs on without its health written
                except OSError as e:
                    print(f"No status: {e!r}", file=sys.stderr, flush=True)
            last = now
            if not ready:
                notify(f"READY=1\nSTATUS={status}")
                ready = True
            else:
                notify(f"WATCHDOG=1\nSTATUS={status}")
        time.sleep(interval)

    # The server's exit status, as a shell would report it
    return server.returncode if server.returncode >= 0 else 128 - server.returncode
