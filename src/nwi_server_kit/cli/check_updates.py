"""The command line of check_updates.py.

Usage: nwi-server check-updates STATE
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from ..check_updates import NO_UPDATES, UNKNOWN, UPDATES, game_updates, workshop_updates
from ..games import item_sources, servers, used_games


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nwi-server check-updates",
        description="Check the servers' games and workshop items for updates.",
    )
    parser.add_argument(
        "state", type=Path, metavar="STATE", help="the state folder of the layers"
    )
    arguments = parser.parse_args(argv)
    # The config sources' versions of the state, as servers() reads the servers' settings there
    os.environ["NWI_LAYERS"] = str(arguments.state)
    try:
        found = servers()
        updates = []
        for game in used_games(found):
            updates += game_updates(game, arguments.state)
            updates += workshop_updates(
                arguments.state, game, item_sources(found, game)
            )
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(
            f"nwi-server check-updates: can't check for updates: {error}",
            file=sys.stderr,
        )
        return UNKNOWN
    for update in updates:
        print(f"update: {update}")
    if not updates:
        print("no updates")
    return UPDATES if updates else NO_UPDATES
