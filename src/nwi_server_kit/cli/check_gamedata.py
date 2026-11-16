"""The command line of check_gamedata.py."""

import argparse
import sys
from pathlib import Path

from .. import check_gamedata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nwi-server check-gamedata",
        description=check_gamedata.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "game_dir",
        type=Path,
        metavar="GAME",
        help="the game install, with its game's folder, doi/ or insurgency/, in it",
    )
    parser.add_argument(
        "--gamedata",
        type=Path,
        default=None,
        help="the gamedata file (of the default config source's configs by default)",
    )
    args = parser.parse_args(argv)
    try:
        missing = check_gamedata.missing(args.game_dir, args.gamedata)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    for line in missing:
        print(f"Error: {line}", file=sys.stderr)
    return 1 if missing else 0
