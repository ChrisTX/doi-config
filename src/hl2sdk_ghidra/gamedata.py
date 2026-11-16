"""SourceMod's gamedata, read as SourceMod reads it for a game.

SourceMod loads, of its gamedata folder, the files a folder's master.games.txt lists for the game or
its engine, and in a file the blocks of the game and the #default blocks whose #supported (if any)
names the game or its engine; a later value replaces an earlier one. The engine is SourceMod's name of
it, e.g. doi for Day of Infamy, which loads Insurgency's engine files too. Only srctools is needed, so
that the servers' kit (nwi_server_kit.check_gamedata) reads gamedata alike.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from srctools.keyvalues import Keyvalues
from srctools.tokenizer import Tokenizer


@dataclass(frozen=True)
class Entry:
    """An offset or a signature of the gamedata for a platform: its kind (Offsets or Signatures),
    name, value, library (server or engine; None for offsets) and file."""

    kind: str
    name: str
    value: str
    library: str | None
    file: str


def parse(path: Path) -> Keyvalues:
    """A gamedata file: with /* */ comments, and without escapes, which byte signatures (\\x55) aren't."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return Keyvalues.parse(
        Tokenizer(text, str(path), allow_escapes=False, allow_star_comments=True)
    )


def values(block: Keyvalues, key: str) -> list[str]:
    """The values of all of a block's children named KEY, not its blocks of that name; srctools compares
    names in lower case, as SourceMod does."""
    return [child.value for child in block.find_all(key) if not child.has_children()]


def matches(block: Keyvalues, game: str, engine: str) -> bool:
    """Whether a block of master.games.txt or a #supported block is for the game: names it or its
    engine, or names neither (an empty entry of master.games.txt is for every game)."""
    games, engines = values(block, "game"), values(block, "engine")
    return (not games and not engines) or game in games or engine in engines


def files(gamedata: Path, game: str, engine: str) -> list[Path]:
    """The gamedata files SourceMod loads for the game, of its gamedata folder."""
    result = sorted(gamedata.glob("*.txt"))
    for folder in sorted(path for path in gamedata.iterdir() if path.is_dir()):
        master = folder / "master.games.txt"
        if not master.is_file():
            continue
        for entry in parse(master).find_key("Game Master", or_blank=True):
            if entry.has_children() and matches(entry, game, engine):
                result.append(folder / entry.real_name)
    return result


def blocks(tree: Keyvalues, game: str, engine: str) -> Iterator[Keyvalues]:
    """The blocks of a gamedata file that apply to the game."""
    for games in tree.find_all("Games"):
        for block in games:
            if not block.has_children():
                continue
            if block.name == game.casefold():
                yield block
            elif block.name == "#default":
                supported = list(block.find_all("#supported"))
                if not supported or any(matches(s, game, engine) for s in supported):
                    yield block


def entries(
    paths: list[Path],
    game: str,
    engine: str,
    platform: str = "linux",
    root: Path | None = None,
) -> list[Entry]:
    """The offsets and signatures of the files for the game on the platform (linux, linux64, windows,
    windows64), a later value replacing an earlier one; files are named relative to ROOT."""
    found: dict[tuple[str, str], Entry] = {}
    for path in paths:
        if not path.is_file():
            continue
        name = str(path.relative_to(root)) if root is not None else path.name
        for block in blocks(parse(path), game, engine):
            for offsets in block.find_all("Offsets"):
                for offset in offsets:
                    value = values(offset, platform)
                    if offset.has_children() and value:
                        found["Offsets", offset.real_name] = Entry(
                            "Offsets", offset.real_name, value[-1], None, name
                        )
            for signatures in block.find_all("Signatures"):
                for signature in signatures:
                    value = values(signature, platform)
                    if signature.has_children() and value:
                        library = (values(signature, "library") or ["server"])[-1]
                        found["Signatures", signature.real_name] = Entry(
                            "Signatures", signature.real_name, value[-1], library, name
                        )
    return list(found.values())


def folder_entries(
    gamedata: Path, game: str, engine: str, platform: str = "linux"
) -> list[Entry]:
    """The offsets and signatures SourceMod loads for the game of its gamedata folder."""
    return entries(files(gamedata, game, engine), game, engine, platform, gamedata)


def symbols(found: list[Entry]) -> list[Entry]:
    """The signatures by symbol (@name) of entries: the value without the @."""
    return [
        Entry(entry.kind, entry.name, entry.value[1:], entry.library, entry.file)
        for entry in found
        if entry.kind == "Signatures" and entry.value.startswith("@")
    ]
