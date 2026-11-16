"""The approval of workshop items' versions, the gate the update lets them through (update.py), and
the servers' lists of the items whose version they run (mount.py).

A config source approves versions in workshop/approved.toml, by their manifests, and may name keys
(workshop/keys/<name>.pem) an item's versions may be signed with:

    [items.3431236539]
    manifests = ["7284409961546829163"]
    keys = ["community"]

A version is approved for a source if its manifest is approved, or if the item has keys and the version
is VPKs only, each signed with one of them (vpk.py); those the update records in its state
(workshop.json), and the admins hear of them. Any other new version is held: the update doesn't make a
layer of it, the servers keep the version they have, and the admins hear of it once, until it's
approved. A source without workshop/approved.toml approves every version (`nwi-server workshop freeze`
makes one of the current versions).

Clients always download an item's newest version of the Workshop. So a server lists only the items
whose version it runs is the Workshop's (its workshop list, subscribed_file_ids.txt), whether another
version is held or its own fell back after failures (layers.py), and its mapcycle leaves out the maps
of the others, which clients would lack; a startup map of theirs becomes the mapcycle's first.

Players subscribed to a Workshop collection get its items' newest versions too. So a source's
collections that mirror its lists (workshop/collections.toml) are made, at every update, the items of
their lists that aren't held, signed in with the credential nwi-server.steam-refresh-token of an
account that may change them, e.g. a contributor of the collections (steam_web.py; nwi-server workshop
login).
"""

import json
import os
import re
import shutil
import sys
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import games, layers, notify, server_config, steam_web, vpk

APPROVED = Path("workshop/approved.toml")
KEYS = Path("workshop/keys")
COLLECTIONS = Path("workshop/collections.toml")
TOKEN_CREDENTIAL = "nwi-server.steam-refresh-token"
# How long before the sign-in expires the admins hear of it
EXPIRY_WARNING = 30 * 24 * 3600


@dataclass
class Approvals:
    """A config source's approvals: per item, its approved manifests and the keys (DER) its versions
    may be signed with; None of a source that doesn't gate (no approved.toml)."""

    manifests: dict[int, set[str]] = field(default_factory=dict)
    keys: dict[int, list[bytes]] = field(default_factory=dict)


def load(configs: Path) -> Approvals | None:
    """The approvals of a config source's configs."""
    path = configs / APPROVED
    if not path.is_file():
        return None
    with path.open("rb") as file:
        settings = tomllib.load(file)
    approvals = Approvals()
    for item, entry in settings.get("items", {}).items():
        approvals.manifests[int(item)] = {
            str(manifest) for manifest in entry.get("manifests", [])
        }
        keys = []
        for name in entry.get("keys", []):
            key_path = configs / KEYS / f"{name}.pem"
            if not key_path.is_file():
                raise ValueError(f"{path}: item {item}'s key {name} isn't in {KEYS}")
            keys.append(vpk.public_der(key_path.read_bytes()))
        approvals.keys[int(item)] = keys
    return approvals


def signed_by(folder: Path, keys: list[bytes]) -> str | None:
    """Whether a version is VPKs only, each signed with one of the keys: None if so, else why not."""
    if not keys:
        return "no keys for it"
    # Loose files, e.g. a map's .bsp, aren't signed. An archive without its directory counts as a VPK of
    # its own, which isn't signed either.
    loose = [
        path for path in folder.rglob("*") if path.is_file() and path.suffix != ".vpk"
    ]
    if loose:
        return f"not VPKs only, e.g. {loose[0].relative_to(folder)}"
    directories = vpk.files_of(folder)
    if not directories:
        return "no VPKs"
    for directory in directories:
        try:
            key = vpk.verify(directory)
        except vpk.VPKError as error:
            return str(error)
        if key not in keys:
            return f"{directory.name} is signed by another key ({vpk.key_name(key)})"
    return None


class State:
    """The update's record of versions approved by signature, per source and item, of the held
    versions the admins heard of, and of the collections' failures and the sign-in's expiry they heard
    of: STATE/workshop.json."""

    def __init__(self, state: Path) -> None:
        self.path = state / "workshop.json"
        data = json.loads(self.path.read_text()) if self.path.is_file() else {}
        self.signed: dict[str, dict[str, list[str]]] = data.get("signed", {})
        self.held: dict[str, dict[str, str]] = data.get("held", {})
        self.failed: dict[str, str] = data.get("failed", {})
        self.warned: float = data.get("warned", 0)

    def save(self) -> None:
        data = {
            "signed": self.signed,
            "held": self.held,
            "failed": self.failed,
            "warned": self.warned,
        }
        temporary = self.path.with_name(f".{self.path.name}.new")
        temporary.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
        temporary.rename(self.path)

    def approved(
        self, source: str, item: int, manifest: str, approvals: Approvals | None
    ) -> bool:
        """Whether a version is approved for a source: by its approvals or by a signature before."""
        if approvals is None:
            return True
        return manifest in approvals.manifests.get(
            item, set()
        ) or manifest in self.signed.get(source, {}).get(str(item), [])


def gate(
    state: Path,
    item: int,
    manifest: str,
    download: Path,
    sources: dict[str, Approvals | None],
) -> bool:
    """Whether a new version of an item may become a layer: approved for one of the sources whose
    servers list it. Records approvals by signature and held versions, and notifies the admins."""
    record = State(state)
    allowed = False
    for source, approvals in sorted(sources.items()):
        if record.approved(source, item, manifest, approvals):
            allowed = True
            record.held.get(source, {}).pop(str(item), None)
            continue
        assert approvals is not None
        reason = signed_by(download, approvals.keys.get(item, []))
        if reason is None:
            allowed = True
            record.signed.setdefault(source, {}).setdefault(str(item), []).append(
                manifest
            )
            record.held.get(source, {}).pop(str(item), None)
            notify.queue(
                f"Workshop item {item} updated, signed",
                f"Version {manifest} of workshop item {item} is signed with a key {source} "
                "trusts for it and was approved. The servers get it when they restart.",
            )
            continue
        if record.held.get(source, {}).get(str(item)) != manifest:
            notify.queue(
                f"Workshop item {item} held",
                f"Version {manifest} of workshop item {item} isn't approved for {source}: {reason}.\n\n"
                "The servers keep the version they have and leave the item off their workshop lists, "
                "and its maps out of their mapcycles, so players don't download the new one. Review "
                f"it, then approve it in workshop/approved.toml of {source}'s configs, e.g. with: "
                f"nwi-server workshop approve {item} {manifest}",
            )
        record.held.setdefault(source, {})[str(item)] = manifest
        print(
            f"Held workshop item {item} at {manifest} for {source}: {reason}",
            file=sys.stderr,
        )
    record.save()
    return allowed


def collections(configs: Path) -> dict[int, str]:
    """A config source's collections and the workshop lists they mirror (game/cfg/<list>), of
    workshop/collections.toml:

        [collections.3450000000]
        list = "doi-config/workshop-ids-pvp.txt"
    """
    path = configs / COLLECTIONS
    if not path.is_file():
        return {}
    with path.open("rb") as file:
        settings = tomllib.load(file)
    return {
        int(collection): str(entry["list"])
        for collection, entry in settings.get("collections", {}).items()
    }


def list_items(path: Path) -> list[int]:
    """The items of a workshop list, in its order."""
    return [
        int(match[1])
        for line in path.read_text().splitlines()
        if (match := re.match(r"\s*(\d+)", line))
    ]


def refresh_token() -> str | None:
    """The sign-in for the collections: the credential nwi-server.steam-refresh-token (systemd's
    CREDENTIALS_DIRECTORY), or the file NWI_STEAM_TOKEN; None without."""
    candidates = []
    if os.environ.get("NWI_STEAM_TOKEN"):
        candidates.append(Path(os.environ["NWI_STEAM_TOKEN"]))
    if os.environ.get("CREDENTIALS_DIRECTORY"):
        candidates.append(Path(os.environ["CREDENTIALS_DIRECTORY"]) / TOKEN_CREDENTIAL)
    for path in candidates:
        if path.is_file():
            return path.read_text().strip()
    return None


def sync_collections(
    state: Path, sources: list[str], configs_of: Callable[[str], Path]
) -> None:
    """Make the sources' collections the items of their lists that aren't held, in their order: the
    players subscribed to a collection mustn't get a held version (see the module's documentation). A
    change that fails, or a sign-in about to expire, the admins hear of once."""
    wanted = {source: collections(configs_of(source)) for source in sources}
    if not any(wanted.values()):
        return
    token = refresh_token()
    record = State(state)
    if token is None:
        print(
            f"No sign-in for the collections ({TOKEN_CREDENTIAL}), they aren't changed",
            file=sys.stderr,
        )
        return
    expiry = steam_web.expires(token)
    if expiry - time.time() < EXPIRY_WARNING and record.warned != expiry:
        notify.queue(
            "The Workshop sign-in expires soon",
            f"The sign-in the servers change the Workshop's collections with expires on "
            f"{time.strftime('%Y-%m-%d', time.gmtime(expiry))}. Sign in again with nwi-server "
            f"workshop login and replace the credential {TOKEN_CREDENTIAL}.",
        )
        record.warned = expiry
    community: steam_web.Community | None = None
    for source, mirrored in sorted(wanted.items()):
        held = set(record.held.get(source, {}))
        for collection, list_name in sorted(mirrored.items()):
            key = f"{source}:{collection}"
            try:
                items = [
                    item
                    for item in list_items(configs_of(source) / "game/cfg" / list_name)
                    if str(item) not in held
                ]
                current = steam_web.collection_items(collection)
                changes = [("add", item) for item in items if item not in current]
                changes += [("remove", item) for item in current if item not in items]
                if changes and community is None:
                    community = steam_web.Community(token)
                for action, item in changes:
                    assert community is not None
                    getattr(community, action)(collection, item)
                    print(f"Collection {collection}: {action} {item}", file=sys.stderr)
                record.failed.pop(key, None)
            except (steam_web.SteamError, OSError, ValueError) as error:
                print(f"Collection {collection} of {source}: {error}", file=sys.stderr)
                if record.failed.get(key) != str(error):
                    notify.queue(
                        f"Workshop collection {collection} not changed",
                        f"The collection {collection} of {source} couldn't be made the items of "
                        f"{list_name} that aren't held: {error}.\n\nChange it by hand so that "
                        "players don't download a held version.",
                    )
                record.failed[key] = str(error)
    record.save()


def manifest_of(version: Path) -> str:
    """The manifest of an item's version, <time>.<manifest>."""
    return layers.version_of(version).split(".", 1)[1]


def allowed_versions(
    state: Path, source: str, item: int, approvals: Approvals | None
) -> Callable[[Path], bool]:
    """Which of an item's versions a server of the source may mount."""
    record = State(state)
    return lambda version: record.approved(
        source, item, manifest_of(version), approvals
    )


def filter_list(text: str, dropped: set[int]) -> str:
    """A workshop list without the dropped items' lines."""
    return "".join(
        line
        for line in text.splitlines(keepends=True)
        if not ((match := re.match(r"\s*(\d+)", line)) and int(match[1]) in dropped)
    )


def filter_mapcycle(text: str, maps: set[str]) -> str:
    """A mapcycle without the maps' lines (<map> <mode>)."""
    return "".join(
        line
        for line in text.splitlines(keepends=True)
        if not line.split() or line.split()[0] not in maps
    )


# The approvals' file and uploads, for nwi-server workshop (cli/workshop.py)

HEADER = """\
# The approved versions of the workshop items of the servers' lists, by their manifests, and the keys
# (workshop/keys/<name>.pem) an item's versions may be signed with, which approves them too. Any other
# new version is held: the servers keep theirs (see nwi_server_kit/workshop.py).
"""


def listed_items(configs: Path) -> list[int]:
    """The items of the workshop lists the configs' servers name."""
    items: set[int] = set()
    for toml in sorted(configs.glob("servers/*/server.toml")):
        settings = server_config.load(toml)
        if "workshop" in settings:
            text = (configs / "game/cfg" / settings["workshop"]).read_text()
            items |= {
                int(line.split()[0])
                for line in text.splitlines()
                if line.split() and line.split()[0].isdigit()
            }
    return sorted(items)


def current_manifests(items: list[int]) -> dict[int, str]:
    """The Workshop's current manifests of the items that are available."""
    return {
        int(detail["publishedfileid"]): str(detail["hcontent_file"])
        for detail in games.item_details(items)
        if detail.get("result") == 1 and detail.get("hcontent_file")
    }


def read_approved(configs: Path) -> dict[int, dict[str, list[str]]]:
    path = configs / APPROVED
    if not path.is_file():
        return {}
    with path.open("rb") as file:
        settings = tomllib.load(file)
    return {
        int(item): {
            "manifests": [str(manifest) for manifest in entry.get("manifests", [])],
            "keys": [str(key) for key in entry.get("keys", [])],
        }
        for item, entry in settings.get("items", {}).items()
    }


def write_approved(configs: Path, approved: dict[int, dict[str, list[str]]]) -> None:
    lines = [HEADER]
    for item, entry in sorted(approved.items()):
        lines.append(f"[items.{item}]")
        lines.append(
            "manifests = [" + ", ".join(f'"{m}"' for m in entry["manifests"]) + "]"
        )
        if entry["keys"]:
            lines.append("keys = [" + ", ".join(f'"{k}"' for k in entry["keys"]) + "]")
        lines.append("")
    path = configs / APPROVED
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip("\n") + "\n")


def approve(
    approved: dict[int, dict[str, list[str]]], item: int, manifest: str
) -> bool:
    """Approve a manifest of an item; whether it's new."""
    entry = approved.setdefault(item, {"manifests": [], "keys": []})
    if manifest in entry["manifests"]:
        return False
    entry["manifests"].append(manifest)
    return True


def stage(paths: list[Path], folder: Path) -> Path:
    """The content of an upload: a folder as it is, or VPKs, with their archives, copied into FOLDER."""
    if len(paths) == 1 and paths[0].is_dir():
        return paths[0]
    for path in paths:
        if path.is_dir() or path.suffix != ".vpk":
            raise ValueError(f"{path}: upload VPKs, or one folder")
        files = [path]
        if path.name.endswith("_dir.vpk"):
            stem = path.name.removesuffix("_dir.vpk")
            files += sorted(path.parent.glob(f"{stem}_[0-9][0-9][0-9].vpk"))
        for file in files:
            if (folder / file.name).exists():
                raise ValueError(f"{file.name}: given twice")
            shutil.copy2(file, folder / file.name)
    return folder
