"""The command line of watchdog.py.

Usage:
    nwi-server watchdog [--host HOST] [--port PORT] [--interval SECONDS] [--timeout SECONDS] -- COMMAND...
    nwi-server watchdog [--host HOST] [--port PORT] [--timeout SECONDS] --check
"""

import argparse
import sys

from .. import watchdog
from ..watchdog import check, default_host, default_port, watch


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command line, the command of the server after --."""
    parser = argparse.ArgumentParser(
        prog="nwi-server watchdog",
        description=watchdog.__doc__ + (__doc__ or ""),
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
