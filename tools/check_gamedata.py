#!/usr/bin/env python3
"""Check the gamedata of the plugins (gamedata/nwi.games.txt) against a game install.

Every Linux signature by symbol ("@name") has to exist in its library's symbol table, so that a game
update that removes or renames a function the plugins call or hook fails the update, rather than the
plugins at the servers' start, where nwi_gamedata only logs what it lacks and the servers run without
it (e.g. with the playlists' restrictions). The entries of the #default block that support the game,
and those of the game's own block, count; signatures without a Linux symbol are left out.
"""

import argparse
import struct
import sys
from pathlib import Path

from srctools.keyvalues import Keyvalues

from games import game_folder


def values(block: Keyvalues, name: str) -> list[str]:
    """The values of the block's keys of the name, without its blocks of that name."""
    return [key.value for key in block.find_all(name) if not key.has_children()]


def symbols_of(gamedata: Keyvalues, game: str) -> list[tuple[str, str, str]]:
    """The Linux symbols the gamedata names for the game: (entry, library, symbol). srctools compares
    the keys' names in lower case, as SourceMod's gamedata does."""
    found = []
    for games in gamedata.find_all("Games"):
        for block in games:
            if not block.has_children():
                continue
            if block.name == "#default":
                supported = [
                    g for s in block.find_all("#supported") for g in values(s, "game")
                ]
                if supported and game not in supported:
                    continue
            elif block.name != game:
                continue
            for signatures in block.find_all("Signatures"):
                for signature in signatures:
                    if not signature.has_children():
                        continue
                    linux = values(signature, "linux")
                    library = values(signature, "library")
                    if linux and linux[0].startswith("@") and library:
                        found.append((signature.real_name, library[0], linux[0][1:]))
    return found


def elf_symbols(path: Path) -> set[str]:
    """The names of an ELF file's symbol tables (.symtab and .dynsym)."""
    data = path.read_bytes()
    if data[:4] != b"\x7fELF":
        raise ValueError(f"{path} isn't an ELF file")
    wide = data[4] == 2
    order = "<" if data[5] == 1 else ">"
    if wide:
        (shoff,) = struct.unpack_from(order + "Q", data, 0x28)
        shentsize, shnum = struct.unpack_from(order + "HH", data, 0x3A)
    else:
        (shoff,) = struct.unpack_from(order + "I", data, 0x20)
        shentsize, shnum = struct.unpack_from(order + "HH", data, 0x2E)
    sections = []
    for i in range(shnum):
        base = shoff + i * shentsize
        if wide:
            _, kind, _, _, offset, size, link, _, _, entsize = struct.unpack_from(
                order + "IIQQQQIIQQ", data, base
            )
        else:
            _, kind, _, _, offset, size, link, _, _, entsize = struct.unpack_from(
                order + "IIIIIIIIII", data, base
            )
        sections.append((kind, offset, size, link, entsize))
    names = set()
    for kind, offset, size, link, entsize in sections:
        # SHT_SYMTAB and SHT_DYNSYM, with the string table they link to
        if kind not in (2, 11) or not entsize:
            continue
        strings_offset = sections[link][1]
        for entry in range(offset, offset + size, entsize):
            (name,) = struct.unpack_from(order + "I", data, entry)
            end = data.index(b"\0", strings_offset + name)
            names.add(data[strings_offset + name : end].decode("utf-8", "replace"))
    return names


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
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
        default=repo / "game/addons/sourcemod/gamedata/nwi.games.txt",
        help="the gamedata file (%(default)s)",
    )
    args = parser.parse_args()

    try:
        folder = game_folder(args.game_dir)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    game = folder.name
    libraries = {
        "server": folder / "bin/server_srv.so",
        "engine": args.game_dir / "bin/engine_srv.so",
    }
    # Signatures keep their backslashes, e.g. \\x2A, as SourceMod reads them
    gamedata = Keyvalues.parse(
        args.gamedata.read_text(encoding="utf-8"), args.gamedata, allow_escapes=False
    )
    missing = []
    loaded: dict[str, set[str]] = {}
    for entry, library, symbol in symbols_of(gamedata, game):
        if library not in loaded:
            loaded[library] = elf_symbols(libraries[library])
        if symbol not in loaded[library]:
            missing.append(f"{entry}: {symbol} isn't in {libraries[library]}")
    for line in missing:
        print(f"Error: {line}", file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
