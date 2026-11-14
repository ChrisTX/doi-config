#!/usr/bin/env python3
"""Make the mods of mods/*.toml from the game's map scripts and playlists.

A map's script, maps/<map>.txt, configures its game modes, a block each: the teams, the control points
in the order they're taken, the spawn zones and the entities. The game ships the scripts in its VPKs
(doi/*_dir.vpk), a workshop map in its item, as a file or in a VPK. A mod copies a block under the name of another game mode,
e.g. offensive as invasion, which the map doesn't have, and adjusts the copy. The mods are made from
the installed game, so they follow its updates, and this repository only holds the rules.

Each mods/<mod>.toml makes the mod folder custom/<mod> of the output, with the scripts of its maps:

    # A map's script comes from the game, unless the map is from the workshop: map = item ID
    [workshop]
    tobruk = 823637416

    # Maps whose scripts are only repaired and formatted, without copies
    [fix]
    maps = ["tobruk"]

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

A mod's [[playlist]] tables make configs of a playlist's settings instead, of scripts/playlists/<name>.playlist:
the settings of its forced_cvars and forced_cvars_dedicated whose names match the include globs and none
of the exclude ones. The nwi_playlist_unlock plugin stops the game forcing them, so a server takes over
the ones it wants, as a baseline it can change:

    [[playlist]]
    name = "nwi/coop_commando"
    include = ["doi_*", "sv_firesupport_cooldown_frac"]
    exclude = ["doi_bot_quota"]

A mod's [[replace]] tables make replacements of playlists, which nwi_playlist_unlock loads instead of
the game's when a playlist has one. A table changes the playlists whose names match its playlists
globs and none of its exclude ones: drop removes keys, with their merge methods (<key>_merge_method),
and set sets keys, replacing those of the same name, a table becoming a section. They change the
playlist's own keys; its rulesets change only by the table's [[replace.ruleset]] tables, each for the
rulesets that match its rulesets globs and none of its exclude ones. The tables apply in order, those
of all mods; a glob of playlists or rulesets that matches none is an error. A playlist that no table
matches gets no replacement and stays as the game has it:

    [[replace]]
    playlists = ["nwi/*"]
    drop = ["allowed_maps", "forced_cvars", "forced_cvars_dedicated"]
    # A section of its own, e.g. for a server for newcomers
    set = { rank_limits = { min = "0", max = "10" } }

    # The rulesets without their maps, except the campaigns, which keep theirs and their teams
    [[replace.ruleset]]
    rulesets = ["*"]
    exclude = ["*_campaign"]
    drop = ["allowed_maps"]

    [[replace.ruleset]]
    rulesets = ["*"]
    drop = ["forced_cvars", "forced_cvars_dedicated"]

A [[replace.ruleset]] table belongs to the [[replace]] table before it, as does a [replace.set] table,
the same as set = { ... } in it.

They make cfg/doi-config/playlists/<name>.playlist of the output.

The [[playlist]] tables make cfg/doi-config/playlists/<name>.cfg of the output, which sets the settings,
for a server's server.cfg (playlist of its server.toml, which sets sv_playlist), and cfg/doi-config/playlists/<name>-<mode>.cfg for each game mode
whose block of settings has some, with nwi_mode_cvar, for the game mode's configs (see
nwi_mode_config.sp). An include glob that matches nothing is an error, e.g. after a game update that
changed the playlist.

The output is the rest of the script as it is, with the copies after the blocks they're made from, in
the game's format, indented anew and without comments. Braces in the wrong place are repaired, as far
as the keys of a level show where a block ends (see parse_script()). A copy whose block the map
doesn't have, or which names a control point that the block doesn't have, is an error, e.g. after a
game update that changed the map.

With --check, nothing is made: every map script of the game and of the workshop items is parsed, and
those whose braces had to be repaired, or can't be, are listed, the latter with an exit status of 1. A
broken script of a workshop map can be repaired with a mod that has the map in its fix list.

Usage: make_mods.py --game DIR --workshop DIR OUTPUT MODS...
       make_mods.py --game DIR --workshop DIR --check

--game is the game's install, with doi/ in it, --workshop SteamCMD's folder of the workshop items
(steamapps/workshop/content/447820/<item> in it). MODS are the mods' .toml files, or folders of them.
OUTPUT is replaced.
"""

import argparse
import fnmatch
import re
import shutil
import sys
import tomllib
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from srctools.vpk import VPK, FileInfo

GAME_APP = 447820

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

PLAYLIST_KEYS = {"name", "include", "exclude"}
REPLACE_KEYS = {"playlists", "exclude", "drop", "set", "ruleset"}
RULESET_KEYS = {"rulesets", "exclude", "drop", "set"}
# The blocks of a playlist with the settings it forces, the latter only on dedicated servers
PLAYLIST_FORCED = ("forced_cvars", "forced_cvars_dedicated")

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


def parse_script(
    text: str, source: str, level: Level | None = FILE_LEVEL
) -> tuple[Pairs, list[str]]:
    """Parse a map's script into its pairs, without its comments, and repair its braces: a key that
    its level doesn't have, but a level it's in, closes the blocks up to that level, e.g. a game mode in
    a game mode that isn't closed, and a closing brace after the file's block is dropped. Returns the
    pairs and what was repaired; a script whose blocks still don't match, or that has a key no level
    takes, is an error. With level None, any key goes, for other files of the game's format."""
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
    stack: list[tuple[Level | None, Pairs, str]] = [(level, file, "the file")]
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


def vpk_files(vpk: Path) -> dict[str, Callable[[], bytes]]:
    """List a VPK's files by their paths in lower case, with a function each that reads the file and
    checks it against its checksum: of a VPK of several files, its directory file (<name>_dir.vpk),
    or a VPK of one file. srctools reads the VPK."""
    try:
        archive = VPK(vpk)
    except ValueError as error:
        raise ModError(f"{vpk} isn't a VPK: {error}") from error

    def reader(info: FileInfo, path: str) -> Callable[[], bytes]:
        def read() -> bytes:
            content = info.read()
            if zlib.crc32(content) != info.crc:
                raise ModError(f"{path} in {vpk} doesn't match its checksum")
            return content

        return read

    return {
        info.filename.lower(): reader(info, info.filename.lower()) for info in archive
    }


def map_scripts(folder: Path) -> dict[str, tuple[str, Callable[[], bytes]]]:
    """List the map scripts of the game's doi folder or of a workshop item, by their paths
    (maps/<map>.txt), with where each is from and a function that reads it: its files first, then its
    VPKs. The numbered archives of a VPK (<name>_000.vpk) are read through its directory file."""
    scripts = {}
    for path in sorted(folder.glob("maps/*.txt")):
        scripts[f"maps/{path.name.lower()}"] = (str(path), path.read_bytes)
    for vpk in sorted(folder.glob("*.vpk")):
        if re.search(r"_\d{3}\.vpk$", vpk.name):
            continue
        for path, read in vpk_files(vpk).items():
            if re.fullmatch(r"maps/[^/]+\.txt", path) and path not in scripts:
                scripts[path] = (f"{vpk}/{path}", read)
    return scripts


def item_folder(workshop: Path, item: int) -> Path:
    """The folder of a workshop item in SteamCMD's folder of the workshop items."""
    return workshop / "steamapps/workshop/content" / str(GAME_APP) / str(item)


def read_script(
    game: Path, workshop: Path, workshop_maps: dict[str, int], name: str
) -> tuple[Pairs, list[str]]:
    """Read and parse a map's script, see parse_script(): a workshop map's from its item, a map of the
    game's from its doi folder."""
    wanted = f"maps/{name.lower()}.txt"
    if name in workshop_maps:
        scripts = map_scripts(item_folder(workshop, workshop_maps[name]))
        where = f"the workshop item {workshop_maps[name]}"
    else:
        scripts = map_scripts(game / "doi")
        where = "the game"
    if wanted not in scripts:
        raise ModError(f"{name}: {where} has no {wanted}")
    source, read = scripts[wanted]
    return parse_script(read().decode("utf-8", errors="replace"), source)


def game_file(game: Path, path: str) -> tuple[str, bytes]:
    """Read a file of the game's doi folder, with where it's from: the file itself, or from a VPK."""
    loose = game / "doi" / path
    if loose.is_file():
        return str(loose), loose.read_bytes()
    for vpk in sorted((game / "doi").glob("*_dir.vpk")):
        read = vpk_files(vpk).get(path.lower())
        if read is not None:
            return f"{vpk}/{path}", read()
    raise ModError(f"the game has no {path}")


def check_scripts(game: Path, workshop: Path) -> int:
    """Parse every map script of the game and of the workshop items, and report those that had to be
    repaired, or can't be: they'd need a mod that has their maps in its fix list. Returns the number of
    scripts that can't be repaired."""
    folders = [game / "doi"]
    content = workshop / "steamapps/workshop/content" / str(GAME_APP)
    if content.is_dir():
        folders += sorted(path for path in content.iterdir() if path.is_dir())
    checked = repaired = broken = 0
    for folder in folders:
        for source, read in map_scripts(folder).values():
            checked += 1
            try:
                _, repairs = parse_script(
                    read().decode("utf-8", errors="replace"), source
                )
            except ModError as error:
                broken += 1
                print(f"error: {error}", file=sys.stderr)
                continue
            if repairs:
                repaired += 1
                print(f"repaired: {source}: {', '.join(repairs)}", file=sys.stderr)
    print(
        f"{checked} map scripts, {repaired} repaired, {broken} that can't be",
        file=sys.stderr,
    )
    return broken


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


@dataclass
class Actions:
    """What a [[replace]] or [[replace.ruleset]] table changes in a block: the keys it drops, with their
    merge methods, then the keys it sets, a TOML table becoming a section."""

    drop: list[str]
    set: Pairs

    @classmethod
    def from_table(cls, table: dict, where: str) -> "Actions":
        drop = table.get("drop", [])
        if not isinstance(drop, list) or not all(isinstance(key, str) for key in drop):
            raise ModError(f"{where}: drop is a list of keys")
        settings = table.get("set", {})
        if not isinstance(settings, dict):
            raise ModError(f"{where}: set is a table")
        return cls(drop=list(drop), set=toml_pairs(settings, f"{where}: set"))

    def __bool__(self) -> bool:
        return bool(self.drop or self.set)

    def apply(self, block: Pairs) -> None:
        dropped = {key.lower() for key in self.drop}
        dropped |= {f"{key}_merge_method" for key in dropped}
        dropped |= {key.lower() for key, _ in self.set}
        block[:] = [(key, value) for key, value in block if key.lower() not in dropped]
        block += self.set


def toml_pairs(table: dict, where: str) -> Pairs:
    """A TOML table as KeyValues pairs: strings and numbers as values, tables as sections."""
    pairs: Pairs = []
    for key, value in table.items():
        if isinstance(value, dict):
            pairs.append((key, toml_pairs(value, f"{where}.{key}")))
        elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
            pairs.append((key, str(value)))
        else:
            raise ModError(f"{where}.{key} is a string, a number or a table")
    return pairs


def matches_globs(name: str, globs: list[str], exclude: list[str]) -> bool:
    return any(
        fnmatch.fnmatchcase(name.lower(), glob.lower()) for glob in globs
    ) and not any(fnmatch.fnmatchcase(name.lower(), glob.lower()) for glob in exclude)


@dataclass
class RulesetRule:
    """A [[replace.ruleset]] table: what changes in the rulesets of a playlist its globs match."""

    rulesets: list[str]
    exclude: list[str]
    actions: Actions

    @classmethod
    def from_table(cls, table: dict, where: str) -> "RulesetRule":
        unknown = set(table) - RULESET_KEYS
        if unknown:
            raise ModError(f"{where}: unknown keys {', '.join(sorted(unknown))}")
        actions = Actions.from_table(table, where)
        if not table.get("rulesets") or not actions:
            raise ModError(
                f"{where}: a ruleset's table needs rulesets, and drop or set"
            )
        return cls(
            rulesets=list(table["rulesets"]),
            exclude=list(table.get("exclude", [])),
            actions=actions,
        )

    def matches(self, name: str) -> bool:
        return matches_globs(name, self.rulesets, self.exclude)


@dataclass
class Replace:
    """A [[replace]] table: what changes in the playlists its globs match, in their own keys and, by
    its [[replace.ruleset]] tables, in their rulesets."""

    playlists: list[str]
    exclude: list[str]
    actions: Actions
    rulesets: list[RulesetRule]
    mod: str

    @classmethod
    def from_table(cls, table: dict, mod: str) -> "Replace":
        unknown = set(table) - REPLACE_KEYS
        if unknown:
            raise ModError(
                f"{mod}: unknown keys in a replacement: {', '.join(sorted(unknown))}"
            )
        actions = Actions.from_table(table, f"{mod}: replace")
        rules = table.get("ruleset", [])
        if not isinstance(rules, list):
            raise ModError(f"{mod}: ruleset is a list of tables, [[replace.ruleset]]")
        rulesets = [
            RulesetRule.from_table(rule, f"{mod}: replace.ruleset") for rule in rules
        ]
        if not table.get("playlists") or not (actions or rulesets):
            raise ModError(
                f"{mod}: a replacement needs playlists, and drop, set or ruleset tables"
            )
        return cls(
            playlists=list(table["playlists"]),
            exclude=list(table.get("exclude", [])),
            actions=actions,
            rulesets=rulesets,
            mod=mod,
        )

    def matches(self, name: str) -> bool:
        return matches_globs(name, self.playlists, self.exclude)

    def apply(self, root: Pairs) -> set[str]:
        """Change a playlist: its own keys, then its rulesets'. Returns the names of its rulesets."""
        self.actions.apply(root)
        names = set()
        for key, rulesets in root:
            if key.lower() != "rulesets" or isinstance(rulesets, str):
                continue
            for name, block in rulesets:
                if isinstance(block, str):
                    continue
                names.add(name.lower())
                for rule in self.rulesets:
                    if rule.matches(name):
                        rule.actions.apply(block)
        return names


def game_playlists(game: Path) -> dict[str, tuple[str, Callable[[], bytes]]]:
    """The game's playlists by their names (scripts/playlists/<name>.playlist), with where each is from
    and a function that reads it: its loose files first, then its VPKs."""
    playlists: dict[str, tuple[str, Callable[[], bytes]]] = {}
    folder = game / "doi/scripts/playlists"
    if folder.is_dir():
        for path in sorted(folder.rglob("*.playlist")):
            name = path.relative_to(folder).with_suffix("").as_posix().lower()
            playlists[name] = (str(path), path.read_bytes)
    for vpk in sorted((game / "doi").glob("*_dir.vpk")):
        for path, read in vpk_files(vpk).items():
            match = re.fullmatch(r"scripts/playlists/(.+)\.playlist", path)
            if match and match[1] not in playlists:
                playlists[match[1]] = (f"{vpk}/{path}", read)
    return playlists


def make_replacements(game: Path, replaces: list[Replace], output: Path) -> None:
    """Write the replacements of the playlists the [[replace]] tables match, see the module's
    documentation."""
    if not replaces:
        return
    playlists = game_playlists(game)
    for replace in replaces:
        unused = [
            glob
            for glob in replace.playlists
            if not any(fnmatch.fnmatchcase(name, glob.lower()) for name in playlists)
        ]
        if unused:
            raise ModError(f"{replace.mod}: no playlist matches {', '.join(unused)}")
    made = 0
    # The rulesets of the playlists each [[replace]] table changed, for its ruleset globs
    rulesets: dict[int, set[str]] = {index: set() for index in range(len(replaces))}
    for name, (source, read) in sorted(playlists.items()):
        matching = [replace for replace in replaces if replace.matches(name)]
        if not matching:
            continue
        (root_key, root), *_ = parse_script(
            read().decode("utf-8", errors="replace"), source, level=None
        )[0]
        if isinstance(root, str):
            raise ModError(f"{source} isn't a block")
        for index, replace in enumerate(replaces):
            if replace.matches(name):
                rulesets[index] |= replace.apply(root)
        mods = ", ".join(
            dict.fromkeys(f"mods/{replace.mod}.toml" for replace in matching)
        )
        path = output / "cfg/doi-config/playlists" / f"{name}.playlist"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"// Made by tools/make_mods.py from the game's scripts/playlists/{name}.playlist,\n"
            f"// as {mods} replaces it\n" + format_keyvalues([(root_key, root)]),
            encoding="utf-8",
        )
        made += 1
    for index, replace in enumerate(replaces):
        unused = [
            glob
            for rule in replace.rulesets
            for glob in rule.rulesets
            if not any(
                fnmatch.fnmatchcase(name, glob.lower()) for name in rulesets[index]
            )
        ]
        if unused:
            raise ModError(f"{replace.mod}: no ruleset matches {', '.join(unused)}")
    print(f"playlists: {made} replacements", file=sys.stderr)


@dataclass
class Playlist:
    """The settings of a playlist that a server takes over, from a mod's [[playlist]] table."""

    name: str
    include: list[str]
    exclude: list[str]

    @classmethod
    def from_table(cls, table: dict, mod: str) -> "Playlist":
        unknown = set(table) - PLAYLIST_KEYS
        if unknown:
            raise ModError(
                f"{mod}: unknown keys in a playlist: {', '.join(sorted(unknown))}"
            )
        if "name" not in table or not table.get("include"):
            raise ModError(f"{mod}: a playlist needs a name and include globs")
        return cls(
            name=table["name"],
            include=list(table["include"]),
            exclude=list(table.get("exclude", [])),
        )

    def takes(self, name: str) -> bool:
        name = name.lower()
        return any(
            fnmatch.fnmatchcase(name, glob.lower()) for glob in self.include
        ) and not any(fnmatch.fnmatchcase(name, glob.lower()) for glob in self.exclude)

    def make(self, game: Path, output: Path, mod: str) -> None:
        """Write the playlist's configs, see the module's documentation."""
        source, data = game_file(game, f"scripts/playlists/{self.name}.playlist")
        (_, root), *_ = parse_script(
            data.decode("utf-8", errors="replace"), source, level=None
        )[0]
        if isinstance(root, str):
            raise ModError(f"{source} isn't a block")
        settings: dict[str, str] = {}
        modes: dict[str, dict[str, str]] = {}
        for key, block in root:
            if key.lower() not in PLAYLIST_FORCED or isinstance(block, str):
                continue
            for name, value in block:
                if isinstance(value, str):
                    if self.takes(name):
                        settings[name] = value
                # A game mode's block; others, like the plugins', aren't settings
                elif name.lower() in GAME_MODES:
                    for setting, mode_value in value:
                        if isinstance(mode_value, str) and self.takes(setting):
                            modes.setdefault(name.lower(), {})[setting] = mode_value
        taken = [*settings, *(name for block in modes.values() for name in block)]
        unused = [
            glob
            for glob in self.include
            if not any(
                fnmatch.fnmatchcase(name.lower(), glob.lower()) for name in taken
            )
        ]
        if unused:
            raise ModError(
                f"{mod}: {self.name} has no forced settings matching {', '.join(unused)}"
            )
        folder = output / "cfg/doi-config/playlists"
        header = (
            f"// Made by tools/make_mods.py from the game's scripts/playlists/{self.name}.playlist:\n"
            f"// the settings it forces that mods/{mod}.toml takes over"
        )
        path = folder / f"{self.name}.cfg"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [header, ""]
        lines += [f'{name} "{value}"' for name, value in settings.items()]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        for mode, block in modes.items():
            lines = [f"{header}, for {mode}", ""]
            lines += [
                f'nwi_mode_cvar "{name}" "{value}"' for name, value in block.items()
            ]
            (folder / f"{self.name}-{mode}.cfg").write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )
        print(
            f"{mod}: {self.name}: {len(settings)} settings, game modes {', '.join(modes) or 'none'}",
            file=sys.stderr,
        )


def make_mod(config: Path, game: Path, workshop: Path, output: Path) -> list[Replace]:
    """Make the mod of a mods/<mod>.toml in output/custom/<mod>, and its playlists' configs in
    output/cfg/doi-config/playlists; returns its replacements of playlists, which make_replacements()
    makes with those of all mods."""
    mod = config.stem
    with config.open("rb") as file:
        settings = tomllib.load(file)
    unknown = set(settings) - {"workshop", "fix", "copy", "playlist", "replace"}
    if unknown:
        raise ModError(f"{mod}: unknown tables {', '.join(sorted(unknown))}")
    # Tables, so that a key after one doesn't end up in it by mistake: TOML's keys after a table's
    # header are the table's
    workshop_maps = settings.get("workshop", {})
    for name, item in workshop_maps.items():
        if not isinstance(item, int):
            raise ModError(f"{mod}: the workshop item of {name} isn't an ID: {item!r}")
    fix = settings.get("fix", {})
    if not isinstance(fix, dict) or set(fix) - {"maps"}:
        raise ModError(f"{mod}: fix is a table with the maps' list only")
    copies = [Copy.from_table(table, mod) for table in settings.get("copy", [])]
    for table in settings.get("playlist", []):
        Playlist.from_table(table, mod).make(game, output, mod)
    replaces = [Replace.from_table(table, mod) for table in settings.get("replace", [])]
    maps = dict.fromkeys(
        [*fix.get("maps", []), *(name for copy in copies for name in copy.maps)]
    )
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
    if maps:
        print(f"{mod}: {len(maps)} maps", file=sys.stderr)
    return replaces


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Make the mods of mods/*.toml from the game's map scripts and playlists."
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
    parser.add_argument(
        "--check",
        action="store_true",
        help="check every map script of the game and the workshop items instead",
    )
    parser.add_argument(
        "output", type=Path, nargs="?", help="the folder of the mods, replaced"
    )
    parser.add_argument(
        "mods", type=Path, nargs="*", help="the mods' .toml files, or folders of them"
    )
    arguments = parser.parse_args()
    if arguments.check:
        if arguments.output is not None:
            parser.error("--check takes no output or mods")
        try:
            return 1 if check_scripts(arguments.game, arguments.workshop) else 0
        except (ModError, OSError) as error:
            print(f"make_mods.py: {error}", file=sys.stderr)
            return 1
    if arguments.output is None or not arguments.mods:
        parser.error("the output and the mods are required")

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
        replaces = []
        for config in configs:
            replaces += make_mod(config, arguments.game, arguments.workshop, new)
        make_replacements(arguments.game, replaces, new)
    except (ModError, OSError, tomllib.TOMLDecodeError) as error:
        shutil.rmtree(new, ignore_errors=True)
        print(f"make_mods.py: {error}", file=sys.stderr)
        return 1
    shutil.rmtree(arguments.output, ignore_errors=True)
    new.rename(arguments.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
