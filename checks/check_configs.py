#!/usr/bin/env python3
"""Format and check the game's configs of this repository (the cfg folders of game/common and of each
game's game/<game>, and servers' own cfg folders of servers/ and tests/integration/servers/).

Formats each line as the game's own configs write it: the cvar or command bare, its arguments quoted,
e.g. mp_roundtime "600", exec "doi-config/bot_logic.cfg". Then checks each config against the cvars and
commands of the game it runs in (checks/cvars/<game>.json, see checks/dump_cvars.py) and those of the
plugins of this repository: a config of game/common against those of every game, of game/<game>
against its game's, a server's own against its server.toml's game's. A finding of some of the games
names them.

- every name is a cvar or a command, and a command's arguments keep to its signature of
  checks/commands.toml, where it has one (whose commands have to be the games' or the plugins'),
- a cvar gets one value, a number within its bounds where it has bounds,
- a cheat cvar is only set if nwi_cvar_unlocker removes its cheat flag (its config,
  game/common/addons/sourcemod/configs/nwi_cvar_unlocker.cfg, the game's section); its bounds replace
  the game's, a bound it calculates (team_slots) isn't checked,
- the configs of the game modes keep to nwi_mode_config.sp: the configs it runs (basic_mode_*.cfg,
  mode_*.cfg) only set cvars with nwi_mode_cvar, which no other config uses, so that the settings of a
  game mode are undone when it changes,
- an exec'd config of ours (nwi-config, doi-config) exists in the game's game/<game> or game/common,
  or the server's own cfg, but for the playlists' configs (nwi-config/playlists), which nwi-server
  make-mods makes.

Usage: check_configs.py   (in the repository; exit status 1 on findings, or if a file was reformatted)
"""

import json
import re
import sys
import tomllib
from pathlib import Path

from srctools.keyvalues import Keyvalues

REPO = Path(__file__).resolve().parent.parent
SCRIPTING = REPO / "game/common/addons/sourcemod/scripting"
CVARS = REPO / "checks/cvars"
SIGNATURES = REPO / "checks/commands.toml"
# The types of commands.toml's arguments, and value-of:<argument>
TYPES = {"path", "cvar", "int", "enum"}
GAMES = ("doi", "insurgency")
UNLOCKER = REPO / "game/common/addons/sourcemod/configs/nwi_cvar_unlocker.cfg"
# A line's tokens: quoted, a comment, or bare
TOKEN = re.compile(r'"(?P<quoted>[^"]*)"|(?P<comment>//.*)|(?P<bare>[^\s"]+)')


def configs() -> list[Path]:
    return sorted(
        [
            *(REPO / "game").glob("*/cfg/**/*.cfg"),
            *(REPO / "servers").glob("*/cfg/**/*.cfg"),
            *(REPO / "tests/integration/servers").glob("*/cfg/**/*.cfg"),
        ]
    )


def parse(line: str) -> tuple[list[str], str]:
    """A line's tokens, unquoted, and its comment."""
    tokens: list[str] = []
    for match in TOKEN.finditer(line):
        if match["comment"] is not None:
            return tokens, match["comment"]
        tokens.append(match["quoted"] if match["quoted"] is not None else match["bare"])
    return tokens, ""


def format_line(line: str) -> str:
    tokens, comment = parse(line)
    if not tokens:
        return line.rstrip()
    text = " ".join([tokens[0], *(f'"{token}"' for token in tokens[1:])])
    return f"{text} {comment}" if comment else text


def plugin_names() -> tuple[set[str], set[str]]:
    """The cvars and commands of the plugins of this repository, from their sources."""
    cvars, commands = set(), set()
    for source in SCRIPTING.glob("*.sp"):
        text = source.read_text(errors="replace")
        cvars |= {
            name.lower() for name in re.findall(r'CreateConVar\(\s*"([^"]+)"', text)
        }
        commands |= {
            name.lower()
            for name in re.findall(
                r'Reg(?:Server|Admin|Console)Cmd\(\s*"([^"]+)"', text
            )
        }
    return cvars, commands


def games_of(path: Path) -> list[str]:
    """The games a config runs in: every game for game/common's, the game of game/<game>, and of a
    server's own its server.toml's (Day of Infamy without one)."""
    parts = path.relative_to(REPO).parts
    if parts[0] == "game":
        return list(GAMES) if parts[1] == "common" else [parts[1]]
    # servers/<server>/cfg/… or tests/integration/servers/<server>/cfg/…
    server = REPO.joinpath(*parts[: parts.index("cfg")])
    toml = server / "server.toml"
    if not toml.is_file():
        return ["doi"]
    with toml.open("rb") as file:
        return [str(tomllib.load(file).get("game", "doi"))]


def unlocker(game: str) -> tuple[set[str], dict[str, float | None]]:
    """The cvars nwi_cvar_unlocker removes the cheat flag of in the game, and its upper bounds: a
    number, None where the plugin calculates it, or missing where it keeps the game's."""
    root = Keyvalues.parse(UNLOCKER.read_text(), UNLOCKER)
    # The keys' names in lower case, as srctools gives them
    config = root.find_key("nwi_cvar_unlocker").find_key(game, or_blank=True)
    cheats = {
        flags.name
        for flags in config.find_key("remove_flags", or_blank=True)
        if "cheat" in flags.value.split()
    }
    bounds: dict[str, float | None] = {}
    for bound in config.find_key("bounds", or_blank=True):
        name, value = bound.name, bound.value
        parts = value.split()
        if len(parts) == 3 and parts[1] == "team_slots":
            bounds[name] = None
        elif len(parts) == 2 and parts[1] != "-":
            bounds[name] = float(parts[1])
    return cheats, bounds


def signatures() -> dict[str, list[dict]]:
    """The commands' arguments of commands.toml, by the commands' names."""
    with SIGNATURES.open("rb") as file:
        return {
            name.lower(): table.get("args", [])
            for name, table in tomllib.load(file).items()
        }


def check_signatures(
    signatures: dict[str, list[dict]], commands: set[str]
) -> list[str]:
    """The findings of commands.toml: commands the games and plugins don't have, arguments without a
    name or of an unknown type, value-of an argument that isn't an earlier cvar, and a required
    argument after an optional one."""
    where = SIGNATURES.relative_to(REPO)
    findings = []
    for command, arguments in signatures.items():
        if command not in commands:
            findings.append(
                f"{where}: {command} is neither the games' nor the plugins' command"
            )
        earlier: dict[str, str] = {}
        optional = False
        for argument in arguments:
            name, kind = argument.get("name"), str(argument.get("type"))
            target = kind.removeprefix("value-of:")
            if not name:
                findings.append(f"{where}: an argument of {command} has no name")
            if kind.startswith("value-of:") and earlier.get(target) != "cvar":
                findings.append(
                    f"{where}: {command}'s {name} is the value of {target}, which isn't an earlier cvar"
                )
            elif not kind.startswith("value-of:") and kind not in TYPES:
                findings.append(
                    f"{where}: {command}'s {name} is of an unknown type {kind}"
                )
            if optional and not argument.get("optional"):
                findings.append(
                    f"{where}: {command}'s {name} is required after an optional one"
                )
            optional = optional or bool(argument.get("optional"))
            earlier[str(name)] = kind
    return findings


def check(
    path: Path,
    game: str,
    data: dict,
    names: tuple[set[str], set[str]],
    signatures: dict[str, list[dict]],
) -> list[str]:
    """The findings of a config in a game, with the game's cvars and commands (DATA) and the commands'
    SIGNATURES."""
    cvars = data["cvars"]
    commands = set(data["commands"])
    plugin_cvars, plugin_commands = names
    cheats, bounds = unlocker(game)
    relative = path.relative_to(REPO)
    mode_config = re.fullmatch(r"(basic_)?mode_.*\.cfg", path.name) is not None
    findings = []

    def setting(number: int, name: str, values: list[str]) -> None:
        where = f"{relative}:{number}"
        name = name.lower()
        if name not in cvars and name not in plugin_cvars:
            findings.append(f"{where}: {name} isn't a cvar")
            return
        if len(values) != 1:
            findings.append(f"{where}: {name} takes one value, not {len(values)}")
            return
        cvar = cvars.get(name, {})
        if "cheat" in cvar.get("flags", []) and name not in cheats:
            findings.append(
                f"{where}: {name} is a cheat cvar, which nwi_cvar_unlocker.cfg doesn't unlock"
            )
        low, high = cvar.get("min"), cvar.get("max")
        if name in bounds:
            high = bounds[name]
        if low is None and high is None:
            return
        try:
            value = float(values[0])
        except ValueError:
            findings.append(f"{where}: {name} takes a number, not {values[0]!r}")
            return
        if low is not None and value < low or high is not None and value > high:
            findings.append(
                f"{where}: {name} {values[0]} is out of its bounds {low} to {high}"
            )

    def arguments_of(number: int, command: str, arguments: list[str]) -> None:
        """A command's arguments by its signature."""
        where = f"{relative}:{number}"
        spec = signatures[command]
        required = sum(1 for argument in spec if not argument.get("optional"))
        if not required <= len(arguments) <= len(spec):
            expected = (
                str(required) if required == len(spec) else f"{required} to {len(spec)}"
            )
            plural = "" if expected == "1" else "s"
            findings.append(
                f"{where}: {command} takes {expected} argument{plural}, not {len(arguments)}"
            )
            return
        given = {argument["name"]: value for argument, value in zip(spec, arguments)}
        # The cvars whose values are given too, which setting() checks with the value
        valued = {
            argument["type"].removeprefix("value-of:")
            for argument in spec[: len(arguments)]
            if argument["type"].startswith("value-of:")
        }
        for argument, value in zip(spec, arguments):
            kind = argument["type"]
            if kind == "cvar" and argument["name"] not in valued:
                if value.lower() not in cvars and value.lower() not in plugin_cvars:
                    findings.append(f"{where}: {value} isn't a cvar")
            elif kind.startswith("value-of:"):
                setting(number, given[kind.removeprefix("value-of:")], [value])
            elif kind == "int":
                try:
                    number_value = int(value)
                except ValueError:
                    findings.append(
                        f"{where}: {command}'s {argument['name']} is a whole number, not {value!r}"
                    )
                    continue
                low, high = argument.get("min"), argument.get("max")
                if (
                    low is not None
                    and number_value < low
                    or (high is not None and number_value > high)
                ):
                    findings.append(
                        f"{where}: {command}'s {argument['name']} {value} is out of its bounds "
                        f"{low} to {high}"
                    )
            elif kind == "enum" and value not in argument.get("values", []):
                findings.append(
                    f"{where}: {command}'s {argument['name']} is one of "
                    f"{', '.join(argument['values'])}, not {value!r}"
                )
            elif kind == "path" and argument.get("relative") == "cfg":
                exists(where, value)

    def exists(where: str, target: str) -> None:
        """A config of ours (nwi-config, doi-config) in the game's folders or the server's own, but for
        the playlists' configs, which nwi-server make-mods makes."""
        ours = target.startswith(("nwi-config/", "doi-config/"))
        made = target.startswith("nwi-config/playlists/")
        folders = [REPO / "game" / game, REPO / "game/common"]
        parts = path.relative_to(REPO).parts
        if parts[0] != "game":
            # A server's own: servers/<server>/cfg/… or tests/integration/servers/<server>/cfg/…
            folders.append(REPO.joinpath(*parts[: parts.index("cfg")]))
        if (
            ours
            and not made
            and not any((folder / "cfg" / target).is_file() for folder in folders)
        ):
            findings.append(f"{where}: there's no {target}")

    for number, line in enumerate(path.read_text().splitlines(), 1):
        tokens, _ = parse(line)
        if not tokens:
            continue
        where = f"{relative}:{number}"
        command, arguments = tokens[0].lower(), tokens[1:]
        if mode_config and command != "nwi_mode_cvar":
            findings.append(
                f"{where}: a game mode's config only sets cvars with nwi_mode_cvar"
            )
        elif command == "nwi_mode_cvar" and not mode_config:
            findings.append(f"{where}: nwi_mode_cvar is for the game modes' configs")
        if command in signatures:
            arguments_of(number, command, arguments)
        elif command in commands or command in plugin_commands:
            continue
        else:
            setting(number, command, arguments)
    return findings


def main() -> int:
    data = {game: json.loads((CVARS / f"{game}.json").read_text()) for game in GAMES}
    names = plugin_names()
    commands = signatures()
    status = 0
    known = names[1].union(*(game["commands"] for game in data.values()))
    for finding in check_signatures(commands, known):
        print(finding, file=sys.stderr)
        status = 1
    for path in configs():
        text = path.read_text()
        formatted = "".join(f"{format_line(line)}\n" for line in text.splitlines())
        if formatted != text:
            path.write_text(formatted)
            print(f"{path.relative_to(REPO)}: formatted", file=sys.stderr)
            status = 1
        # Each finding once, with the games it's of if it isn't of all the config runs in
        games = games_of(path)
        findings: dict[str, list[str]] = {}
        for game in games:
            for finding in check(path, game, data[game], names, commands):
                findings.setdefault(finding, []).append(game)
        for finding, of in findings.items():
            suffix = f" (in {', '.join(of)})" if len(games) > 1 and of != games else ""
            print(finding + suffix, file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
