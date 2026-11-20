#!/usr/bin/env python3
# SPDX-FileCopyrightText: Christian Pfeiffer
# SPDX-License-Identifier: MIT

"""Set safe-launch.py as the Steam launch options of Day of Infamy and Insurgency on the Linux
client, so the game runs through it (see README.md). It finds the games Steam has installed, copies
the wrapper to a folder of its own, writes each game's blocklist, and puts the wrapper before
%command% in each game's launch options, keeping anything that's there. Run it with Steam closed, as
Steam rewrites its config when it exits. It changes only the launch options and the blocklist, and
backs up the config it edits first.

NWI_STEAM_ROOT and HOME override where it looks, for testing.
"""

import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# The games, by Steam app ID: the install folder under steamapps/common, and the game's mod folder.
GAMES = {
    "447820": ("dayofinfamy", "doi"),
    "222880": ("insurgency2", "insurgency"),
}
BLOCKLIST_URL = os.environ.get(
    "NWI_BLOCKLIST_URL", "https://content.hl2dm.org/spamfilter/RogueIPs.txt"
)
HERE = Path(__file__).resolve().parent
INSTALL_DIR = (
    Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    / "nwi-safe-launch"
)
IP = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")
KEY = re.compile(r'^(\s*)"([^"]*)"\s*$')
OPEN = re.compile(r"^\s*\{\s*$")
CLOSE = re.compile(r"^(\s*)\}\s*$")
PAIR = re.compile(r'^(\s*)"([^"]*)"(\s+)"(.*)"\s*$')


def steam_root() -> Path | None:
    """The main Steam folder, the one with userdata."""
    override = os.environ.get("NWI_STEAM_ROOT")
    if override:
        return Path(override)
    for path in (
        Path.home() / ".local/share/Steam",
        Path.home() / ".steam/steam",
        Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
    ):
        if (path / "userdata").is_dir():
            return path
    return None


def libraries(root: Path) -> list[Path]:
    """The Steam library folders, from libraryfolders.vdf (the root included)."""
    found = [root]
    vdf = root / "steamapps/libraryfolders.vdf"
    if vdf.is_file():
        found += [
            Path(path) for path in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text())
        ]
    return found


def installed(root: Path) -> dict[str, tuple[Path, str]]:
    """The installed games, app ID to its game folder (…/common/<install>/<mod>) and mod name."""
    games: dict[str, tuple[Path, str]] = {}
    for library in libraries(root):
        for app, (install, mod) in GAMES.items():
            if (library / f"steamapps/appmanifest_{app}.acf").is_file():
                folder = library / "steamapps/common" / install / mod
                if folder.is_dir():
                    games[app] = (folder, mod)
    return games


def steam_running() -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-x", "steam"], check=False, capture_output=True
        )
        return result.returncode == 0
    except OSError:
        return False


def wrapped_value(current: str, insert: str) -> str | None:
    """current with insert ("<wrapper> %command%") put before %command%, or None if it's already
    there. An existing value keeps its prefix (e.g. Proton's) and any trailing options."""
    if insert in current:
        return None
    if "%command%" in current:
        return current.replace("%command%", insert, 1)
    return insert if current == "" else f"{insert} {current}"


def set_launch_options(text: str, app: str, insert: str) -> tuple[str, str | None]:
    """Set app's LaunchOptions so the wrapper runs before %command%, changing only that line. Returns
    one of "changed" (with the new text), "already" (nothing to do) or "absent" (app has no block)."""
    want = ["userlocalconfigstore", "software", "valve", "steam", "apps", app.lower()]
    newline = "\r\n" if "\r\n" in text else "\n"
    stack: list[str] = []
    pending = ""
    out: list[str] = []
    entered = False
    changed = False
    seen = False

    def in_app() -> bool:
        return [key.lower() for key in stack] == want

    for line in text.splitlines():
        pair = PAIR.match(line)
        if pair and in_app() and pair[2].lower() == "launchoptions":
            seen = True
            value = wrapped_value(pair[4], insert)
            if value is not None:
                out.append(f'{pair[1]}"{pair[2]}"{pair[3]}"{value}"')
                changed = True
                continue
        close = CLOSE.match(line)
        if close and in_app() and not seen:
            out.append(f'{close[1]}\t"LaunchOptions"\t\t"{insert}"')
            changed = True
        key = KEY.match(line)
        if key:
            pending = key[2]
        elif OPEN.match(line):
            stack.append(pending)
            if in_app():
                entered = True
        elif close:
            stack.pop()
        out.append(line)
    if changed:
        tail = newline if text.endswith(("\n", "\r")) else ""
        return "changed", newline.join(out) + tail
    return ("already", None) if entered else ("absent", None)


def localconfigs(root: Path, app: str) -> list[Path]:
    """The localconfig.vdf of each account that has the app."""
    found = []
    for config in root.glob("userdata/*/config/localconfig.vdf"):
        if re.search(rf'"{app}"', config.read_text(errors="replace")):
            found.append(config)
    return found


def addresses() -> list[str]:
    with urllib.request.urlopen(BLOCKLIST_URL, timeout=10) as answer:
        text = answer.read().decode("utf-8", "replace")
    extra = INSTALL_DIR / "blocklist-extra.txt"
    if extra.is_file():
        text += "\n" + extra.read_text("utf-8")
    seen = dict.fromkeys(
        match[0]
        for match in (IP.search(line.split("#")[0]) for line in text.splitlines())
        if match
    )
    return sorted(seen, key=lambda ip: tuple(int(part) for part in ip.split(".")))


def write_blocklist(cfg: Path) -> int:
    ips = addresses()
    now = int(time.time())
    blocks = "".join(
        f'    "server"\n    {{\n        "name"    "Spamfilter {ip}"\n'
        f'        "addr"    "{ip}"\n        "date"    "{now}"\n    }}\n'
        for ip in ips
    )
    (cfg / "server_blacklist.txt").write_text(
        f'// Written by nwi safe-launch\n"serverblacklist"\n{{\n{blocks}}}\n', "utf-8"
    )
    return len(ips)


def main() -> int:
    root = steam_root()
    if root is None:
        print("Couldn't find Steam. Is it installed for this user?", file=sys.stderr)
        return 1
    games = installed(root)
    if not games:
        print(
            "Neither Day of Infamy nor Insurgency is installed in Steam.",
            file=sys.stderr,
        )
        return 1
    if steam_running():
        print(
            "Steam is running, and would undo this when it exits. Close Steam fully "
            "(right-click the tray icon, Exit) and run this again.",
            file=sys.stderr,
        )
        return 1

    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    wrapper = INSTALL_DIR / "safe-launch.py"
    shutil.copy2(HERE / "safe-launch.py", wrapper)
    wrapper.chmod(0o755)
    if (HERE / "blocklist-extra.txt").is_file():
        shutil.copy2(HERE / "blocklist-extra.txt", INSTALL_DIR / "blocklist-extra.txt")
    print(f"Installed the wrapper to {wrapper}")

    for app, (folder, mod) in sorted(games.items()):
        name = "Day of Infamy" if mod == "doi" else "Insurgency"
        try:
            count = write_blocklist(folder / "cfg")
            print(f"{name}: wrote {count} servers to its blocklist")
        except (OSError, urllib.error.URLError) as error:
            print(f"{name}: couldn't write the blocklist ({error})", file=sys.stderr)
        insert = f"{wrapper} %command%"
        for config in localconfigs(root, app):
            status, edited = set_launch_options(config.read_text(), app, insert)
            if status == "already":
                print(f"{name}: launch options already set")
            elif status == "absent":
                print(
                    f"{name}: no launch-options entry yet; start the game once from Steam, close it, "
                    "then run this again",
                    file=sys.stderr,
                )
            elif edited is not None:
                backup = config.with_suffix(f".vdf.nwi-backup-{int(time.time())}")
                shutil.copy2(config, backup)
                config.write_text(edited)
                print(f"{name}: set its launch options (backed up to {backup.name})")

    print("\nDone. Start Steam and play as usual.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
