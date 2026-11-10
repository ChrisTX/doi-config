#!/usr/bin/env python3
"""Print SourceMod's gamedata for a game as TSV, for CheckGamedata.java.

GAMEDATA is SourceMod's gamedata folder, GAME the game's folder (e.g. doi) and ENGINE its engine as
SourceMod names it (e.g. insurgency, which DoI uses too). Like SourceMod, it reads the files each
folder's master.games.txt lists for the engine or game, and in them the blocks of the game and the
#default blocks whose #supported (if any) names the engine or game; a later value replaces an earlier
one. Each line: the kind (Offsets or Signatures), the name, the value for Linux, the library (-
for offsets) and the file.
"""

import argparse
from pathlib import Path

from srctools.keyvalues import Keyvalues
from srctools.tokenizer import Tokenizer


def parse(path: Path) -> Keyvalues:
    """A gamedata file: with /* */ comments, and without escapes, which byte signatures (\\x55) aren't."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return Keyvalues.parse(
        Tokenizer(text, str(path), allow_escapes=False, allow_star_comments=True)
    )


def values(block: Keyvalues, key: str) -> list[str]:
    """The values of all of a block's children named key."""
    return [
        child.value for child in block if child.name == key and not child.has_children()
    ]


def matches(block: Keyvalues, game: str, engine: str) -> bool:
    """Whether a block of master.games.txt or a #supported block is for the game: names it or its
    engine, or names none (an empty entry of master.games.txt is for every game)."""
    games, engines = values(block, "game"), values(block, "engine")
    return (not games and not engines) or game in games or engine in engines


def files(gamedata: Path, game: str, engine: str) -> list[Path]:
    """The gamedata files SourceMod loads for the game."""
    result = sorted(path for path in gamedata.glob("*.txt"))
    for folder in sorted(path for path in gamedata.iterdir() if path.is_dir()):
        master = folder / "master.games.txt"
        if not master.is_file():
            continue
        tree = parse(master)
        for entry in tree.find_key("Game Master"):
            if entry.has_children() and matches(entry, game, engine):
                result.append(folder / entry.real_name)
    return result


def blocks(tree: Keyvalues, game: str, engine: str):
    """The blocks of a gamedata file that apply to the game."""
    for block in tree.find_key("Games", []):
        if not block.has_children():
            continue
        if block.name == game:
            yield block
        elif block.name == "#default":
            supported = [child for child in block if child.name == "#supported"]
            if not supported or any(matches(s, game, engine) for s in supported):
                yield block


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--arch",
        choices=["x86", "x86_64"],
        default="x86",
        help="the server's architecture, whose values to take (%(default)s)",
    )
    parser.add_argument(
        "gamedata",
        type=Path,
        metavar="GAMEDATA",
        help="SourceMod's gamedata folder, e.g. /usr/lib/sourcemod/addons/sourcemod/gamedata",
    )
    parser.add_argument("game", metavar="GAME", help="the game's folder, e.g. doi")
    parser.add_argument(
        "engine",
        metavar="ENGINE",
        help="the engine as SourceMod names it, e.g. insurgency",
    )
    args = parser.parse_args()
    platform = "linux" if args.arch == "x86" else "linux64"

    found: dict[tuple[str, str], tuple[str, str, str]] = {}
    for path in files(args.gamedata, args.game, args.engine):
        if not path.is_file():
            continue
        tree = parse(path)
        name = str(path.relative_to(args.gamedata))
        for block in blocks(tree, args.game, args.engine):
            for entry in block.find_all("Offsets"):
                for offset in entry:
                    value = values(offset, platform)
                    if offset.has_children() and value:
                        found["Offsets", offset.real_name] = (value[-1], "-", name)
            for entry in block.find_all("Signatures"):
                for signature in entry:
                    value = values(signature, platform)
                    if signature.has_children() and value:
                        library = (values(signature, "library") or ["server"])[-1]
                        found["Signatures", signature.real_name] = (
                            value[-1],
                            library,
                            name,
                        )
    for (kind, name), (value, library, file) in found.items():
        print(f"{kind}\t{name}\t{value}\t{library}\t{file}")


if __name__ == "__main__":
    main()
