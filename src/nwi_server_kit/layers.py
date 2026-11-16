"""Versioned layers: the folders the servers are assembled of, as systemd's versioned directories.

A layer NAME is the folder NAME.v, with a version a folder NAME_VERSION in it (systemd.v(7),
systemd-vpick(1)), e.g. depot-1006.v/depot-1006_20260915T182910.4559160656493359681. A version doesn't
change once it's made: it's made under a temporary name and renamed when complete, so it's whole or
absent, and the servers mount the newest one when they start, which an update doesn't touch. So an
update needs no copy of the layers, it adds versions while the servers run. VERSION has no "_": systemd
reads NAME_VERSION_ARCH. The versions of a layer are ordered by their time first, e.g. a manifest's
date, then the rest, e.g. its ID.

Versions are copies of a folder with reflinks where the file system has them (btrfs, XFS), so they
share their data with it and each other and take the space of what differs only. Of a layer, the
newest versions are kept (NWI_KEEP_VERSIONS, 3 by default), and those a server uses, which their
mounts record in /run/nwi-server/in-use (mount.py).
"""

import calendar
import filecmp
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

# Folders of the downloads' and clones' own, which no version has
EXCLUDED = (".DepotDownloader", ".git")
IN_USE = Path("/run/nwi-server/in-use")


def keep_versions() -> int:
    """How many of a layer's newest versions are kept."""
    return max(1, int(os.environ.get("NWI_KEEP_VERSIONS", "3")))


def folder(parent: Path, name: str) -> Path:
    """The folder of the layer NAME in PARENT."""
    return parent / f"{name}.v"


def versions(layer: Path) -> list[Path]:
    """The versions of a layer's folder, oldest first: by their time, then the rest of the version."""
    prefix = layer.name.removesuffix(".v") + "_"
    found = [
        path
        for path in layer.glob(f"{prefix}*")
        if path.is_dir() and not path.name.startswith(".")
    ]

    def key(path: Path) -> tuple[str, str]:
        version = path.name.removeprefix(prefix)
        stamp, _, rest = version.partition(".")
        return stamp, rest

    return sorted(found, key=key)


def latest(layer: Path) -> Path | None:
    """The newest version of a layer's folder, None without one."""
    found = versions(layer)
    return found[-1] if found else None


def newest(layer: Path) -> Path:
    """The newest version of a layer's folder; an error without one, before an update made it."""
    found = latest(layer)
    if found is None:
        raise ValueError(f"{layer} has no version, update first (nwi-update.service)")
    return found


def version_of(path: Path) -> str:
    """The version of a version's folder, NAME_VERSION."""
    return path.name.split("_", 1)[1]


def stamp(seconds: float | None = None) -> str:
    """A time as the first part of a version, e.g. 20260915T182910, in UTC."""
    return time.strftime("%Y%m%dT%H%M%S", time.gmtime(seconds))


def seconds(version: str) -> int:
    """The time of a version, its first part, as seconds since the epoch."""
    return calendar.timegm(time.strptime(version.split(".", 1)[0], "%Y%m%dT%H%M%S"))


def _copy(source: Path, target: Path) -> None:
    """A copy of a folder, with reflinks where the file system has them, without EXCLUDED."""
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["cp", "-a", "--reflink=auto", f"{source}/.", str(target)], check=True
    )
    for name in EXCLUDED:
        shutil.rmtree(target / name, ignore_errors=True)


def _temporary(layer: Path, name: str) -> Path:
    """A temporary folder for a version of the layer, which versions() doesn't take."""
    target = layer / f".{name}.{os.getpid()}.new"
    shutil.rmtree(target, ignore_errors=True)
    return target


def snapshot(
    source: Path,
    layer: Path,
    version: str,
    shape: str = "",
    prepare: Callable[[Path], None] | None = None,
) -> Path:
    """The version VERSION of the layer, a copy of SOURCE, made unless the layer has it already. With
    SHAPE, a relative path, the copy is in that folder of the version, e.g. a workshop item's
    steamapps/workshop/content/<app>/<item>. PREPARE changes the copy before it becomes the version."""
    if "_" in version:
        raise ValueError(f"a version can't have a _: {version}")
    name = layer.name.removesuffix(".v")
    final = layer / f"{name}_{version}"
    if final.is_dir():
        return final
    temporary = _temporary(layer, name)
    _copy(source, temporary / shape if shape else temporary)
    if prepare is not None:
        prepare(temporary)
    temporary.rename(final)
    return final


def same(left: Path, right: Path) -> bool:
    """Whether two folders have the same files, by their names and contents."""
    comparison = filecmp.dircmp(left, right)
    if comparison.left_only or comparison.right_only or comparison.funny_files:
        return False
    _, mismatch, errors = filecmp.cmpfiles(
        left, right, comparison.common_files, shallow=False
    )
    if mismatch or errors:
        return False
    return all(same(left / sub, right / sub) for sub in comparison.common_dirs)


def keep_if_new(built: Path, layer: Path) -> Path:
    """The folder BUILT as a new version of the layer, unless the newest has the same files, which it
    is then instead. BUILT is moved or removed."""
    newest = latest(layer)
    if newest is not None and same(built, newest):
        shutil.rmtree(built)
        return newest
    name = layer.name.removesuffix(".v")
    layer.mkdir(parents=True, exist_ok=True)
    final = layer / f"{name}_{stamp()}"
    while final.exists():
        time.sleep(1)
        final = layer / f"{name}_{stamp()}"
    temporary = _temporary(layer, name)
    shutil.move(built, temporary)
    temporary.rename(final)
    return final


def in_use() -> set[Path]:
    """The versions the mounted servers use, as their records have them."""
    used = set()
    if IN_USE.is_dir():
        for record in IN_USE.iterdir():
            used |= {
                Path(line) for line in record.read_text().splitlines() if line.strip()
            }
    return used


def collect(layer: Path, keep: int, used: set[Path]) -> list[Path]:
    """Remove a layer's versions but the newest KEEP and those in USED, and left-over temporary ones;
    returns those removed."""
    removed = []
    for path in layer.glob(".*.new"):
        shutil.rmtree(path, ignore_errors=True)
    for path in versions(layer)[:-keep] if keep else versions(layer):
        if path.resolve() in used:
            continue
        shutil.rmtree(path)
        removed.append(path)
    return removed


def remove_layer(layer: Path, used: set[Path]) -> bool:
    """Remove a layer no server needs any more, unless a server still uses a version of it; whether
    it's removed."""
    if any(path.resolve() in used for path in versions(layer)):
        return False
    shutil.rmtree(layer)
    return True
