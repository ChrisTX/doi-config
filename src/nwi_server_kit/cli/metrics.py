"""The command line of metrics.py."""

import argparse
import sys

from .. import metrics

# The port metrics serves on by default
PORT = 9734


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nwi-server metrics",
        description=metrics.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--listen",
        default=f"127.0.0.1:{PORT}",
        metavar="ADDRESS:PORT",
        help="where to serve /metrics (%(default)s): an internal address only",
    )
    parser.add_argument(
        "--once", action="store_true", help="print the metrics once instead"
    )
    args = parser.parse_args(argv)
    if args.once:
        print(metrics.render([metrics.collect(t) for t in metrics.targets()]), end="")
        return 0
    address, _, port = args.listen.rpartition(":")
    if not address or not port.isdigit():
        print(f"--listen is ADDRESS:PORT, not {args.listen}", file=sys.stderr)
        return 2
    metrics.serve(address.strip("[]"), int(port))
    return 0
