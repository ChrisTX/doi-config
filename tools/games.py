#!/usr/bin/env python3
"""The games the tools support, and what they find out about an install of one.

Of a game, only its dedicated server's app is kept here. Everything else comes from Steam or from the
files: the depots from the app (DepotDownloader picks them), the workshop's app from the items
(the Web API's consumer_app_id), the game's folder from the install, the folder with gameinfo.txt.
A game's name is the name of its folder.

The configs, servers/ and game/ of this repository, are those of DOI_CONFIG: a clone of it, by default
the checkout the tools are in, or /var/lib/doi-server/doi-config, the servers' clone, for the
installed tools (make install).

The servers, whose games are installed and whose workshop items are downloaded, are found, in this
order: the configs of servers/ in DOI_SERVER_CONFIGS, separated by spaces (e.g. a test instance's);
the environment files of DOI_SERVERS_DIR (/etc/doi-server by default), <server>.env each, if there
is one; every config of servers/ otherwise. A server's game is its server.toml's (game), or GAME of
its environment file without one, Day of Infamy by default; its workshop items those of its
server.toml's list (workshop).

Usage:
    games.py config            print the folder of the configs (DOI_CONFIG)
    games.py app GAME          print the dedicated server's app of the game, e.g. 462310 of doi
    games.py folder INSTALL    print the name of the game's folder of an install, e.g. doi
    games.py server NAME       print the game of the server NAME
    games.py used              print the games of the servers, one per line
    games.py servers GAME      print the names of the game's servers, one per line
    games.py items GAME        print the workshop items of the game's servers, one per line as
                               "<app> <item>", the app being the workshop's, from the Web API; an
                               error if they're not all of one app, e.g. an item of another game
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# The games by the names of their folders, with the apps of their dedicated servers
SERVER_APPS = {
    "doi": 462310,
    "insurgency": 237410,
}
DEFAULT = "doi"
TOOLS = Path(__file__).resolve().parent
CLONE = Path("/var/lib/doi-server/doi-config")


def config_folder() -> Path:
    """The folder of the configs, see the module's documentation."""
    if os.environ.get("DOI_CONFIG"):
        return Path(os.environ["DOI_CONFIG"])
    return TOOLS.parent if (TOOLS.parent / "servers").is_dir() else CLONE


CONFIG = config_folder()
DETAILS_URL = (
    "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
)


@dataclass
class Server:
    """A server: its name, its config of servers/ (if it has one), its game, its workshop list."""

    name: str
    config: str | None
    game: str
    workshop: Path | None


def read_env(path: Path) -> dict[str, str]:
    """The variables of an environment file, as systemd's EnvironmentFile= reads simple ones:
    VAR=value a line, the value optionally quoted, comments with #."""
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        env[key.strip()] = value
    return env


def server(name: str, env: dict[str, str]) -> Server:
    """The server of the name, with the variables of its environment file."""
    # Imported here: server_config imports this module
    from server_config import load

    config = env.get("SERVER_CONFIG_NAME") or env.get("SERVER_NAME") or name
    toml = CONFIG / "servers" / config / "server.toml"
    if not toml.is_file():
        if "SERVER_CONFIG_NAME" in env:
            raise ValueError(f"{name}: the config {config} is unknown")
        game = env.get("GAME", DEFAULT)
        if game not in SERVER_APPS:
            raise ValueError(
                f"{name}: GAME is one of {', '.join(SERVER_APPS)}, not {game}"
            )
        return Server(name, None, game, None)
    settings = load(toml)
    workshop = settings.get("workshop")
    return Server(
        name,
        config,
        settings.get("game", DEFAULT),
        CONFIG / "game/cfg" / workshop if workshop else None,
    )


def servers() -> list[Server]:
    """The servers, see the module's documentation."""
    configs = os.environ.get("DOI_SERVER_CONFIGS")
    if configs is not None:
        return [
            server(config, {"SERVER_CONFIG_NAME": config}) for config in configs.split()
        ]
    folder = Path(os.environ.get("DOI_SERVERS_DIR", "/etc/doi-server"))
    envs = sorted(folder.glob("*.env")) if folder.is_dir() else []
    if envs:
        return [server(env.stem, read_env(env)) for env in envs]
    return [
        server(toml.parent.name, {"SERVER_CONFIG_NAME": toml.parent.name})
        for toml in sorted((CONFIG / "servers").glob("*/server.toml"))
    ]


def used_games(found: list[Server]) -> list[str]:
    """The games of the servers, in the order of SERVER_APPS; Day of Infamy without servers."""
    games = {found_server.game for found_server in found}
    return [game for game in SERVER_APPS if game in games] or [DEFAULT]


def workshop_items(found: list[Server], game: str) -> list[int]:
    """The workshop items of the game's servers' lists."""
    items = set()
    for found_server in found:
        if found_server.game == game and found_server.workshop is not None:
            text = found_server.workshop.read_text()
            items |= {
                int(match[1]) for match in re.finditer(r"^(\d+)", text, re.MULTILINE)
            }
    return sorted(items)


def item_details(items: list[int]) -> list[dict]:
    """The Web API's details of the workshop items (GetPublishedFileDetails, no key needed)."""
    if not items:
        return []
    fields = {"itemcount": len(items)}
    fields.update({f"publishedfileids[{i}]": item for i, item in enumerate(items)})
    request = urllib.request.Request(
        DETAILS_URL, data=urllib.parse.urlencode(fields).encode()
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)["response"]["publishedfiledetails"]


def workshop_app(items: list[int]) -> int | None:
    """The workshop's app of the items, which all have to be of one; None without items. An item that
    isn't available (any more) has no app and doesn't count."""
    apps: dict[int, list[str]] = {}
    for detail in item_details(items):
        if detail.get("result") == 1:
            apps.setdefault(detail["consumer_app_id"], []).append(
                detail["publishedfileid"]
            )
    if len(apps) > 1:
        listed = "; ".join(f"app {app}: {', '.join(ids)}" for app, ids in apps.items())
        raise ValueError(f"the workshop items aren't of one game: {listed}")
    return next(iter(apps), None)


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


def known(game: str) -> str:
    """The game, if it's one of the tools."""
    if game not in SERVER_APPS:
        raise ValueError(f"{game} isn't a game of the tools")
    return game


def main() -> int:
    operands = {
        "config": 0,
        "app": 1,
        "folder": 1,
        "server": 1,
        "used": 0,
        "servers": 1,
        "items": 1,
    }
    if len(sys.argv) < 2 or operands.get(sys.argv[1]) != len(sys.argv) - 2:
        print(__doc__.split("Usage:")[1], file=sys.stderr)
        return 2
    command, operand = sys.argv[1], (sys.argv[2:] or [""])[0]
    try:
        if command == "config":
            print(CONFIG)
        elif command == "app":
            print(SERVER_APPS[known(operand)])
        elif command == "folder":
            print(game_folder(Path(operand)).name)
        elif command == "server":
            folder = Path(os.environ.get("DOI_SERVERS_DIR", "/etc/doi-server"))
            env = folder / f"{operand}.env"
            print(server(operand, read_env(env) if env.is_file() else {}).game)
        elif command == "used":
            print("\n".join(used_games(servers())))
        elif command == "servers":
            game = known(operand)
            names = [found.name for found in servers() if found.game == game]
            print("\n".join(names), end="\n" if names else "")
        else:
            items = workshop_items(servers(), known(operand))
            app = workshop_app(items)
            if items and app is None:
                raise ValueError("none of the workshop items is available")
            for item in items:
                print(app, item)
    except (ValueError, OSError) as error:
        print(f"games.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
