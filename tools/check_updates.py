#!/usr/bin/env python3
"""Check whether the game or the workshop items have updates, without downloading them.

The game: each depot of the installed dedicated server (steamapps/appmanifest_462310.acf) against the
public branch's manifest from SteamCMD's app info. The depots, not the build ID, as the shared depot
1006, the Steam client library (steamclient.so), changes without a new build of the game.

The workshop items: each item of the workshop-ids-*.txt files against the Steam Web API's current
manifest of the item (GetPublishedFileDetails, no key needed), which SteamCMD's manifest of the
installed items (steamapps/workshop/appworkshop_447820.acf) records too. An item of a list that isn't
installed counts as an update.

Exit status: 0 if there are updates, which it lists, 1 if there are none, 255 if it can't tell, e.g.
without a connection. For systemd's ExecCondition=, which skips the unit on 1 and fails it on 255.

Usage: check_updates.py --game DIR --workshop DIR
"""

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

SERVER_APP = 462310
GAME_APP = 447820
DETAILS_URL = (
    "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
)
LISTS = Path(__file__).resolve().parent.parent / "game/cfg/doi-config"

UPDATES = 0
NO_UPDATES = 1
UNKNOWN = 255

TOKEN = re.compile(r'"(?P<quoted>[^"\n]*)"|(?P<brace>[{}])')

# Steam's text KeyValues (VDF): a key's value is a string or a dict
Tree = dict[str, "str | Tree"]


def parse_vdf(text: str) -> Tree:
    """Parse Steam's VDF text into dicts, later keys replacing earlier ones."""
    stack: list[Tree] = [{}]
    key = None
    for match in TOKEN.finditer(text):
        if match["brace"] == "{":
            if key is None:
                raise ValueError("a block without a key")
            block: Tree = {}
            stack[-1][key] = block
            stack.append(block)
            key = None
        elif match["brace"] == "}":
            if len(stack) == 1:
                raise ValueError("a closing brace too many")
            stack.pop()
        elif key is None:
            key = match["quoted"]
        else:
            stack[-1][key] = match["quoted"]
            key = None
    if len(stack) != 1:
        raise ValueError("a block isn't closed")
    return stack[0]


def block(tree: "str | Tree", *keys: str) -> Tree:
    """The block at the keys' path; an empty one if it's missing."""
    for key in keys:
        if not isinstance(tree, dict) or not isinstance(tree.get(key), dict):
            return {}
        tree = tree[key]
    return tree if isinstance(tree, dict) else {}


def game_updates(game: Path) -> list[str]:
    """The installed depots whose manifest isn't the public branch's any more."""
    manifest = game / f"steamapps/appmanifest_{SERVER_APP}.acf"
    installed = block(parse_vdf(manifest.read_text()), "AppState", "InstalledDepots")
    # A fresh app info: SteamCMD caches it otherwise
    output = subprocess.run(
        [
            "steamcmd",
            "+login",
            "anonymous",
            "+app_info_update",
            "1",
            "+app_info_print",
            str(SERVER_APP),
            "+quit",
        ],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
        check=False,
    ).stdout
    # The app info is SteamCMD's output from the app's ID on its own line to the block's end
    start = re.search(rf'^"{SERVER_APP}"$', output, re.MULTILINE)
    if start is None:
        raise ValueError("SteamCMD printed no app info")
    depots = block(parse_vdf(output[start.start() :]), str(SERVER_APP), "depots")
    if not depots:
        raise ValueError("SteamCMD's app info has no depots")
    updates = []
    for depot, info in installed.items():
        current = block(depots, depot, "manifests", "public").get("gid")
        if current is None:
            raise ValueError(f"the app info has no public manifest of depot {depot}")
        if not isinstance(info, dict) or info.get("manifest") != current:
            updates.append(f"depot {depot}: manifest {current}")
    return updates


def workshop_updates(workshop: Path) -> list[str]:
    """The items of the lists whose installed manifest isn't the current one, or that aren't installed."""
    items = sorted(
        {
            match[1]
            for path in LISTS.glob("workshop-ids-*.txt")
            for match in re.finditer(r"^(\d+)", path.read_text(), re.MULTILINE)
        }
    )
    if not items:
        return []
    manifest = workshop / f"steamapps/workshop/appworkshop_{GAME_APP}.acf"
    installed = (
        block(parse_vdf(manifest.read_text()), "AppWorkshop", "WorkshopItemsInstalled")
        if manifest.is_file()
        else {}
    )
    fields = {"itemcount": len(items)}
    fields.update({f"publishedfileids[{i}]": item for i, item in enumerate(items)})
    request = urllib.request.Request(
        DETAILS_URL, data=urllib.parse.urlencode(fields).encode()
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        details = json.load(response)["response"]["publishedfiledetails"]
    updates = []
    for detail in details:
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
        description="Check the game and the workshop items for updates."
    )
    parser.add_argument(
        "--game", type=Path, required=True, help="the dedicated server's install"
    )
    parser.add_argument(
        "--workshop",
        type=Path,
        required=True,
        help="SteamCMD's folder of the workshop items",
    )
    arguments = parser.parse_args()
    try:
        updates = game_updates(arguments.game) + workshop_updates(arguments.workshop)
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
