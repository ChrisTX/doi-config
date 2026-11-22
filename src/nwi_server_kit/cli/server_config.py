"""The command line of server_config.py.

Usage: with GAME the game's folder of the install ROOT (nwi_server_kit.games):
    nwi-server server-config prepare ROOT   write ROOT/GAME/cfg/server.cfg and ROOT/GAME/subscribed_file_ids.txt
                                    from ROOT/GAME/server.toml (nwi-server prepare)
    nwi-server server-config args ROOT      print the command line's options of ROOT/GAME/server.toml, one per
                                    line (nwi-server start)
    nwi-server server-config game FILE      print the game of a server.toml of a config source's
                                    servers/<config>/, its own or the source's (games.source_game())
    nwi-server server-config check FILE...  check server.toml files: their keys, and that the configs and lists
                                    they name exist in the cfg of game/<game> or game/common, or in the
                                    server's own cfg folder (NWI_CONFIG, see
                                    nwi_server_kit.games)
"""

import sys
import tomllib
from pathlib import Path

from ..games import config_game
from ..server_config import check, load, options, prepare


def args(root: Path) -> None:
    for option in options(root):
        print(option)


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
            # servers/<config>/server.toml of the source's configs
            print(config_game(load(operands[0]), operands[0].resolve().parents[2]))
        else:
            (prepare if command == "prepare" else args)(operands[0])
    except (ValueError, OSError, tomllib.TOMLDecodeError) as error:
        print(f"nwi-server server-config: {error}", file=sys.stderr)
        return 1
    return 0
