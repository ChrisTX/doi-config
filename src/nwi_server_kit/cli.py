"""The nwi-server command: the tools of the kit as subcommands.

Usage: nwi-server COMMAND ARGUMENTS..., the commands:
    games            what the tools know of the games and find out about the servers (games.py)
    server-config    a server's settings, server.toml (server_config.py)
"""

import sys
from collections.abc import Callable

from . import games, server_config

COMMANDS: dict[str, Callable[[list[str]], int]] = {
    "games": games.main,
    "server-config": server_config.main,
}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in COMMANDS:
        print(__doc__.split("Usage:")[1].rstrip(), file=sys.stderr)
        return 2
    return COMMANDS[args[0]](args[1:])
