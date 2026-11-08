#!/usr/bin/env python3
"""Make the mods of mods/*.toml from the game's map scripts.

A map's script, maps/<map>.txt, configures its game modes, a block each: the teams, the control points
in the order they're taken, the spawn zones and the entities. The game ships the scripts in its VPKs
(doi/*_dir.vpk), a workshop map in its item. A mod copies a block under the name of another game mode,
e.g. offensive as invasion, which the map doesn't have, and adjusts the copy. The mods are made from
the installed game, so they follow its updates, and this repository only holds the rules.

Each mods/<mod>.toml makes the mod folder custom/<mod> of the output, with the scripts of its maps:

    # A map's script comes from the game, unless the map is from the workshop: map = item ID
    [workshop]
    tobruk = 823637416

    # The copies, applied in order; each copies one block of the maps it lists
    [[copy]]
    maps = ["reichswald", "tobruk"]
    from = "offensive"
    to = "invasion"
    # The copy's control points without these ...
    remove_controlpoints = ["regroup_cap"]
    # ... or these instead of the copied ones, in their order
    controlpoints = ["occupy_cap", "church_cap", "radiopoint_final"]
    # Spawn zones of the copy set or added, by their number
    spawnzones = { 3 = "sz_offensive_c" }

The output is the rest of the script as it is, with the copies after the blocks they're made from, in
the game's format, indented anew and without comments. Braces in the wrong place are repaired, as far
as the keys of a level show where a block ends (see parse_script()). A copy whose block the map doesn't have, or which names a control
point that the block doesn't have, is an error, e.g. after a game update that changed the map.

Usage: make_mods.py --game DIR --workshop DIR OUTPUT MODS...

--game is the game's install, with doi/ in it, --workshop SteamCMD's folder of the workshop items
(steamapps/workshop/content/447820/<item> in it). MODS are the mods' .toml files, or folders of them.
OUTPUT is replaced.
"""

import argparse
import re
import shutil
import struct
import sys
import tomllib
import zlib
from dataclasses import dataclass, field
from pathlib import Path

GAME_APP = 447820
VPK_SIGNATURE = 0x55AA1234
# A file's data in the directory file rather than in an archive of the VPK
VPK_IN_DIRECTORY = 0x7FFF

# The game modes, the blocks of a map's script that copies are made from and to
GAME_MODES = {
    "assassination",
    "entrenchment",
    "firefight",
    "frontline",
    "intel",
    "invasion",
    "liberation",
    "offensive",
    "patrol",
    "raid",
    "sabotage",
    "sandbox",
    "stronghold",
}

COPY_KEYS = {
    "maps",
    "from",
    "to",
    "remove_controlpoints",
    "controlpoints",
    "spawnzones",
}


class ModError(Exception):
    """A mod that can't be made, with the reason."""


# KeyValues, the format of the map scripts: a list of (key, value) pairs, where a value is a string or
# a block, a list of pairs again. Keys repeat, e.g. "controlpoint" once for every control point.
Pairs = list[tuple[str, "str | Pairs"]]

TOKEN = re.compile(
    r'"(?P<quoted>[^"\n]*)"|(?P<comment>//[^\n]*)|(?P<brace>[{}])|[^\s{}"]+'
)


@dataclass(frozen=True)
class Level:
    """The keys a level of a map's script may have, in lower case: its values and its blocks, with the
    level each block's contents are on. None is a level with any keys, e.g. the entities of a game
    mode."""

    name: str
    values: frozenset[str] = frozenset()
    blocks: dict[str, "Level | None"] = field(default_factory=dict)
    # The level of blocks of other names, if the level may have any
    other_blocks: "Level | None" = None

    def allows(self, key: str, block: bool) -> bool:
        if block:
            return key.lower() in self.blocks or self.other_blocks is not None
        return key.lower() in self.values

    def child(self, key: str) -> "Level | None":
        return self.blocks.get(key.lower(), self.other_blocks)


# The levels of a map's script, from the scripts of the game and of workshop maps: the file holds one
# block (named "cpsetup.txt"), the script, whose blocks are the game modes and the units. Below a game
# mode, and in the units' blocks, any key goes.
GAME_MODE_LEVEL = Level(
    "a game mode",
    values=frozenset(
        {
            "teamone",
            "teamtwo",
            "attackingteam",
            "controlpoint",
            "roundtimer_frac",
            "teamonedefaultunit",
            "teamtwodefaultunit",
        }
    ),
    blocks=dict.fromkeys(
        ("spawnzones", "entities", "blockzones", "ai", "navspawns", "cvars")
    ),
)
SCRIPT_LEVEL = Level(
    "the script",
    values=frozenset({"nightlighting", "navfile", "compassoffset"}),
    blocks=dict.fromkeys(
        (
            "theater_conditions",
            "allowed_units",
            "coop_base_units",
            "coop_elite_units",
        )
    )
    | dict.fromkeys(GAME_MODES, GAME_MODE_LEVEL),
)
FILE_LEVEL = Level("the file", other_blocks=SCRIPT_LEVEL)


def parse_script(text: str, source: str) -> tuple[Pairs, list[str]]:
    """Parse a map's script into its pairs, without its comments, and repair its braces: a key that
    its level doesn't have, but a level it's in, closes the blocks up to that level, e.g. a game mode in
    a game mode that isn't closed, and a closing brace after the file's block is dropped. Returns the
    pairs and what was repaired; a script whose blocks still don't match, or that has a key no level
    takes, is an error."""
    # (brace, text): a brace is "{" or "}", not a quoted "{"
    tokens = [
        (
            match["brace"] is not None,
            match["quoted"] if match["quoted"] is not None else match[0],
        )
        for match in TOKEN.finditer(text)
        if match["comment"] is None
    ]
    file: Pairs = []
    # The open blocks, the file's first: their level, their pairs and their key
    stack: list[tuple[Level | None, Pairs, str]] = [(FILE_LEVEL, file, "the file")]
    repairs = []
    index = 0
    while index < len(tokens):
        brace, key = tokens[index]
        if brace:
            if key == "{":
                raise ModError(f"{source}: a block without a key in {stack[-1][2]}")
            if len(stack) == 1:
                repairs.append("dropped a closing brace after the end")
            else:
                stack.pop()
            index += 1
            continue
        if index + 1 >= len(tokens) or tokens[index + 1] == (True, "}"):
            raise ModError(f"{source}: {key!r} has no value")
        brace, value = tokens[index + 1]
        block = brace
        # The innermost open block whose level takes the key; the blocks in it are closed
        depth = next(
            (
                depth
                for depth in range(len(stack) - 1, -1, -1)
                if stack[depth][0] is None or stack[depth][0].allows(key, block)
            ),
            None,
        )
        if depth is None:
            raise ModError(f"{source}: unexpected {key!r} in {stack[-1][2]}")
        repairs.extend(
            f"closed {name} before {key}" for _, _, name in reversed(stack[depth + 1 :])
        )
        del stack[depth + 1 :]
        level, pairs, _ = stack[-1]
        if block:
            contents: Pairs = []
            pairs.append((key, contents))
            stack.append((None if level is None else level.child(key), contents, key))
        else:
            pairs.append((key, value))
        index += 2
    if len(stack) > 1:
        raise ModError(f"{source}: {stack[-1][2]} isn't closed")
    if len(file) != 1:
        raise ModError(f"{source}: the file isn't one block")
    return file, repairs


def format_keyvalues(pairs: Pairs, depth: int = 0) -> str:
    """Write pairs in the format of the game's scripts, indented with tabs."""
    indent = "\t" * depth
    lines = []
    for key, value in pairs:
        if isinstance(value, str):
            lines.append(f'{indent}"{key}"\t"{value}"\n')
        else:
            lines.append(
                f'{indent}"{key}"\n{indent}{{\n{format_keyvalues(value, depth + 1)}{indent}}}\n'
            )
    return "".join(lines)


def read_vpk(directory: Path, wanted: str) -> bytes | None:
    """Read a file from a VPK by its path in it, from its directory file (<name>_dir.vpk), version 1 or
    2; None if it doesn't have the file."""
    data = directory.read_bytes()
    signature, version, tree_size = struct.unpack_from("<III", data)
    if signature != VPK_SIGNATURE or version not in (1, 2):
        raise ModError(f"{directory} isn't a VPK of version 1 or 2")
    # Version 2's header has four more fields, the sizes of the sections after the tree
    position = 12 if version == 1 else 28
    tree_end = position + tree_size

    def string() -> str:
        nonlocal position
        end = data.index(b"\0", position)
        text = data[position:end].decode()
        position = end + 1
        return text

    # The tree: by extension, then by path, the files, each a list ending with an empty string. A
    # single space stands for no extension or path.
    while extension := string():
        while path := string():
            while name := string():
                crc, preload_size, archive, offset, size, _ = struct.unpack_from(
                    "<IHHIIH", data, position
                )
                position += 18
                preload = data[position : position + preload_size]
                position += preload_size
                file = name if extension == " " else f"{name}.{extension}"
                if (file if path == " " else f"{path}/{file}") != wanted:
                    continue
                if archive == VPK_IN_DIRECTORY:
                    body = data[tree_end + offset : tree_end + offset + size]
                else:
                    stem = directory.name.removesuffix("_dir.vpk")
                    with directory.with_name(f"{stem}_{archive:03}.vpk").open(
                        "rb"
                    ) as archive_file:
                        archive_file.seek(offset)
                        body = archive_file.read(size)
                content = preload + body
                if zlib.crc32(content) != crc:
                    raise ModError(
                        f"{wanted} in {directory} doesn't match its checksum"
                    )
                return content
    return None


def read_script(
    game: Path, workshop: Path, workshop_maps: dict[str, int], name: str
) -> tuple[Pairs, list[str]]:
    """Read and parse a map's script, see parse_script(): a workshop map's from its item, a map of the
    game's from its doi folder or its VPKs."""
    wanted = f"maps/{name}.txt"
    if name in workshop_maps:
        item = workshop_maps[name]
        path = (
            workshop / "steamapps/workshop/content" / str(GAME_APP) / str(item) / wanted
        )
        if not path.is_file():
            raise ModError(f"{name}: the workshop item {item} has no {wanted}")
        content, source = path.read_bytes(), str(path)
    elif (game / "doi" / wanted).is_file():
        content, source = (
            (game / "doi" / wanted).read_bytes(),
            str(game / "doi" / wanted),
        )
    else:
        for directory in sorted((game / "doi").glob("*_dir.vpk")):
            found = read_vpk(directory, wanted)
            if found is not None:
                content, source = found, f"{directory.name}/{wanted}"
                break
        else:
            raise ModError(f"{name}: the game has no {wanted}")
    return parse_script(content.decode("utf-8", errors="replace"), source)


@dataclass
class Copy:
    """A copy of a game mode's block, from a mod's [[copy]] table."""

    maps: list[str]
    source: str
    target: str
    remove: list[str]
    controlpoints: list[str] | None
    spawnzones: dict[str, str]

    @classmethod
    def from_table(cls, table: dict, mod: str) -> "Copy":
        unknown = set(table) - COPY_KEYS
        if unknown:
            raise ModError(
                f"{mod}: unknown keys in a copy: {', '.join(sorted(unknown))}"
            )
        if "remove_controlpoints" in table and "controlpoints" in table:
            raise ModError(
                f"{mod}: a copy has controlpoints or remove_controlpoints, not both"
            )
        try:
            copy = cls(
                maps=list(table["maps"]),
                source=table["from"],
                target=table["to"],
                remove=list(table.get("remove_controlpoints", [])),
                controlpoints=table.get("controlpoints"),
                spawnzones={
                    str(number): zone
                    for number, zone in table.get("spawnzones", {}).items()
                },
            )
        except KeyError as error:
            raise ModError(f"{mod}: a copy has no {error.args[0]}") from None
        for mode in (copy.source, copy.target):
            if mode not in GAME_MODES:
                raise ModError(f"{mod}: {mode} isn't a game mode")
        return copy

    def apply(self, blocks: Pairs, name: str) -> None:
        """Insert the copy into a map script's blocks, after the block it's made from."""
        modes = [key.lower() for key, _ in blocks]
        if self.source not in modes:
            raise ModError(f"{name}: has no {self.source} to copy")
        if self.target in modes:
            raise ModError(f"{name}: has {self.target} already")
        index = modes.index(self.source)
        block = list(blocks[index][1])

        def is_point(key: str) -> bool:
            return key.lower() == "controlpoint"

        points = [value for key, value in block if is_point(key)]
        missing = [point for point in self.remove if point not in points]
        if missing:
            raise ModError(
                f"{name}: {self.source} has no control points {', '.join(missing)}"
            )
        block = [
            pair for pair in block if not (is_point(pair[0]) and pair[1] in self.remove)
        ]
        if self.controlpoints is not None:
            first = next(i for i, (key, _) in enumerate(block) if is_point(key))
            block = [pair for pair in block if not is_point(pair[0])]
            block[first:first] = [
                ("controlpoint", point) for point in self.controlpoints
            ]
        if self.spawnzones:
            zones_index = next(
                (i for i, (key, _) in enumerate(block) if key.lower() == "spawnzones"),
                None,
            )
            if zones_index is None:
                raise ModError(f"{name}: {self.source} has no spawn zones")
            key, zones = block[zones_index]
            zones = dict(zones)
            zones.update(self.spawnzones)
            block[zones_index] = (key, list(zones.items()))
        blocks.insert(index + 1, (self.target, block))


def make_mod(config: Path, game: Path, workshop: Path, output: Path) -> None:
    """Make the mod of a mods/<mod>.toml in output/custom/<mod>."""
    mod = config.stem
    with config.open("rb") as file:
        settings = tomllib.load(file)
    unknown = set(settings) - {"workshop", "copy"}
    if unknown:
        raise ModError(f"{mod}: unknown tables {', '.join(sorted(unknown))}")
    workshop_maps = settings.get("workshop", {})
    copies = [Copy.from_table(table, mod) for table in settings.get("copy", [])]
    maps = dict.fromkeys(name for copy in copies for name in copy.maps)
    for name in maps:
        script, repairs = read_script(game, workshop, workshop_maps, name)
        for repair in repairs:
            print(f"{mod}: {name}: {repair}", file=sys.stderr)
        root, blocks = script[0]
        for copy in copies:
            if name in copy.maps:
                copy.apply(blocks, name)
        path = output / "custom" / mod / "maps" / f"{name}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(format_keyvalues([(root, blocks)]), encoding="utf-8")
    print(f"{mod}: {len(maps)} maps", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Make the mods of mods/*.toml from the game's map scripts."
    )
    parser.add_argument(
        "--game", type=Path, required=True, help="the game's install, with doi/ in it"
    )
    parser.add_argument(
        "--workshop",
        type=Path,
        required=True,
        help="SteamCMD's folder of the workshop items",
    )
    parser.add_argument("output", type=Path, help="the folder of the mods, replaced")
    parser.add_argument(
        "mods", type=Path, nargs="+", help="the mods' .toml files, or folders of them"
    )
    arguments = parser.parse_args()

    # Made next to the output first, so that a failure leaves the mods as they were
    new = arguments.output.with_name(arguments.output.name + ".new")
    shutil.rmtree(new, ignore_errors=True)
    new.mkdir(parents=True)
    try:
        configs = [
            config
            for path in arguments.mods
            for config in (sorted(path.glob("*.toml")) if path.is_dir() else [path])
        ]
        for config in configs:
            make_mod(config, arguments.game, arguments.workshop, new)
    except (ModError, OSError, tomllib.TOMLDecodeError) as error:
        shutil.rmtree(new, ignore_errors=True)
        print(f"make_mods.py: {error}", file=sys.stderr)
        return 1
    shutil.rmtree(arguments.output, ignore_errors=True)
    new.rename(arguments.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
