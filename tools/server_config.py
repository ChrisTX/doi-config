#!/usr/bin/env python3
"""A server's settings, servers/<name>/server.toml, for its start.

The file says what the server is; its machine's settings and secrets (ports, passwords) are in its
environment file instead (/etc/doi-server/<server>.env). Its keys, the paths relative to the game's cfg
folder:

    hostname        the server's name in the server browser; SourceTV's is "<hostname> | SourceTV"
    startup_map     the first map and its game mode, e.g. "bastogne stronghold"
    playlist        optional: the playlist (sv_playlist), e.g. "nwi/coop_commando", whose config of the
                    settings we take over, doi-config/playlists/<playlist>.cfg, tools/make_mods.py makes
    theater         optional: the theater to use instead of the game's (mp_theater_override)
    mapcycle        optional: the maps the server cycles through (mapcyclefile)
    workshop        optional: the list of workshop items, which becomes the server's
                    subscribed_file_ids.txt, the list the game downloads and mounts by default
    launch_options  optional: more options of the server's command line, e.g. ["-tickrate", "128"]
    configs_before  optional: configs to run before ours
    configs_after   optional: configs to run after ours, e.g. ["doi-config/basic_coop.cfg"]

The server.cfg it makes runs, in this order, so that a later one's setting replaces an earlier one's:
configs_before, doi-config/tv_settings.cfg, the playlist's config, doi-config/basic_settings.cfg,
configs_after. The game modes' configs run at every map start, after these (nwi_mode_config.sp).

Usage:
    server_config.py prepare ROOT   write ROOT/doi/cfg/server.cfg and ROOT/doi/subscribed_file_ids.txt
                                    from ROOT/doi/server.toml (tools/prepare_server.sh)
    server_config.py args ROOT      print the command line's options of ROOT/doi/server.toml, one per
                                    line (tools/start_server.sh)
    server_config.py check FILE...  check server.toml files: their keys, and that the configs and lists
                                    they name exist in game/cfg of this repository
"""

import shutil
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# The keys and their types
KEYS = {
    "hostname": str,
    "startup_map": str,
    "playlist": str,
    "theater": str,
    "mapcycle": str,
    "workshop": str,
    "launch_options": list,
    "configs_before": list,
    "configs_after": list,
}
REQUIRED = ("hostname", "startup_map")


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
        if not isinstance(value, kind) or (
            kind is list and not all(isinstance(item, str) for item in value)
        ):
            errors.append(
                f"{path}: {key} is a {'list of strings' if kind is list else 'string'}"
            )
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
        "// Made by tools/server_config.py of doi-config from server.toml at each start of the server;",
        "// change server.toml instead",
        f"hostname {quote(hostname)}",
        f"tv_name {quote(hostname + ' | SourceTV')}",
        f"tv_title {quote(hostname + ' | SourceTV')}",
    ]
    configs = list(settings.get("configs_before", []))
    configs.append("doi-config/tv_settings.cfg")
    if "playlist" in settings:
        configs.append(f"doi-config/playlists/{settings['playlist']}.cfg")
    configs.append("doi-config/basic_settings.cfg")
    configs += settings.get("configs_after", [])
    lines += [f"exec {quote(config)}" for config in configs]
    if "mapcycle" in settings:
        lines.append(f"mapcyclefile {quote('cfg/' + settings['mapcycle'])}")
    return "\n".join(lines) + "\n"


def prepare(root: Path) -> None:
    doi = root / "doi"
    settings = load(doi / "server.toml")
    (doi / "cfg" / "server.cfg").write_text(server_cfg(settings))
    workshop = doi / "subscribed_file_ids.txt"
    workshop.unlink(missing_ok=True)
    if "workshop" in settings:
        shutil.copyfile(doi / "cfg" / settings["workshop"], workshop)


def args(root: Path) -> None:
    settings = load(root / "doi" / "server.toml")
    options = ["+map", settings["startup_map"]]
    if "theater" in settings:
        options += ["+mp_theater_override", settings["theater"]]
    options += settings.get("launch_options", [])
    for option in options:
        if "\n" in option:
            raise ValueError(f"an option can't have a line break: {option!r}")
        print(option)


def check(paths: list[Path]) -> int:
    status = 0
    cfg = REPO / "game" / "cfg"
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


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] not in ("prepare", "args", "check"):
        print(__doc__.split("Usage:")[1], file=sys.stderr)
        return 2
    command, operands = sys.argv[1], [Path(arg) for arg in sys.argv[2:]]
    if command == "check":
        return check(operands)
    try:
        (prepare if command == "prepare" else args)(operands[0])
    except (ValueError, OSError, tomllib.TOMLDecodeError) as error:
        print(f"server_config.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
