"""The games the tools support, and what they find out about an install of one.

Of a game, only its dedicated server's app is kept here. Everything else comes from Steam or from the
files: the depots from the app (DepotDownloader picks them), the workshop's app from the items
(the Web API's consumer_app_id), the game's folder from the install, the folder with gameinfo.txt.
A game's name is the name of its folder.

The configs, servers/ and game/ of a repository like this one, come from config sources, e.g. a
community's: the repository and its branch or tag of NWI_SOURCES_DIR/<source>.env
(/etc/nwi-server/configs), URL=… and REF=…, whose newest version the updater keeps in its state,
NWI_LAYERS/config-<source>.v (NWI_LAYERS is /var/lib/nwi-server/layers by default, see layers.py). A server's source is
CONFIG_SOURCE of its environment file, "default" without one. With NWI_CONFIG, or for the tools of a
checkout, there's one source for all servers: that folder, or the checkout the tools are in.

The servers, whose games are installed and whose workshop items are downloaded, are found, in this
order: the configs of servers/ in NWI_SERVER_CONFIGS, separated by spaces (e.g. a test instance's);
the environment files of NWI_SERVERS_DIR (/etc/nwi-server by default), <server>.env each, if there
is one; every config of the default source's servers/ otherwise. A server's game is its server.toml's (game), or GAME of
its environment file without one, Day of Infamy by default; its workshop items those of its
server.toml's list (workshop).

The commands: cli/games.py.
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import layers

# The games by the names of their folders, with the apps of their dedicated servers
SERVER_APPS = {
    "doi": 462310,
    "insurgency": 237410,
}
DEFAULT = "doi"
# The checkout the package is in, if it's run from one: src/nwi_server_kit/ of this repository
CHECKOUT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = "default"
SOURCE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def single_config() -> Path | None:
    """The one folder of configs for all sources, if there is one: NWI_CONFIG, or the checkout the tools
    are in."""
    if os.environ.get("NWI_CONFIG"):
        return Path(os.environ["NWI_CONFIG"])
    return CHECKOUT if (CHECKOUT / "servers").is_dir() else None


def config_folder(source: str = DEFAULT_SOURCE, pick: bool = False) -> Path:
    """The folder of a config source's configs, see the module's documentation: of the updater's
    versions the newest, or with PICK the one a server mounts (layers.pick())."""
    if not SOURCE_NAME.fullmatch(source):
        raise ValueError(f"not a config source's name: {source}")
    single = single_config()
    if single is not None:
        return single
    state = Path(os.environ.get("NWI_LAYERS", "/var/lib/nwi-server/layers"))
    layer = layers.folder(state, f"config-{source}")
    newest = layers.pick(layer) if pick else layers.latest(layer)
    if newest is None:
        raise ValueError(f"the config source {source} has no version yet, update first")
    return newest


DETAILS_URL = (
    "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
)


@dataclass
class Server:
    """A server: its name, its config source, its config of servers/ (if it has one), its game, its
    workshop list."""

    name: str
    source: str
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


def server(name: str, env: dict[str, str], pick: bool = False) -> Server:
    """The server of the name, with the variables of its environment file; with PICK, of the version
    of its configs that it mounts."""
    # Imported here: server_config imports this module
    from .server_config import load

    # One source with one folder of configs for all, e.g. a container image's
    source = (
        DEFAULT_SOURCE
        if single_config()
        else env.get("CONFIG_SOURCE") or DEFAULT_SOURCE
    )
    configs = config_folder(source, pick)
    config = env.get("SERVER_CONFIG_NAME") or env.get("SERVER_NAME") or name
    toml = configs / "servers" / config / "server.toml"
    if not toml.is_file():
        if "SERVER_CONFIG_NAME" in env:
            raise ValueError(f"{name}: the config {config} of {source} is unknown")
        game = env.get("GAME", DEFAULT)
        if game not in SERVER_APPS:
            raise ValueError(
                f"{name}: GAME is one of {', '.join(SERVER_APPS)}, not {game}"
            )
        return Server(name, source, None, game, None)
    settings = load(toml)
    workshop = settings.get("workshop")
    return Server(
        name,
        source,
        config,
        settings.get("game", DEFAULT),
        configs / "game/cfg" / workshop if workshop else None,
    )


def source_file(source: str) -> Path:
    """A config source's settings file."""
    folder = Path(os.environ.get("NWI_SOURCES_DIR", "/etc/nwi-server/configs"))
    return folder / f"{source}.env"


def source_settings(source: str) -> tuple[str, str]:
    """The repository and the branch or tag of a config source, from its file; empty without."""
    path = source_file(source)
    settings = read_env(path) if path.is_file() else {}
    return settings.get("URL", ""), settings.get("REF", "")


def server_envs() -> dict[str, dict[str, str]]:
    """The servers' environment files' variables by the servers' names."""
    folder = Path(os.environ.get("NWI_SERVERS_DIR", "/etc/nwi-server"))
    envs = sorted(folder.glob("*.env")) if folder.is_dir() else []
    return {env.stem: read_env(env) for env in envs}


def env_sources() -> list[str]:
    """The config sources the servers' environment files name, the default one without any: read
    without the clones, so before they're made."""
    if os.environ.get("NWI_SERVER_CONFIGS") is not None or single_config() is not None:
        return [DEFAULT_SOURCE]
    names = {
        env.get("CONFIG_SOURCE") or DEFAULT_SOURCE for env in server_envs().values()
    }
    return sorted(names) or [DEFAULT_SOURCE]


def servers() -> list[Server]:
    """The servers, see the module's documentation."""
    configs = os.environ.get("NWI_SERVER_CONFIGS")
    if configs is not None:
        return [
            server(config, {"SERVER_CONFIG_NAME": config}) for config in configs.split()
        ]
    envs = server_envs()
    if envs:
        return [server(name, env) for name, env in envs.items()]
    return [
        server(toml.parent.name, {"SERVER_CONFIG_NAME": toml.parent.name})
        for toml in sorted((config_folder() / "servers").glob("*/server.toml"))
    ]


def used_games(found: list[Server]) -> list[str]:
    """The games of the servers, in the order of SERVER_APPS; Day of Infamy without servers."""
    games = {found_server.game for found_server in found}
    return [game for game in SERVER_APPS if game in games] or [DEFAULT]


def workshop_items(found: list[Server], game: str) -> list[int]:
    """The workshop items of the game's servers' lists."""
    return sorted(item_sources(found, game))


def item_sources(found: list[Server], game: str) -> dict[int, set[str]]:
    """The workshop items of the game's servers' lists, with the config sources of the servers that list
    them."""
    items: dict[int, set[str]] = {}
    for found_server in found:
        if found_server.game == game and found_server.workshop is not None:
            text = found_server.workshop.read_text()
            for match in re.finditer(r"^(\d+)", text, re.MULTILINE):
                items.setdefault(int(match[1]), set()).add(found_server.source)
    return items


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


def downloaded_manifest(folder: Path, app: int) -> str | None:
    """The manifest of a workshop item that DepotDownloader downloaded into the folder, the latest of
    its record, .DepotDownloader/<app>_<manifest>.manifest."""
    records = sorted(
        folder.glob(f".DepotDownloader/{app}_*.manifest"),
        key=lambda path: path.stat().st_mtime,
    )
    return records[-1].stem.split("_", 1)[1] if records else None


def workshop_record(workshop: Path, app: int) -> None:
    """Write appworkshop_<app>.acf of the items in workshop, see main()'s usage."""
    content = workshop / "steamapps/workshop/content" / str(app)
    folders = sorted(
        path for path in content.glob("*") if path.is_dir() and path.name.isdigit()
    )
    times = {
        int(detail["publishedfileid"]): int(detail.get("time_updated", 0))
        for detail in item_details([int(folder.name) for folder in folders])
        if detail.get("result") == 1
    }
    installed, details, total = [], [], 0
    now = int(time.time())
    for folder in folders:
        manifest = downloaded_manifest(folder, app)
        if manifest is None:
            continue
        item = int(folder.name)
        size = sum(
            path.stat().st_size
            for path in folder.rglob("*")
            if path.is_file()
            and ".DepotDownloader" not in path.relative_to(folder).parts
        )
        total += size
        updated = times.get(item, 0)
        installed.append(
            f'\t\t"{item}"\n\t\t{{\n\t\t\t"size"\t\t"{size}"\n'
            f'\t\t\t"timeupdated"\t\t"{updated}"\n\t\t\t"manifest"\t\t"{manifest}"\n\t\t}}\n'
        )
        details.append(
            f'\t\t"{item}"\n\t\t{{\n\t\t\t"manifest"\t\t"{manifest}"\n'
            f'\t\t\t"timeupdated"\t\t"{updated}"\n\t\t\t"timetouched"\t\t"{now}"\n'
            f'\t\t\t"latest_timeupdated"\t\t"{updated}"\n'
            f'\t\t\t"latest_manifest"\t\t"{manifest}"\n\t\t}}\n'
        )
    header = [("appid", app), ("SizeOnDisk", total)] + [
        (key, 0)
        for key in (
            "NeedsUpdate",
            "NeedsDownload",
            "TimeLastUpdated",
            "TimeLastFullCheck",
            "TimeLastAppRan",
            "LastBuildID",
        )
    ]
    text = '"AppWorkshop"\n{\n'
    text += "".join(f'\t"{key}"\t\t"{value}"\n' for key, value in header)
    text += '\t"WorkshopItemsInstalled"\n\t{\n' + "".join(installed) + "\t}\n"
    text += '\t"WorkshopItemDetails"\n\t{\n' + "".join(details) + "\t}\n}\n"
    record = workshop / f"steamapps/workshop/appworkshop_{app}.acf"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(text)


def known(game: str) -> str:
    """The game, if it's one of the tools."""
    if game not in SERVER_APPS:
        raise ValueError(f"{game} isn't a game of the tools")
    return game
