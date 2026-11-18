#!/usr/bin/env python3
"""Dump the cvars and commands of a running server, for checks/check_configs.py and for editors.

Lists every cvar with its default, its bounds and its flags, and every command with its flags, from
the server's cvarlist and the help of each, over RCON, with the game's version and build. Bounds and
flags are the server's as they are: those nwi_cvar_unlocker.smx changes are its own, which
check_configs.py takes from the plugin's source instead, so a dump from a server without the plugin is
the exact one (a server's nwi-server prepare disables it with DISABLE_PLUGINS=nwi_cvar_unlocker).
tests/integration/instance.py dump-cvars runs it on the test server of a game.

The descriptions, the help texts of the game, SourceMod and the plugins, aren't in the dump: they're
the game's and the others' texts, not this repository's to publish. With --descriptions FILE, they go
into that file, for a developer's own machine, e.g. checks/cvars/descriptions/<game>.json, which git
ignores: the help text of each cvar and command, and the usage where the help has one (a line
starting with "Usage:", or the command's name and its arguments, like sm_cvar <cvar> [value]).

The password comes from RCON_PASSWORD. The dump goes to the output, e.g. > checks/cvars/doi.json.
"""

import argparse
import json
import os
import re
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nwi_server_kit import rcon

# A line of cvarlist: the name, the value or "cmd", the flags and the description
LINE = re.compile(r"^(?P<name>\S+)\s+:\s(?P<value>.*?)\s+:\s(?P<flags>.*?)\s+:\s")
# The bounds in a cvar's help
BOUNDS = re.compile(r"\b(?P<which>min|max)\. (?P<value>-?[\d.]+)")
DEFAULT = re.compile(r'\( def\. "(?P<value>[^"]*)" \)')
# help's answer: "name" and, for a cvar, its value, default, bounds and flags, then " - " and the
# description, which may go on over more lines
HELP = re.compile(r'^"(?P<name>[^"]+)".*? - (?P<text>.*)', re.DOTALL)
# The game's version and build of version's answer: Exe version 3.2.1.5 (dayofinfamy), Exe build:
# 02:45:36 Nov 15 2017 (6948) (447820)
VERSION = re.compile(r"^Exe version (?P<version>\S+)", re.MULTILINE)
BUILD = re.compile(r"^Exe build: .*\((?P<build>\d+)\) \((?P<app>\d+)\)$", re.MULTILINE)
LOG_LINE = re.compile(r"^L \d\d/\d\d/\d{4} - ")


def answer(sock: socket.socket, command: str) -> str:
    """A command's answer without the log lines the server echoes into it."""
    text = rcon.run(sock, command)
    return "\n".join(line for line in text.splitlines() if not LOG_LINE.match(line))


def description(name: str, help_text: str) -> dict[str, str]:
    """The help's description of a cvar or command, and its usage where it has one."""
    match = HELP.match(help_text.strip())
    if match is None:
        return {}
    text = match["text"].strip()
    result = {"help": text}
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("usage:"):
            result["usage"] = line[len("usage:") :].strip()
            break
        if line.split(" ", 1)[0] == name and len(line.split()) > 1:
            result["usage"] = line
            break
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="the server's address (%(default)s)"
    )
    parser.add_argument(
        "--port", type=int, default=27015, help="the server's port (%(default)s)"
    )
    parser.add_argument(
        "--descriptions",
        type=Path,
        metavar="FILE",
        help="write the help texts into FILE too, for a developer's own machine",
    )
    arguments = parser.parse_args()
    password = os.environ.get("RCON_PASSWORD")
    if not password:
        print("RCON_PASSWORD isn't set", file=sys.stderr)
        return 2
    with rcon.connect(arguments.host, arguments.port, password) as sock:
        if '"NWI cvar unlocker"' in answer(sock, "sm plugins list"):
            print(
                "dump_cvars.py: nwi_cvar_unlocker.smx is loaded: the bounds and flags it changes "
                "are its own",
                file=sys.stderr,
            )
        version_text = answer(sock, "version")
        version, build = VERSION.search(version_text), BUILD.search(version_text)
        game = {
            "version": version["version"] if version else "",
            "build": int(build["build"]) if build else 0,
            "app": int(build["app"]) if build else 0,
        }
        cvars: dict[str, dict[str, str | float | list[str]]] = {}
        commands: dict[str, dict[str, list[str]]] = {}
        for line in answer(sock, "cvarlist").splitlines():
            match = LINE.match(line)
            if match is None:
                continue
            name = match["name"].lower()
            flags = sorted(re.findall(r'"([^"]+)"', match["flags"]))
            if match["value"].strip() == "cmd":
                commands[name] = {"flags": flags}
            else:
                # The value as the default, which help only names when the value differs from it
                cvars[name] = {"flags": flags, "default": match["value"].strip()}
        texts: dict[str, dict[str, dict[str, str]]] = {"cvars": {}, "commands": {}}
        for name, cvar in cvars.items():
            help_text = answer(sock, f"help {name}")
            default = DEFAULT.search(help_text)
            if default is not None:
                cvar["default"] = default["value"]
            for bound in BOUNDS.finditer(help_text.split(" - ", 1)[0]):
                cvar[bound["which"]] = float(bound["value"])
            if arguments.descriptions and (text := description(name, help_text)):
                texts["cvars"][name] = text
        if arguments.descriptions:
            for name in commands:
                if text := description(name, answer(sock, f"help {name}")):
                    texts["commands"][name] = text
    json.dump(
        {
            "game": game,
            "cvars": dict(sorted(cvars.items())),
            "commands": dict(sorted(commands.items())),
        },
        sys.stdout,
        indent=1,
    )
    print()
    if arguments.descriptions:
        arguments.descriptions.parent.mkdir(parents=True, exist_ok=True)
        arguments.descriptions.write_text(
            json.dumps(
                {
                    "game": game,
                    "cvars": dict(sorted(texts["cvars"].items())),
                    "commands": dict(sorted(texts["commands"].items())),
                },
                indent=1,
            )
            + "\n"
        )
    print(f"{len(cvars)} cvars, {len(commands)} commands", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
