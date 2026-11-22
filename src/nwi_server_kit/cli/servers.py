"""The command line of servers.py.

Usage:
    nwi-server configs [SOURCE]
        list the configs of a config source (the default one without SOURCE): their names, games and
        servers' names
    nwi-server add SERVER [--config CONFIG] [--source SOURCE] [--game GAME] [--user]
        set up a server: write its environment file, /etc/nwi-server/SERVER.env (NWI_SERVERS_DIR),
        with --user ~/.config/nwi-server/SERVER.env of the Quadlet units, with the config CONFIG of
        SOURCE, the one named SERVER without, and ports that the folder's other servers don't use;
        its game is the config's, and print it, and how to start the server. A server without a
        config names its game with --game, and needs its own cfg/server.cfg
"""

import argparse
import sys

from .. import games, servers


def configs_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nwi-server configs",
        description="List the configs of a config source: their names, games and servers' names.",
    )
    parser.add_argument(
        "source", nargs="?", default=games.DEFAULT_SOURCE, metavar="SOURCE"
    )
    args = parser.parse_args(argv)
    try:
        with servers.source_configs(args.source) as configs:
            found = servers.offered(configs)
            default = games.source_game(configs)
    except (ValueError, OSError) as error:
        print(f"nwi-server configs: {error}", file=sys.stderr)
        return 1
    print(f"The configs of {args.source}, {default} where they name no game:")
    width = max((len(config.name) for config in found), default=0)
    game_width = max(len(game) for game in games.SERVER_APPS)
    for config in found:
        print(
            f"  {config.name:<{width}}  {config.game:<{game_width}}  {config.hostname}"
        )
    return 0


def add_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nwi-server add",
        description="Set up a server: write its environment file, with its config, game and ports.",
    )
    parser.add_argument("server", metavar="SERVER")
    parser.add_argument(
        "--config", help="the config of servers/, the one named SERVER without"
    )
    parser.add_argument(
        "--source", default=games.DEFAULT_SOURCE, help="the config source"
    )
    parser.add_argument(
        "--game",
        choices=sorted(games.SERVER_APPS),
        help="the game, of a server without a config",
    )
    parser.add_argument(
        "--user",
        action="store_true",
        help="for the Quadlet units, in ~/.config/nwi-server",
    )
    args = parser.parse_args(argv)
    folder = servers.user_dir() if args.user else games.servers_dir()
    single = games.single_config() is not None
    try:
        with servers.source_configs(args.source) as configs:
            new = servers.plan(
                args.server, folder, configs, args.source, args.config, args.game
            )
        servers.write(new, single)
    except (ValueError, OSError) as error:
        print(f"nwi-server add: {error}", file=sys.stderr)
        return 1
    of = f"the config {new.config} of {new.source}" if new.config else "no config"
    if single:
        of = f"the config {new.config}" if new.config else "no config"
    print(f"{new.name}: {new.game} ({new.reason}), {of}")
    print(
        f"Ports: game {new.ports['SERVER_PORT']} (UDP, and TCP for RCON), "
        f"SourceTV {new.ports['TV_PORT']}, client {new.ports['CLIENT_PORT']}"
    )
    print(f"Written: {new.path}")
    if new.config is None:
        print("A server without a config needs its own cfg/server.cfg.")
    user = " --user" if args.user else ""
    print(
        f"Start it with: systemctl{user} enable --now nwi-server@{new.name}.service "
        "nwi-servers.target"
    )
    return 0
