"""The scan of a game client's workshop items, as the servers scan theirs (scan.py, ClamAV too): the
items a player's Steam installed for Day of Infamy and Insurgency, which the game loads, e.g. cosmetic
mods of an author whose account was taken over.

Steam's libraries are those of its libraryfolders.vdf, and each library's record of an app's items
is steamapps/workshop/appworkshop_<app>.acf, which Steam writes after it installed or updated one: a
version is scanned once, by its manifest, and what was scanned is kept in the state file
(${XDG_STATE_HOME:-~/.local/state}/nwi-server-kit/client-scan.json). The scan warns, it can't block:
Steam installed the item already, so the player unsubscribes before the game loads it. The user
units nwi-client-scan.path and .service run it whenever Steam writes a record (nwi-server workshop
scan-client --notify).

An item a player hasn't subscribed to, e.g. one popular with a server's players, is scanned on demand
(scan_item, nwi-server workshop scan-item): its current version, downloaded with DepotDownloader as
the servers' updates download theirs, into a temporary folder that's removed afterwards.
"""

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from srctools.keyvalues import Keyvalues

from . import clamd, downloads, games, scan

# The client's apps whose workshop items the scan checks
APPS = {447820: "Day of Infamy", 222880: "Insurgency"}


@dataclass
class Result:
    """A scanned version of an item and its findings."""

    app: int
    item: int
    manifest: str
    folder: Path
    findings: list[str] = field(default_factory=list)


def steam_root(environ: dict[str, str] | None = None) -> Path:
    """Steam's folder: STEAM_ROOT, or ~/.local/share/Steam, or ~/.steam/steam."""
    environ = dict(os.environ) if environ is None else environ
    if environ.get("STEAM_ROOT"):
        return Path(environ["STEAM_ROOT"])
    home = Path(environ.get("HOME", Path.home()))
    for candidate in (home / ".local/share/Steam", home / ".steam/steam"):
        if candidate.is_dir():
            return candidate
    return home / ".local/share/Steam"


def state_file(environ: dict[str, str] | None = None) -> Path:
    environ = dict(os.environ) if environ is None else environ
    home = Path(environ.get("HOME", Path.home()))
    state = Path(environ.get("XDG_STATE_HOME") or home / ".local/state")
    return state / "nwi-server-kit/client-scan.json"


def libraries(root: Path) -> list[Path]:
    """Steam's libraries, by its libraryfolders.vdf, its own folder without one."""
    record = root / "steamapps/libraryfolders.vdf"
    found = []
    if record.is_file():
        for folders in Keyvalues.parse(record.read_text(errors="replace")).find_all(
            "libraryfolders"
        ):
            for folder in folders:
                if folder.has_children():
                    path = folder["path", ""]
                    if path:
                        found.append(Path(path))
    return found or [root]


def installed_items(library: Path, app: int) -> dict[int, str]:
    """The items a library has installed of an app, by their manifests (appworkshop_<app>.acf)."""
    record = library / f"steamapps/workshop/appworkshop_{app}.acf"
    if not record.is_file():
        return {}
    items = {}
    for installed in Keyvalues.parse(record.read_text(errors="replace")).find_all(
        "AppWorkshop", "WorkshopItemsInstalled"
    ):
        for item in installed:
            if item.has_children() and item.name.isdigit():
                items[int(item.name)] = item["manifest", ""]
    return items


def scan_client(
    root: Path, state: Path, socket: str | None = scan.CLAMD_SETTING
) -> list[Result]:
    """Scan the versions of the client's items not scanned yet, see the module's documentation; a
    ClamdError if clamd can't be reached, rather than a finding of every item."""
    if socket == scan.CLAMD_SETTING:
        socket = clamd.socket_path()
    if socket is not None:
        clamd.command(socket, "PING")
    scanned: dict[str, str] = {}
    if state.is_file():
        scanned = json.loads(state.read_text()).get("scanned", {})
    results = []
    for library in libraries(root):
        for app in APPS:
            for item, manifest in sorted(installed_items(library, app).items()):
                key = f"{app}/{item}"
                folder = library / f"steamapps/workshop/content/{app}/{item}"
                if scanned.get(key) == manifest or not folder.is_dir():
                    continue
                results.append(
                    Result(
                        app,
                        item,
                        manifest,
                        folder,
                        scan.scan(folder, socket, client=True),
                    )
                )
                scanned[key] = manifest
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"scanned": scanned}, indent=1, sort_keys=True) + "\n")
    return results


def notify(summary: str, body: str) -> None:
    """A desktop notification, if notify-send is there."""
    if shutil.which("notify-send"):
        subprocess.run(
            [
                "notify-send",
                "--urgency=critical",
                "--app-name=nwi-server-kit",
                summary,
                body,
            ],
            check=False,
        )


def item_page(item: int) -> str:
    return f"https://steamcommunity.com/sharedfiles/filedetails/?id={item}"


def scan_item(
    item: int, socket: str | None = scan.CLAMD_SETTING
) -> tuple[str, list[str]]:
    """Download an item's current version and scan it: its title and the findings. A ValueError if
    it isn't an available item of Day of Infamy or Insurgency."""
    details = [
        detail for detail in games.item_details([item]) if detail.get("result") == 1
    ]
    if not details:
        raise ValueError(f"{item} isn't an available workshop item")
    app = int(details[0]["consumer_app_id"])
    if app not in APPS:
        raise ValueError(
            f"{item} is an item of app {app}, not of {' or '.join(APPS.values())}"
        )
    with tempfile.TemporaryDirectory(prefix="nwi-scan-item-") as work:
        # A folder named after the item, which the scan's notes name
        folder = Path(work) / str(item)
        downloads.download_item(app, item, folder)
        return str(details[0].get("title", item)), scan.scan(folder, socket)
