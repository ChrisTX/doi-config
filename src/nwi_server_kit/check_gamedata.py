"""Check the gamedata of the plugins (gamedata/nwi.games.txt) against a game install.

Every Linux signature by symbol ("@name") has to exist in its library's symbol table, so that a game
update that removes or renames a function the plugins call or hook fails the update, rather than the
plugins at the servers' start, where nwi_gamedata only logs what it lacks and the servers run without
it (e.g. with the playlists' restrictions). The entries of the #default block that support the game,
and those of the game's own block, count; signatures without a Linux symbol are left out. The gamedata
is read as SourceMod reads it (hl2sdk_ghidra.gamedata).
"""

from pathlib import Path

from hl2sdk_ghidra import elf, gamedata

from .games import config_folder, game_folder


def missing(game_dir: Path, gamedata_file: Path | None = None) -> list[str]:
    """The gamedata's signatures by symbol that the game install's libraries don't have, as
    messages; the gamedata of the default config source's configs without GAMEDATA_FILE."""
    if gamedata_file is None:
        gamedata_file = config_folder() / "game/addons/sourcemod/gamedata/nwi.games.txt"
    folder = game_folder(game_dir)
    game = folder.name
    libraries = {
        "server": folder / "bin/server_srv.so",
        "engine": game_dir / "bin/engine_srv.so",
    }
    # The game's engine as SourceMod names it is the game's name: doi or insurgency
    found = gamedata.symbols(gamedata.entries([gamedata_file], game, game))
    messages = []
    loaded: dict[str, set[str]] = {}
    for entry in found:
        library = entry.library or "server"
        if library not in libraries:
            continue
        if library not in loaded:
            loaded[library] = elf.symbols(libraries[library])
        if entry.value not in loaded[library]:
            messages.append(
                f"{entry.name}: {entry.value} isn't in {libraries[library]}"
            )
    return messages
