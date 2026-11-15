"""A server's settings, servers/<name>/server.toml, for its start.

The file says what the server is; its machine's settings and secrets (ports, passwords) are in its
environment file instead (/etc/nwi-server/<server>.env). Its keys, the paths relative to the game's cfg
folder:

    game            optional: the game, by the name of its folder, "doi" (Day of Infamy, the default)
                    or "insurgency"; the server's install has to be one of it
    hostname        the server's name in the server browser; SourceTV's is "<hostname> | SourceTV"
    startup_map     the first map and its game mode, e.g. "bastogne stronghold"
    playlist        optional: the playlist (+sv_playlist), e.g. "nwi/coop_commando"; its config of the
                    settings we take over, doi-config/playlists/<playlist>.cfg, which tools/make_mods.py
                    makes, runs in server.cfg
    ruleset         optional, with a playlist: its ruleset (+sv_ruleset), e.g. "american_campaign" of
                    nwi/coop_commando; the playlist's default one without
    theater         optional: the theater to use instead of the game's (mp_theater_override)
    mapcycle        optional: the maps the server cycles through (mapcyclefile)
    workshop        optional: the list of workshop items, which becomes the server's
                    subscribed_file_ids.txt, the list the game downloads and mounts by default;
                    without one, the server starts without the workshop (-workshop)
    maxplayers      optional: the server's slots (+maxplayers), 64 by default; the configs may lower
                    them for the game modes, e.g. maxplayers 33 of basic_coop.cfg
    lan             optional: true for a server only for its local network (+sv_lan 1), false by
                    default
    launch_options  optional: more options of the server's command line, e.g. ["-tickrate", "128"]
    configs_before  optional: configs to run before ours
    configs_after   optional: configs to run after ours, e.g. ["doi-config/basic_coop.cfg"]

The server.cfg it makes runs, in this order, so that a later one's setting replaces an earlier one's:
configs_before, doi-config/tv_settings.cfg, the playlist's config, doi-config/basic_settings.cfg,
configs_after. The game modes' configs run at every map start, after these (nwi_mode_config.sp).

The playlist and its ruleset are on the command line, before +map, so that the game applies the
playlist's "cvars" on the first map as on every map change: before server.cfg, which our settings
then replace where we have some. Set in server.cfg, the playlist came too late for that on the first
map. The game takes the playlist only once the plugins are loaded, so nwi_playlist_unlock's
replacements are in place and the game's forced settings are never applied.

Usage, with GAME the game's folder of the install ROOT (nwi_server_kit.games):
    nwi-server server-config prepare ROOT   write ROOT/GAME/cfg/server.cfg and ROOT/GAME/subscribed_file_ids.txt
                                    from ROOT/GAME/server.toml (tools/prepare_server.sh)
    nwi-server server-config args ROOT      print the command line's options of ROOT/GAME/server.toml, one per
                                    line (tools/start_server.sh)
    nwi-server server-config game FILE      print the game of a server.toml
    nwi-server server-config check FILE...  check server.toml files: their keys, and that the configs and lists
                                    they name exist in game/cfg of the configs (NWI_CONFIG, see
                                    nwi_server_kit.games)
"""

import shutil
import sys
import tomllib
from pathlib import Path

from .games import DEFAULT, SERVER_APPS, config_folder, game_folder

# The keys and their types
KEYS = {
    "game": str,
    "hostname": str,
    "startup_map": str,
    "playlist": str,
    "ruleset": str,
    "theater": str,
    "mapcycle": str,
    "workshop": str,
    "maxplayers": int,
    "lan": bool,
    "launch_options": list,
    "configs_before": list,
    "configs_after": list,
}
REQUIRED = ("hostname", "startup_map")
KINDS = {
    str: "a string",
    int: "a number",
    bool: "true or false",
    list: "a list of strings",
}


def load(path: Path) -> dict:
    """The settings of a server.toml; an error for unknown keys, wrong types or missing keys."""
    with path.open("rb") as file:
        settings = tomllib.load(file)
    errors = [f"{path}: unknown key {key}" for key in settings if key not in KEYS]
    errors += [f"{path}: {key} is missing" for key in REQUIRED if key not in settings]
    for key, kind in KEYS.items():
        value = settings.get(key)
        if value is None:
            continue
        # bool is an int to Python, but not to TOML
        wrong = not isinstance(value, kind) or (kind is int and isinstance(value, bool))
        if kind is list and not wrong:
            wrong = not all(isinstance(item, str) for item in value)
        if wrong:
            errors.append(f"{path}: {key} is {KINDS[kind]}")
    if settings.get("game", DEFAULT) not in SERVER_APPS:
        games = ", ".join(SERVER_APPS)
        errors.append(f"{path}: game is one of {games}, not {settings['game']}")
    if "ruleset" in settings and "playlist" not in settings:
        errors.append(f"{path}: a ruleset needs a playlist")
    if errors:
        raise ValueError("\n".join(errors))
    return settings


def quote(value: str) -> str:
    """A config's argument, quoted as the game writes it; a quote can't be in one."""
    if '"' in value:
        raise ValueError(f"a config's value can't have a quote: {value}")
    return f'"{value}"'


def server_cfg(settings: dict) -> str:
    """The server.cfg of the settings."""
    hostname = settings["hostname"]
    lines = [
        "// Made by nwi-server-kit (server_config.py) from server.toml at each start of the server;",
        "// change server.toml instead",
        f"hostname {quote(hostname)}",
        f"tv_name {quote(hostname + ' | SourceTV')}",
        f"tv_title {quote(hostname + ' | SourceTV')}",
    ]
    configs = list(settings.get("configs_before", []))
    configs.append("doi-config/tv_settings.cfg")
    lines += [f"exec {quote(config)}" for config in configs]
    configs = []
    if "playlist" in settings:
        configs.append(f"doi-config/playlists/{settings['playlist']}.cfg")
    configs.append("doi-config/basic_settings.cfg")
    configs += settings.get("configs_after", [])
    lines += [f"exec {quote(config)}" for config in configs]
    if "mapcycle" in settings:
        lines.append(f"mapcyclefile {quote('cfg/' + settings['mapcycle'])}")
    return "\n".join(lines) + "\n"


def server_settings(root: Path) -> tuple[Path, dict]:
    """The game's folder of the install and the settings of its server.toml, which has to be of the
    install's game."""
    folder = game_folder(root)
    path = folder / "server.toml"
    settings = load(path)
    game = settings.get("game", DEFAULT)
    if game != folder.name:
        raise ValueError(
            f"{path}: the server is of {game}, the install of {folder.name}"
        )
    return folder, settings


def prepare(root: Path) -> None:
    folder, settings = server_settings(root)
    (folder / "cfg" / "server.cfg").write_text(server_cfg(settings))
    workshop = folder / "subscribed_file_ids.txt"
    workshop.unlink(missing_ok=True)
    if "workshop" in settings:
        shutil.copyfile(folder / "cfg" / settings["workshop"], workshop)


def args(root: Path) -> None:
    _, settings = server_settings(root)
    options = ["+maxplayers", str(settings.get("maxplayers", 64))]
    options += ["+sv_lan", "1" if settings.get("lan", False) else "0"]
    if "workshop" in settings:
        options.append("-workshop")
    if "ruleset" in settings:
        options += ["+sv_ruleset", settings["ruleset"]]
    if "playlist" in settings:
        options += ["+sv_playlist", settings["playlist"]]
    options += ["+map", settings["startup_map"]]
    if "theater" in settings:
        options += ["+mp_theater_override", settings["theater"]]
    options += settings.get("launch_options", [])
    for option in options:
        if "\n" in option:
            raise ValueError(f"an option can't have a line break: {option!r}")
        print(option)


def check(paths: list[Path]) -> int:
    status = 0
    cfg = config_folder() / "game" / "cfg"
    for path in paths:
        try:
            settings = load(path)
            server_cfg(settings)
        except (ValueError, tomllib.TOMLDecodeError) as error:
            print(error)
            status = 1
            continue
        named = settings.get("configs_before", []) + settings.get("configs_after", [])
        named += [settings[key] for key in ("mapcycle", "workshop") if key in settings]
        for name in named:
            if not (cfg / name).is_file():
                print(f"{path}: there's no game/cfg/{name}")
                status = 1
    return status


def main(argv: list[str] | None = None) -> int:
    # Not "args", the function of the command args
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) < 2 or arguments[0] not in ("prepare", "args", "game", "check"):
        print(__doc__.split("Usage:")[1], file=sys.stderr)
        return 2
    command, operands = arguments[0], [Path(arg) for arg in arguments[1:]]
    if command == "check":
        return check(operands)
    try:
        if command == "game":
            print(load(operands[0]).get("game", DEFAULT))
        else:
            (prepare if command == "prepare" else args)(operands[0])
    except (ValueError, OSError, tomllib.TOMLDecodeError) as error:
        print(f"nwi-server server-config: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
