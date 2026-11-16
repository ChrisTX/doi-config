"""Check the gamedata of the plugins (gamedata/nwi.games.txt) against a game install.

Every Linux signature by symbol ("@name") has to exist in its library's symbol table, so that a game
update that removes or renames a function the plugins call or hook fails the update, rather than the
plugins at the servers' start, where nwi_gamedata only logs what it lacks and the servers run without
it (e.g. with the playlists' restrictions). The entries of the #default block that support the game,
and those of the game's own block, count; signatures without a Linux symbol are left out. The gamedata
is read as SourceMod reads it (hl2sdk_ghidra.gamedata).
"""

import argparse
import sys
from pathlib import Path

from hl2sdk_ghidra import elf, gamedata

from .games import config_folder, game_folder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nwi-server check-gamedata",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "game_dir",
        type=Path,
        metavar="GAME",
        help="the game install, with its game's folder, doi/ or insurgency/, in it",
    )
    parser.add_argument(
        "--gamedata",
        type=Path,
        default=None,
        help="the gamedata file (of the default config source's configs by default)",
    )
    args = parser.parse_args(argv)

    try:
        if args.gamedata is None:
            args.gamedata = (
                config_folder() / "game/addons/sourcemod/gamedata/nwi.games.txt"
            )
        folder = game_folder(args.game_dir)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    game = folder.name
    libraries = {
        "server": folder / "bin/server_srv.so",
        "engine": args.game_dir / "bin/engine_srv.so",
    }
    # The game's engine as SourceMod names it is the game's name: doi or insurgency
    found = gamedata.symbols(gamedata.entries([args.gamedata], game, game))
    missing = []
    loaded: dict[str, set[str]] = {}
    for entry in found:
        library = entry.library or "server"
        if library not in libraries:
            continue
        if library not in loaded:
            loaded[library] = elf.symbols(libraries[library])
        if entry.value not in loaded[library]:
            missing.append(f"{entry.name}: {entry.value} isn't in {libraries[library]}")
    for line in missing:
        print(f"Error: {line}", file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
