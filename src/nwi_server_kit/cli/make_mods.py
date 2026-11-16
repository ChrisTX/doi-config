"""The command line of make_mods.py.

Usage: nwi-server make-mods --game DIR --workshop DIR OUTPUT MODS...
       nwi-server make-mods --game DIR --workshop DIR --check

--game is the game's install, with its game's folder, e.g. doi/, in it (games.py), --workshop
the folder of the workshop items (steamapps/workshop/content/<app>/<item> in it). MODS are the mods' .toml files, or folders of them.
OUTPUT is replaced.
"""

import argparse
import sys
from pathlib import Path

from ..make_mods import ModError, check_scripts, make


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nwi-server make-mods",
        description="Make the mods of mods/<game>/*.toml from the game's map scripts and playlists.",
    )
    parser.add_argument(
        "--game",
        type=Path,
        required=True,
        help="the game's install, with its game's folder, e.g. doi/, in it",
    )
    parser.add_argument(
        "--workshop",
        type=Path,
        required=True,
        help="the folder of the workshop items",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="check every map script of the game and the workshop items instead",
    )
    parser.add_argument(
        "output", type=Path, nargs="?", help="the folder of the mods, replaced"
    )
    parser.add_argument(
        "mods", type=Path, nargs="*", help="the mods' .toml files, or folders of them"
    )
    arguments = parser.parse_args(argv)
    if arguments.check:
        if arguments.output is not None:
            parser.error("--check takes no output or mods")
        try:
            return 1 if check_scripts(arguments.game, arguments.workshop) else 0
        except (ModError, OSError, ValueError) as error:
            print(f"nwi-server make-mods: {error}", file=sys.stderr)
            return 1
    if arguments.output is None or not arguments.mods:
        parser.error("the output and the mods are required")
    try:
        make(arguments.game, arguments.workshop, arguments.output, arguments.mods)
    except (ModError, OSError, ValueError) as error:
        print(f"nwi-server make-mods: {error}", file=sys.stderr)
        return 1
    return 0
