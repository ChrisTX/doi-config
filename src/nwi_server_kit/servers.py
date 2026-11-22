"""Setting up a server: the configs a config source offers, and a new server's environment file.

A server is its environment file, <server>.env of the servers' folder (/etc/nwi-server for the systemd
units, ~/.config/nwi-server for the Quadlet units), see games.py. add() writes one: the server's
config of its source, its game, and ports no other server of the folder uses. The game is its
config's (server.toml's game, or its source's, games.source_game()); a server without a config names
its own (GAME).

The configs are those of the source's newest version in the updater's state, or, before the first
update, a shallow clone of its repository (its URL and REF), which is removed again; with NWI_CONFIG,
or for the tools of a checkout, that folder's (games.single_config()).

The commands: cli/servers.py.
"""

import os
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import games
from .server_config import load

# The ports of a server's environment file, with the defaults the launcher takes without them
# (launch.py): the game's (UDP, and RCON's TCP), SourceTV's and the client's
PORTS = {"SERVER_PORT": 27015, "TV_PORT": 27020, "CLIENT_PORT": 27005}


@dataclass
class Config:
    """A config of a source's servers/: its name, its game and its server's name."""

    name: str
    game: str
    hostname: str


@dataclass
class Plan:
    """A new server: its name, its config source, its config (None for a server without one), its game
    and why it's that one, its ports and its environment file."""

    name: str
    source: str
    config: str | None
    game: str
    reason: str
    ports: dict[str, int]
    path: Path


def user_dir() -> Path:
    """The folder of the Quadlet units' environment files."""
    config = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config) / "nwi-server"


@contextmanager
def source_configs(source: str) -> Iterator[Path]:
    """The folder of a config source's configs, see the module's documentation."""
    if not games.SOURCE_NAME.fullmatch(source):
        raise ValueError(f"not a config source's name: {source}")
    try:
        folder: Path | None = games.config_folder(source)
    except ValueError:
        # Without a version yet; resolved before the yield, so that an error of the caller's isn't
        # taken for one
        folder = None
    if folder is not None:
        yield folder
        return
    url, ref = games.source_settings(source)
    if not url:
        raise ValueError(
            f"the config source {source} has no repository: URL=… in {games.source_file(source)}"
        )
    with tempfile.TemporaryDirectory(prefix="nwi-configs.") as work:
        clone = Path(work) / source
        branch = ["--branch", ref] if ref else []
        # Without the caller's repository, e.g. GIT_DIR of a git hook, which git clone would fill
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        result = subprocess.run(
            ["git", "clone", "--quiet", "--depth", "1", *branch, url, str(clone)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError(
                f"the config source {source}'s repository {url} can't be cloned: "
                f"{result.stderr.strip()}"
            )
        yield clone


def offered(configs: Path) -> list[Config]:
    """The configs of a source's servers/, by name."""
    found = []
    for toml in sorted(configs.glob("servers/*/server.toml")):
        settings = load(toml)
        found.append(
            Config(
                toml.parent.name,
                games.config_game(settings, configs),
                str(settings.get("hostname", "")),
            )
        )
    return found


def used_ports(folder: Path) -> set[int]:
    """The ports of the servers of a folder of environment files, a missing one's the launcher's
    default."""
    used = set()
    envs = sorted(folder.glob("*.env")) if folder.is_dir() else []
    for path in envs:
        env = games.read_env(path)
        for key, default in PORTS.items():
            value = env.get(key, str(default))
            if value.isdigit():
                used.add(int(value))
    return used


def free_ports(used: set[int]) -> dict[str, int]:
    """Of each of a server's ports the lowest from its default that's free, and not one of its
    others."""
    taken = set(used)
    chosen = {}
    for key, port in PORTS.items():
        while port in taken:
            port += 1
        chosen[key] = port
        taken.add(port)
    return chosen


def plan(
    name: str,
    folder: Path,
    configs: Path,
    source: str,
    config: str | None = None,
    game: str | None = None,
) -> Plan:
    """A new server NAME of the environment files' FOLDER, with the configs of SOURCE: its config the
    one named, or the one of its own name; without one, its game has to be named."""
    if not games.SOURCE_NAME.fullmatch(name):
        raise ValueError(
            f"not a server's name: {name} (letters, digits, '.', '_' and '-')"
        )
    path = folder / f"{name}.env"
    if path.exists():
        raise ValueError(f"the server {name} exists already: {path}")
    if game is not None:
        games.known(game)
    names = {found.name: found for found in offered(configs)}
    listing = ", ".join(names) or "none"
    chosen = config or (name if name in names else None)
    if chosen is not None and chosen not in names:
        raise ValueError(
            f"the config source {source} has no config {chosen}; its configs: {listing}"
        )
    if chosen is None:
        if game is None:
            raise ValueError(
                f"the config source {source} has no config {name}: name one with --config "
                f"(its configs: {listing}), or the game of a server without one with --game"
            )
        reason = "named, for a server without a config"
    else:
        settings = load(configs / "servers" / chosen / "server.toml")
        own = names[chosen].game
        if game is not None and game != own:
            raise ValueError(
                f"the config {chosen} is of {own}, not {game}: a config's game is its own"
            )
        if "game" in settings:
            reason = f"the config {chosen}'s"
        else:
            reason = f"the config source {source}'s, as the config {chosen} names none"
        game = own
    return Plan(
        name, source, chosen, game, reason, free_ports(used_ports(folder)), path
    )


def env_text(new: Plan, single: bool) -> str:
    """The environment file of a new server; with SINGLE, of the one folder of configs for all
    servers, which has no sources."""
    lines = [f"# The server {new.name}, of nwi-server add"]
    lines += [f"{key}={port}" for key, port in new.ports.items()]
    if new.source != games.DEFAULT_SOURCE and not single:
        lines.append(f"CONFIG_SOURCE={new.source}")
    if new.config is None:
        lines.append(f"GAME={new.game}")
    elif new.config != new.name:
        lines.append(f"SERVER_CONFIG_NAME={new.config}")
    return "\n".join(lines) + "\n"


def write(new: Plan, single: bool) -> None:
    """Write a new server's environment file, which mustn't exist; readable by all, as it has no
    secrets."""
    new.path.parent.mkdir(parents=True, exist_ok=True)
    with new.path.open("x") as file:
        file.write(env_text(new, single))
    new.path.chmod(0o644)
