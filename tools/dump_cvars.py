#!/usr/bin/env python3
"""Dump the cvars and commands of a running server, for tools/check_configs.py.

Lists every cvar with its default, its bounds and its flags, and the commands, from the server's
cvarlist and the help of each cvar, over RCON. The descriptions are left out. Bounds and flags are
the server's as they are: those nwi_cvar_unlocker.smx changes are its own, which check_configs.py
takes from the plugin's source instead, so a dump from a server without the plugin is the exact
one (a server's prepare_server.sh disables it with DISABLE_PLUGINS=nwi_cvar_unlocker).

The password comes from RCON_PASSWORD.

Usage: dump_cvars.py [--host HOST] [--port PORT] > tools/cvars.json
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rcon

# A line of cvarlist: the name, the value or "cmd", the flags and the description
LINE = re.compile(r"^(?P<name>\S+)\s+:\s(?P<value>.*?)\s+:\s(?P<flags>.*?)\s+:\s")
# The bounds in a cvar's help
BOUNDS = re.compile(r"\b(?P<which>min|max)\. (?P<value>-?[\d.]+)")
DEFAULT = re.compile(r'\( def\. "(?P<value>[^"]*)" \)')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=27015)
    arguments = parser.parse_args()
    password = os.environ.get("RCON_PASSWORD")
    if not password:
        print("RCON_PASSWORD isn't set", file=sys.stderr)
        return 2
    with rcon.connect(arguments.host, arguments.port, password) as sock:
        if "DOI CVAR unlocker" in rcon.run(sock, "sm plugins list"):
            print(
                "dump_cvars.py: nwi_cvar_unlocker.smx is loaded: the bounds and flags it changes "
                "are its own",
                file=sys.stderr,
            )
        cvars = {}
        commands = []
        for line in rcon.run(sock, "cvarlist").splitlines():
            match = LINE.match(line)
            if match is None:
                continue
            name = match["name"].lower()
            if match["value"].strip() == "cmd":
                commands.append(name)
                continue
            flags = sorted(re.findall(r'"([^"]+)"', match["flags"]))
            cvars[name] = {"flags": flags}
        for name, cvar in cvars.items():
            help_text = rcon.run(sock, f"help {name}")
            default = DEFAULT.search(help_text)
            if default is not None:
                cvar["default"] = default["value"]
            for bound in BOUNDS.finditer(help_text):
                cvar[bound["which"]] = float(bound["value"])
    json.dump(
        {"cvars": dict(sorted(cvars.items())), "commands": sorted(commands)},
        sys.stdout,
        indent=1,
    )
    print()
    print(f"{len(cvars)} cvars, {len(commands)} commands", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
