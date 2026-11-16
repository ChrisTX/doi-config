"""The command line of games.py.

Usage:
    nwi-server games config [SOURCE]   print the folder of the configs of SOURCE, the default one without
    nwi-server games sources [GAME]    print the config sources of the servers (of GAME), one per line;
                               without GAME from their environment files only, so before cloning
    nwi-server games source SOURCE     print the repository (URL) and branch or tag (REF) of SOURCE, one
                               per line, empty where its file has none
    nwi-server games app GAME          print the dedicated server's app of the game, e.g. 462310 of doi
    nwi-server games folder INSTALL    print the name of the game's folder of an install, e.g. doi
    nwi-server games server NAME       print the game of the server NAME
    nwi-server games source-of NAME    print the config source of the server NAME
    nwi-server games used              print the games of the servers, one per line
    nwi-server games servers GAME      print the names of the game's servers, one per line
    nwi-server games workshop-record DIR APP
                               write the record of the workshop items of APP in DIR, as SteamCMD
                               would: steamapps/workshop/appworkshop_<app>.acf, of the manifests
                               DepotDownloader downloaded and the times of the Web API; the game
                               downloads the items itself without it
    nwi-server games items GAME        print the workshop items of the game's servers, one per line as
                               "<app> <item>", the app being the workshop's, from the Web API; an
                               error if they're not all of one app, e.g. an item of another game
"""

import sys
from pathlib import Path

from ..games import (
    DEFAULT_SOURCE,
    SERVER_APPS,
    config_folder,
    env_sources,
    game_folder,
    known,
    server,
    server_envs,
    servers,
    source_settings,
    used_games,
    workshop_app,
    workshop_items,
    workshop_record,
)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    # The least and the most operands of each command
    operands = {
        "config": (0, 1),
        "sources": (0, 1),
        "source": (1, 1),
        "app": (1, 1),
        "folder": (1, 1),
        "server": (1, 1),
        "source-of": (1, 1),
        "used": (0, 0),
        "servers": (1, 1),
        "items": (1, 1),
        "workshop-record": (2, 2),
    }
    command = args[0] if args else ""
    least, most = operands.get(command, (-1, -1))
    if not least <= len(args) - 1 <= most:
        print(__doc__.split("Usage:")[1], file=sys.stderr)
        return 2
    operand = (args[1:] or [""])[0]
    try:
        if command == "config":
            print(config_folder(operand or DEFAULT_SOURCE))
        elif command == "sources":
            if operand:
                game = known(operand)
                names = sorted(
                    {found.source for found in servers() if found.game == game}
                )
            else:
                names = env_sources()
            print("\n".join(names), end="\n" if names else "")
        elif command == "source":
            config_folder(operand)
            print("\n".join(source_settings(operand)))
        elif command == "app":
            print(SERVER_APPS[known(operand)])
        elif command == "folder":
            print(game_folder(Path(operand)).name)
        elif command in ("server", "source-of"):
            found = server(operand, server_envs().get(operand, {}))
            print(found.game if command == "server" else found.source)
        elif command == "workshop-record":
            workshop_record(Path(operand), int(args[2]))
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
        print(f"nwi-server games: {error}", file=sys.stderr)
        return 1
    return 0
