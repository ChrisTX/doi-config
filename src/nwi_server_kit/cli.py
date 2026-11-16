"""The nwi-server command: the tools of the kit as subcommands.

Usage: nwi-server COMMAND ARGUMENTS..., the commands:
    games            what the tools know of the games and find out about the servers (games.py)
    server-config    a server's settings, server.toml (server_config.py)
    make-mods        make the mods of mods/<game>/*.toml (make_mods.py)
    check-gamedata   check the plugins' gamedata against a game install (check_gamedata.py)
    update           update the layers of the servers (update.py)
    compile-plugins  compile the plugins of configs (update.py)
    check-updates    check the games and workshop items for updates (check_updates.py)
    mount            mount a server's layers (mount.py)
    unmount          unmount a server's layers (mount.py)
    health           the trial of new versions of the layers (health.py)
    notify           the admins' notifications (notify.py)
"""

import sys
from collections.abc import Callable

from . import (
    check_gamedata,
    check_updates,
    games,
    health,
    make_mods,
    mount,
    notify,
    server_config,
    update,
)

COMMANDS: dict[str, Callable[[list[str]], int]] = {
    "games": games.main,
    "server-config": server_config.main,
    "make-mods": make_mods.main,
    "check-gamedata": check_gamedata.main,
    "update": update.main,
    "compile-plugins": update.compile_main,
    "check-updates": check_updates.main,
    "mount": mount.main,
    "unmount": mount.unmount_main,
    "health": health.main,
    "notify": notify.main,
}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in COMMANDS:
        print(__doc__.split("Usage:")[1].rstrip(), file=sys.stderr)
        return 2
    return COMMANDS[args[0]](args[1:])
