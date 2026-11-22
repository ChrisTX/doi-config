"""The container image's commands, one for the server and for its updates, as the systemd units have
them (the image's entrypoint, cli/container.py).

The server's mounts, its game's folders of the state: game at /srv/game and workshop/steamapps/workshop
at /srv/game/steamapps/workshop, both with Podman's overlay (:O), so that the server's writes stay in
its container, and read-only: mods at /srv/mods, the state at /srv/layers and the list of the game's
other depots' versions in it at /srv/depots.list. Its start links the game's other depots into the game,
copies the image's files of the game's folder (/opt/nwi-layer: SourceMod, Metamod:Source, the plugins
and game/common of the repository), the repository's game/<game>, the mods (the map scripts in
custom/, the playlists' configs in cfg/), the server's config of the repository and the secrets into
the game's folder (doi, insurgency), then
prepares and runs the server (launch.py), under the watchdog, which passes the container's stop signal
on.

The environment:
    SERVER_NAME     the server's name, and its config in servers/ if it has one; without, the
                    secrets need a cfg/server.cfg
    SERVER_CONFIG_NAME  its config instead, if it isn't the one of its name, as for the systemd units
The other settings are the variables of nwi-server@.service's environment file (SERVER_PORT, …).
/srv/nwi-data has what the server keeps between its containers, volumes or folders of the image's user:
dumps (crash dumps), logs (the game's), sourcemod/logs and sourcemod/data (SourceMod's).
/run/secrets/nwi-server has the secrets, laid out like the game's folder (e.g. the database credentials
in addons/sourcemod/configs/databases.cfg).
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import games

# What the server keeps, in /srv/nwi-data, and where the game's folder has it, GAME for the game's
KEPT = {
    "dumps": "dumps",
    "logs": "GAME/logs",
    "sourcemod/logs": "GAME/addons/sourcemod/logs",
    "sourcemod/data": "GAME/addons/sourcemod/data",
}


@dataclass(frozen=True)
class Paths:
    """The image's and the mounts' folders."""

    repository: Path = Path("/opt/nwi-server-kit")
    root: Path = Path("/srv/game")
    state: Path = Path("/srv/state")
    layer: Path = Path("/opt/nwi-layer")
    mods: Path = Path("/srv/mods")
    layers: Path = Path("/srv/layers")
    depots: Path = Path("/srv/depots.list")
    data: Path = Path("/srv/nwi-data")
    secrets: Path = Path("/run/secrets/nwi-server")


def link_tree(source: Path, target: Path) -> None:
    """Link every file of SOURCE into TARGET, in the same folders, replacing what's there (cp -as)."""
    for path in sorted(source.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        link = target / path.relative_to(source)
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(path.absolute())


def copy_tree(source: Path, target: Path, links: bool = True) -> None:
    """Copy a folder's contents into another, replacing files; with LINKS the symbolic links as links,
    otherwise their targets."""
    shutil.copytree(source, target, symlinks=links, dirs_exist_ok=True)


def assemble(paths: Paths, server: str | None, config_name: str | None = None) -> Path:
    """Make the game's folder of the server's files, see the module's documentation; the game's folder."""
    if not os.access(paths.root / "srcds_linux", os.X_OK):
        raise ValueError(
            f"no game in {paths.root}, mount the state's game folder there, after an update"
        )
    # The game's other depots, e.g. the Steam client library (1006), as nwi-server update --image lists
    # them: the container has the game's own depot at the root, the versions of the others in the state
    if paths.depots.is_file():
        for depot in paths.depots.read_text().splitlines():
            if depot.strip():
                link_tree(paths.layers / depot.strip(), paths.root)
    game = games.game_folder(paths.root)
    copy_tree(paths.layer, game)
    # The repository's files of the game, over the common ones of the layer (games.game_folders)
    if (paths.repository / "game" / game.name).is_dir():
        copy_tree(paths.repository / "game" / game.name, game, links=False)
    if paths.mods.is_dir():
        copy_tree(paths.mods, game, links=False)
    # What the server keeps, mounted at /srv/nwi-data rather than in the game's folders, where Podman
    # would make the folders above them root's, so the folders are linked
    for kept, place in KEPT.items():
        target = paths.root / place.replace("GAME", game.name)
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(paths.data / kept)
    config_name = config_name or server
    if server and config_name:
        config = paths.repository / "servers" / config_name
        if not config.is_dir():
            raise ValueError(
                f"the config {config_name} isn't in {paths.repository}/servers"
            )
        # With its symbolic links resolved: a link to another server's file, like private-mp's
        # motd.txt, points out of the server's folder
        copy_tree(config, game, links=False)
    if paths.secrets.is_dir():
        copy_tree(paths.secrets, game, links=False)
    return game
