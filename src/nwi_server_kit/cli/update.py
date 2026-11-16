"""The command line of update.py."""

import argparse
import subprocess
import sys
from pathlib import Path

from .. import update as library
from ..update import compile_plugins, update


def compile_main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("Usage: nwi-server compile-plugins CONFIGS OUTPUT", file=sys.stderr)
        return 2
    try:
        compile_plugins(Path(args[0]), Path(args[1]))
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"nwi-server compile-plugins: {error}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nwi-server update",
        description=library.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--image", action="store_true", help="for the container image")
    parser.add_argument("state", type=Path, metavar="STATE", help="the updater's state")
    args = parser.parse_args(argv)
    try:
        update(args.state, args.image)
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"nwi-server update: {error}", file=sys.stderr)
        return 1
    return 0
