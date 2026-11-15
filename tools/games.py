#!/usr/bin/env python3
"""The games the tools support, and what they find out about an install of one.

Of a game, only its dedicated server's app is kept here. Everything else comes from Steam or from the
files: the depots from the app (DepotDownloader picks them), the workshop's app from the items
(the Web API's consumer_app_id), the game's folder from the install, the folder with gameinfo.txt.
A game's name is the name of its folder.

Usage:
    games.py app GAME        print the dedicated server's app of the game, e.g. 462310 of doi
    games.py folder INSTALL  print the name of the game's folder of an install, e.g. doi
"""

import sys
from pathlib import Path

# The games by the names of their folders, with the apps of their dedicated servers
SERVER_APPS = {
    "doi": 462310,
    "insurgency": 237410,
}
DEFAULT = "doi"


def game_folder(install: Path) -> Path:
    """The game's folder of an install: the one folder in it with gameinfo.txt, of a game of
    SERVER_APPS."""
    folders = sorted(path.parent for path in install.glob("*/gameinfo.txt"))
    if len(folders) != 1:
        found = ", ".join(path.name for path in folders) or "none"
        raise ValueError(f"{install}: not one game folder with gameinfo.txt: {found}")
    if folders[0].name not in SERVER_APPS:
        raise ValueError(f"{install}: {folders[0].name} isn't a game of the tools")
    return folders[0]


def item_folder(workshop: Path, item: int) -> Path | None:
    """The folder of a workshop item in a folder of workshop items (steamapps/workshop/content/<app>/
    <item>), of whichever app: the items' IDs are unique across them. None if it isn't there."""
    return next(
        iter(sorted(workshop.glob(f"steamapps/workshop/content/*/{item}"))), None
    )


def item_folders(workshop: Path) -> list[Path]:
    """The folders of all workshop items in a folder of workshop items."""
    return sorted(
        path
        for path in workshop.glob("steamapps/workshop/content/*/*")
        if path.is_dir()
    )


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("app", "folder"):
        print(__doc__.split("Usage:")[1], file=sys.stderr)
        return 2
    command, operand = sys.argv[1:]
    try:
        if command == "app":
            if operand not in SERVER_APPS:
                raise ValueError(f"{operand} isn't a game of the tools")
            print(SERVER_APPS[operand])
        else:
            print(game_folder(Path(operand)).name)
    except ValueError as error:
        print(f"games.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
