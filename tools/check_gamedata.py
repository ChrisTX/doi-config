#!/usr/bin/env python3
"""Check the gamedata of the plugins (gamedata/nwi.games.txt) against a game install.

Every Linux signature by symbol ("@name") has to exist in its library's symbol table, so that a game
update that removes or renames a function the plugins call or hook fails the update, rather than the
plugins at the servers' start, where nwi_gamedata only logs what it lacks and the servers run without
it (e.g. with the playlists' restrictions). The entries of the #default block that support the game,
and those of the game's own block, count; signatures without a Linux symbol are left out.
"""

import argparse
import re
import struct
import sys
from pathlib import Path

# A token of the KeyValues format: a quoted string, a brace or a bare word; comments are left out
TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])|//[^\n]*|([^\s{}"]+)')


def parse_keyvalues(text: str) -> list:
    """The file as nested lists of (key, value) pairs, a value a string or such a list."""
    stack: list[list] = [[]]
    key = None
    for match in TOKEN.finditer(text):
        string, brace, bare = match.groups()
        if brace == "{":
            block: list = []
            stack[-1].append((key, block))
            stack.append(block)
            key = None
        elif brace == "}":
            stack.pop()
        elif string is not None or bare is not None:
            word = string if string is not None else bare
            if key is None:
                key = word
            else:
                stack[-1].append((key, word))
                key = None
    return stack[0]


def blocks(pairs: list, name: str) -> list:
    return [value for key, value in pairs if key == name and isinstance(value, list)]


def strings(pairs: list, name: str) -> list[str]:
    return [value for key, value in pairs if key == name and isinstance(value, str)]


def symbols_of(gamedata: list, game: str) -> list[tuple[str, str, str]]:
    """The Linux symbols the gamedata names for the game: (entry, library, symbol)."""
    found = []
    for games in blocks(gamedata, "Games"):
        for key, block in games:
            if not isinstance(block, list):
                continue
            if key == "#default":
                supported = [
                    g for s in blocks(block, "#supported") for g in strings(s, "game")
                ]
                if supported and game not in supported:
                    continue
            elif key != game:
                continue
            for signatures in blocks(block, "Signatures"):
                for entry, signature in signatures:
                    if not isinstance(signature, list):
                        continue
                    linux = strings(signature, "linux")
                    library = strings(signature, "library")
                    if linux and linux[0].startswith("@") and library:
                        found.append((entry, library[0], linux[0][1:]))
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
        help="the game install, with doi/ or insurgency/ in it",
    )
    parser.add_argument(
        "--gamedata",
        type=Path,
        default=repo / "game/addons/sourcemod/gamedata/nwi.games.txt",
        help="the gamedata file (%(default)s)",
    )
    args = parser.parse_args()

    game = next(
        (g for g in ("doi", "insurgency") if (args.game_dir / g).is_dir()), None
    )
    if game is None:
        print(f"Error: no doi or insurgency folder in {args.game_dir}", file=sys.stderr)
        return 2
    libraries = {
        "server": args.game_dir / game / "bin/server_srv.so",
        "engine": args.game_dir / "bin/engine_srv.so",
    }
    gamedata = parse_keyvalues(args.gamedata.read_text(encoding="utf-8"))
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
