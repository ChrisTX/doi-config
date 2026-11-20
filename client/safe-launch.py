#!/usr/bin/env python3
# SPDX-FileCopyrightText: Christian Pfeiffer
# SPDX-License-Identifier: MIT

"""Start Day of Infamy or Insurgency safely, for the Linux client (install.py sets it as the game's
Steam launch options, before %command%). It drops the console commands a malicious Steam invite can
smuggle onto the command line (see README.md): +rcon and its kin point the client's RCON client at an
attacker's server, +host_writeconfig writes to the client's config, and +alias can stand in for them.
Everything else is kept, +connect included, so invites to a real server and the launch options work.

It also refreshes the game's cfg/server_blacklist.txt from a maintained list of spammy servers
(NWI_BLOCKLIST_URL) and the addresses in blocklist-extra.txt next to this script, one per line. That
is best effort: without the network the file is left as it is, and the game always starts.

NWI_SAFE_LAUNCH_LOG names a file to append the dropped commands to.
"""

import os
import re
import sys
import time
import urllib.request
from pathlib import Path

# The +commands a client never needs, which an invite abuses.
DENIED = {
    "rcon",
    "rcon_address",
    "rcon_password",
    "rcon_port",
    "host_writeconfig",
    "host_writeconfig_ss",
    "alias",
}
BLOCKLIST_URL = os.environ.get(
    "NWI_BLOCKLIST_URL", "https://content.hl2dm.org/spamfilter/RogueIPs.txt"
)
IP = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")


def filter_command(argv: list[str]) -> tuple[list[str], list[str]]:
    """The command with the denied +commands and their arguments removed, and what was removed. A
    denied +command's arguments are the tokens up to the next +command or -option."""
    keep: list[str] = []
    dropped: list[str] = []
    dropping = False
    for token in argv:
        if token.startswith("+"):
            dropping = token[1:].lower() in DENIED
            (dropped if dropping else keep).append(token)
        elif token.startswith("-"):
            dropping = False
            keep.append(token)
        else:
            (dropped if dropping else keep).append(token)
    return keep, dropped


def game_cfg(keep: list[str]) -> Path | None:
    """The game's cfg folder, from the game's binary (the first kept token) and -game <mod>."""
    mod = next(
        (keep[i + 1] for i, token in enumerate(keep[:-1]) if token == "-game"), None
    )
    if not mod:
        return None
    cfg = Path(keep[0]).resolve().parent / mod / "cfg"
    return cfg if cfg.is_dir() else None


def addresses() -> list[str]:
    """The blocklist's addresses: the maintained list and blocklist-extra.txt, deduplicated."""
    with urllib.request.urlopen(BLOCKLIST_URL, timeout=6) as answer:
        text = answer.read().decode("utf-8", "replace")
    extra = Path(__file__).resolve().parent / "blocklist-extra.txt"
    if extra.is_file():
        text += "\n" + extra.read_text("utf-8")
    found = [IP.search(line.split("#")[0].split("//")[0]) for line in text.splitlines()]
    seen = dict.fromkeys(match[0] for match in found if match)
    return sorted(seen, key=lambda ip: tuple(int(part) for part in ip.split(".")))


def write_blocklist(keep: list[str]) -> None:
    """Write the game's server blocklist, best effort: any failure leaves it as it is."""
    try:
        cfg = game_cfg(keep)
        if cfg is None:
            return
        ips = addresses()
        if not ips:
            return
        now = int(time.time())
        blocks = "".join(
            f'    "server"\n    {{\n        "name"    "Spamfilter {ip}"\n'
            f'        "addr"    "{ip}"\n        "date"    "{now}"\n    }}\n'
            for ip in ips
        )
        header = (
            f"// Written by safe-launch from {BLOCKLIST_URL} and blocklist-extra.txt\n"
        )
        (cfg / "server_blacklist.txt").write_text(
            f'{header}"serverblacklist"\n{{\n{blocks}}}\n', "utf-8"
        )
    except Exception:  # noqa: BLE001 - the blocklist must never stop the game from starting
        return


def main() -> None:
    keep, dropped = filter_command(sys.argv[1:])
    if not keep:
        return
    if dropped:
        message = "safe-launch dropped: " + " ".join(dropped)
        print(message, file=sys.stderr)
        log = os.environ.get("NWI_SAFE_LAUNCH_LOG")
        if log:
            with open(log, "a", encoding="utf-8") as file:
                file.write(
                    f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {message}\n"
                )
    write_blocklist(keep)
    os.execvp(keep[0], keep)


if __name__ == "__main__":
    main()
