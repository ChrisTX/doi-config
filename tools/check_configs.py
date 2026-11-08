#!/usr/bin/env python3
"""Format and check the game's configs of this repository (game/cfg, servers/*/cfg).

Formats each line as the game's own configs write it: the cvar or command bare, its arguments quoted,
e.g. mp_roundtime "600", exec "doi-config/bot_logic.cfg". Then checks against the server's cvars and
commands (tools/cvars.json, see tools/dump_cvars.py) and those of the plugins of this repository:

- every name is a cvar or a command,
- a cvar gets one value, a number within its bounds where it has bounds,
- a cheat cvar is only set if doi_cvar_unlocker.sp removes its cheat flag; the plugin's upper bounds
  replace the game's, a bound it calculates (not a number) isn't checked,
- the configs of the game modes keep to doi_mode_config.sp: cfg/server_<mode>.cfg only names the game
  mode (doi_mode), the configs it runs (basic_mode_*.cfg, mode_*.cfg) only set cvars with
  doi_mode_cvar, which no other config uses, so that the settings of a game mode are undone when it
  changes,
- an exec'd config of doi-config exists, but for the playlists' configs, which tools/make_mods.py makes.

Usage: check_configs.py   (in the repository; exit status 1 on findings, or if a file was reformatted)
"""

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTING = REPO / "game/addons/sourcemod/scripting"
# A line's tokens: quoted, a comment, or bare
TOKEN = re.compile(r'"(?P<quoted>[^"]*)"|(?P<comment>//.*)|(?P<bare>[^\s"]+)')


def configs() -> list[Path]:
    return sorted(
        [*(REPO / "game/cfg").rglob("*.cfg"), *(REPO / "servers").glob("*/cfg/*.cfg")]
    )


def parse(line: str) -> tuple[list[str], str]:
    """A line's tokens, unquoted, and its comment."""
    tokens = []
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


def unlocker() -> tuple[set[str], dict[str, float | None]]:
    """The cvars doi_cvar_unlocker.sp removes the cheat flag of, and its upper bounds: a number, or
    None where the plugin calculates it."""
    text = (SCRIPTING / "doi_cvar_unlocker.sp").read_text()
    cheats = {
        name.lower() for name in re.findall(r'RemoveCheatFlag\("([^"]+)"\)', text)
    }
    bounds: dict[str, float | None] = {}
    for name, bound in re.findall(r'SetVarUpperBound\("([^"]+)",\s*(.+?)\);', text):
        try:
            bounds[name.lower()] = float(bound)
        except ValueError:
            bounds[name.lower()] = None
    return cheats, bounds


def check(path: Path, data: dict, names: tuple[set[str], set[str]]) -> list[str]:
    """The findings of a config."""
    cvars = data["cvars"]
    commands = set(data["commands"])
    plugin_cvars, plugin_commands = names
    cheats, bounds = unlocker()
    relative = path.relative_to(REPO)
    mode_runner = path.parent == REPO / "game/cfg" and path.name.startswith("server_")
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
                f"{where}: {name} is a cheat cvar, which doi_cvar_unlocker.sp doesn't unlock"
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

    for number, line in enumerate(path.read_text().splitlines(), 1):
        tokens, _ = parse(line)
        if not tokens:
            continue
        where = f"{relative}:{number}"
        command, arguments = tokens[0].lower(), tokens[1:]
        if mode_runner and command != "doi_mode":
            findings.append(f"{where}: a game mode's server_*.cfg only has doi_mode")
        elif mode_config and command != "doi_mode_cvar":
            findings.append(
                f"{where}: a game mode's config only sets cvars with doi_mode_cvar"
            )
        elif command == "doi_mode_cvar" and not mode_config:
            findings.append(f"{where}: doi_mode_cvar is for the game modes' configs")
        if command == "doi_mode_cvar":
            if arguments:
                setting(number, arguments[0], arguments[1:])
            else:
                findings.append(f"{where}: doi_mode_cvar without a cvar")
        elif command == "exec":
            target = arguments[0] if arguments else ""
            ours = target.startswith("doi-config/")
            made = target.startswith("doi-config/playlists/")
            if ours and not made and not (REPO / "game/cfg" / target).is_file():
                findings.append(f"{where}: there's no {target}")
        elif command in commands or command in plugin_commands:
            continue
        else:
            setting(number, command, arguments)
    return findings


def main() -> int:
    data = json.loads((REPO / "tools/cvars.json").read_text())
    names = plugin_names()
    status = 0
    for path in configs():
        text = path.read_text()
        formatted = "".join(f"{format_line(line)}\n" for line in text.splitlines())
        if formatted != text:
            path.write_text(formatted)
            print(f"{path.relative_to(REPO)}: formatted", file=sys.stderr)
            status = 1
        for finding in check(path, data, names):
            print(finding, file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
