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
"""

import json
import re
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import layers, notify, vpk

APPROVED = Path("workshop/approved.toml")
KEYS = Path("workshop/keys")


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
    """The update's record of versions approved by signature, per source and item, and of the held
    versions the admins heard of: STATE/workshop.json."""

    def __init__(self, state: Path) -> None:
        self.path = state / "workshop.json"
        data = json.loads(self.path.read_text()) if self.path.is_file() else {}
        self.signed: dict[str, dict[str, list[str]]] = data.get("signed", {})
        self.held: dict[str, dict[str, str]] = data.get("held", {})

    def save(self) -> None:
        temporary = self.path.with_name(f".{self.path.name}.new")
        temporary.write_text(
            json.dumps(
                {"signed": self.signed, "held": self.held}, indent=1, sort_keys=True
            )
            + "\n"
        )
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
