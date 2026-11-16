"""The command line of launch.py.

Usage:
    nwi-server prepare ROOT NAME   configure the server of ROOT, named NAME, in its writable layer
    nwi-server start ROOT          run the server of ROOT (srcds_linux there) under the watchdog
"""

import sys
from pathlib import Path

from ..launch import prepare, start


def prepare_main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.split("Usage:")[1].split("\n\n")[0], file=sys.stderr)
        return 2
    try:
        prepare(Path(argv[0]), argv[1])
    except (OSError, ValueError) as error:
        print(f"nwi-server prepare: {error}", file=sys.stderr)
        return 1
    return 0


def start_main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.split("Usage:")[1].split("\n\n")[0], file=sys.stderr)
        return 2
    try:
        return start(Path(argv[0]))
    except (OSError, ValueError) as error:
        print(f"nwi-server start: {error}", file=sys.stderr)
        return 1
