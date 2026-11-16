"""Check whether the games or the workshop items have updates, without downloading them.

The games and items of the servers (games.py), in the state folder STATE of the layers as
nwi-server update keeps it (update.py). A game that isn't installed counts as an update.

A game: each depot of its dedicated server for Linux, as its record has it (STATE/<game>/depots),
against the public branch's manifest as DepotDownloader lists it. The depots,
not the build ID, as the shared depot 1006, the Steam client library (steamclient.so), changes without
a new build of the game.

The workshop items: each item of the game's servers' lists against the Steam Web API's current
manifest of the item (GetPublishedFileDetails, no key needed), which the newest version of
the item's layer has in its name (<game>/item-<item>.v, update.py). An item of a list that isn't
installed counts as an update; a version the update held for every config source whose servers list it
doesn't (workshop.py).

Exit status: 0 if there are updates, which it lists, 1 if there are none, 255 if it can't tell, e.g.
without a connection. For systemd's ExecCondition=, which skips the unit on 1 and fails it on 255.

Usage: nwi-server check-updates STATE
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import layers, workshop
from .games import SERVER_APPS, item_details, item_sources, servers, used_games

UPDATES = 0
NO_UPDATES = 1
UNKNOWN = 255


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


def workshop_updates(state: Path, game: str, sources: dict[int, set[str]]) -> list[str]:
    """The items whose newest version's manifest (<time>.<manifest>) isn't the current one, or that
    have no version, unless the current one is held for all the sources whose servers list it."""
    if not sources:
        return []
    updates = []
    held = workshop.State(state).held
    for detail in item_details(sorted(sources)):
        item = detail["publishedfileid"]
        # An item that was removed from the workshop (a result other than 1) can't be updated
        if detail.get("result") != 1:
            print(
                f"workshop item {item} isn't available: result {detail.get('result')}",
                file=sys.stderr,
            )
            continue
        current = detail.get("hcontent_file")
        if all(
            held.get(source, {}).get(str(item)) == current
            for source in sources[int(item)]
        ):
            continue
        newest = layers.latest(layers.folder(state / game, f"item-{item}"))
        if newest is None:
            updates.append(
                f"workshop item {item} ({detail.get('title')}): not installed"
            )
        elif layers.version_of(newest).split(".", 1)[1] != current:
            updates.append(
                f"workshop item {item} ({detail.get('title')}): manifest {current}"
            )
    return updates


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


if __name__ == "__main__":
    sys.exit(main())
