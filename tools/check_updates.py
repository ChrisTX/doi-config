#!/usr/bin/env python3
"""Check whether the games or the workshop items have updates, without downloading them.

The games and items of the servers (tools/games.py), in the state folder STATE as
tools/update_layers.sh updates them: STATE/<game>/depots and STATE/<game>/workshop. A game that isn't
installed counts as an update.

A game: each depot of its dedicated server for Linux, as its record has it (STATE/<game>/depots,
tools/update_game.sh), against the public branch's manifest as DepotDownloader lists it. The depots,
not the build ID, as the shared depot 1006, the Steam client library (steamclient.so), changes without
a new build of the game.

The workshop items: each item of the game's servers' lists against the Steam Web API's current
manifest of the item (GetPublishedFileDetails, no key needed), which the record of the installed
items (steamapps/workshop/appworkshop_<app>.acf) has too. An item of a list that isn't
installed counts as an update.

Exit status: 0 if there are updates, which it lists, 1 if there are none, 255 if it can't tell, e.g.
without a connection. For systemd's ExecCondition=, which skips the unit on 1 and fails it on 255.

Usage: check_updates.py STATE
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from srctools.keyvalues import Keyvalues

from games import SERVER_APPS, item_details, servers, used_games, workshop_items

UPDATES = 0
NO_UPDATES = 1
UNKNOWN = 255

# Steam's text KeyValues (VDF), read by srctools: a key's value is a string or a dict
Tree = dict[str, "str | Tree"]


def as_tree(keyvalues: Keyvalues) -> Tree:
    """A block's keys as dicts, later keys replacing earlier ones, as Steam reads them."""
    return {
        key.real_name: as_tree(key) if key.has_children() else key.value
        for key in keyvalues
    }


def parse_vdf(path: Path) -> Tree:
    """Parse a VDF file of Steam's into dicts."""
    return as_tree(Keyvalues.parse(path.read_text(), path))


def block(tree: "str | Tree", *keys: str) -> Tree:
    """The block at the keys' path; an empty one if it's missing."""
    for key in keys:
        if not isinstance(tree, dict) or not isinstance(tree.get(key), dict):
            return {}
        tree = tree[key]
    return tree if isinstance(tree, dict) else {}


def game_updates(game: str, state: Path) -> list[str]:
    """The game's depots whose manifest isn't the public branch's any more, or that it doesn't have."""
    record = state / game / "depots"
    if not record.is_file():
        return [f"{game}: not installed"]
    installed = dict(line.split() for line in record.read_text().splitlines() if line)
    # The public branch's depots for Linux, as DepotDownloader lists them: manifest_<depot>_<manifest>.txt
    with tempfile.TemporaryDirectory() as listing:
        result = subprocess.run(
            [
                "depotdownloader",
                "-app",
                str(SERVER_APPS[game]),
                "-os",
                "linux",
                "-manifest-only",
                "-dir",
                listing,
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=300,
            check=False,
        )
        current = dict(
            path.stem.removeprefix("manifest_").split("_", 1)
            for path in Path(listing).glob("manifest_*_*.txt")
        )
    if result.returncode != 0 or not current:
        raise ValueError(
            f"DepotDownloader listed no depots of {game}: {result.stdout[-500:]}"
        )
    return [
        f"{game}: depot {depot}: manifest {manifest}"
        for depot, manifest in sorted(current.items())
        if installed.get(depot) != manifest
    ]


def workshop_updates(workshop: Path, items: list[int]) -> list[str]:
    """The items whose installed manifest isn't the current one, or that aren't installed."""
    if not items:
        return []
    # The items of the workshop's app, whichever it is: the items' IDs are unique across them
    installed: Tree = {}
    for manifest in sorted(workshop.glob("steamapps/workshop/appworkshop_*.acf")):
        installed |= block(parse_vdf(manifest), "AppWorkshop", "WorkshopItemsInstalled")
    updates = []
    for detail in item_details(items):
        item = detail["publishedfileid"]
        # An item that was removed from the workshop (a result other than 1) can't be updated
        if detail.get("result") != 1:
            print(
                f"workshop item {item} isn't available: result {detail.get('result')}",
                file=sys.stderr,
            )
            continue
        current = detail.get("hcontent_file")
        info = installed.get(item)
        if not isinstance(info, dict):
            updates.append(
                f"workshop item {item} ({detail.get('title')}): not installed"
            )
        elif info.get("manifest") != current:
            updates.append(
                f"workshop item {item} ({detail.get('title')}): manifest {current}"
            )
    return updates


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check the servers' games and workshop items for updates."
    )
    parser.add_argument(
        "state", type=Path, metavar="STATE", help="the state folder of the layers"
    )
    arguments = parser.parse_args()
    # The config sources' clones of the state, as servers() reads the servers' settings there
    os.environ["NWI_LAYERS"] = str(arguments.state)
    try:
        found = servers()
        updates = []
        for game in used_games(found):
            folder = arguments.state / game
            updates += game_updates(game, arguments.state)
            updates += workshop_updates(
                folder / "workshop", workshop_items(found, game)
            )
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"check_updates.py: can't check for updates: {error}", file=sys.stderr)
        return UNKNOWN
    for update in updates:
        print(f"update: {update}")
    if not updates:
        print("no updates")
    return UPDATES if updates else NO_UPDATES


if __name__ == "__main__":
    sys.exit(main())
