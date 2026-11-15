"""The downloads of the games' depots and the workshop items, with DepotDownloader, anonymously.

DepotDownloader keeps its record of a download in .DepotDownloader of the download's folder, so the
folders are for the downloads only, which update.py makes versions of (layers.py). Downloads fail at
times, so each is tried three times. Its output goes to the log, without its progress.
"""

import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ATTEMPTS = 3
# The lines of DepotDownloader's progress, a line a file
PROGRESS = re.compile(r"^ *[0-9.]+% |^Pre-allocating ")
# A listing's header: "Manifest ID / date     : 1007577009454669389 / 12/25/2025 10:38:28"
MANIFEST_DATE = re.compile(
    r"^Manifest ID / date\s*:\s*\d+\s*/\s*(\d+)/(\d+)/(\d+)\s+(\d+):(\d+):(\d+)",
    re.MULTILINE,
)


@dataclass
class Depot:
    """A depot of an app at its manifest: when it was made, as a version's time, and whether it has
    the game's folder."""

    depot: int
    manifest: str
    made: str
    files: list[str]


def run(arguments: list[str]) -> None:
    """Run DepotDownloader, tried ATTEMPTS times; an error when it fails each time."""
    for attempt in range(1, ATTEMPTS + 1):
        process = subprocess.Popen(
            ["depotdownloader", *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
        assert process.stdout is not None
        for line in process.stdout:
            if not PROGRESS.match(line):
                print(line, end="", file=sys.stderr)
        if process.wait() == 0:
            return
        print(
            f"DepotDownloader failed, attempt {attempt} of {ATTEMPTS}: {' '.join(arguments)}",
            file=sys.stderr,
        )
    raise RuntimeError(f"DepotDownloader failed: {' '.join(arguments)}")


def list_depots(app: int) -> list[Depot]:
    """The public branch's depots of an app for Linux and their manifests, as DepotDownloader lists
    them: manifest_<depot>_<manifest>.txt, with the manifest's date and its files."""
    with tempfile.TemporaryDirectory() as listing:
        run(["-app", str(app), "-os", "linux", "-manifest-only", "-dir", listing])
        depots = []
        for path in sorted(Path(listing).glob("manifest_*_*.txt")):
            depot, manifest = path.stem.removeprefix("manifest_").split("_", 1)
            text = path.read_text(errors="replace")
            date = MANIFEST_DATE.search(text)
            made = (
                f"{date[3]}{date[1]:0>2}{date[2]:0>2}T{date[4]:0>2}{date[5]:0>2}{date[6]:0>2}"
                if date
                else time.strftime("%Y%m%dT%H%M%S", time.gmtime())
            )
            # The files' paths, the lines' last column after the header
            files = [
                line.split(maxsplit=4)[4]
                for line in text.splitlines()
                if re.match(r"^\s*\d+\s+\d+\s+[0-9a-f]{40}\s+\d+\s+\S", line)
            ]
            depots.append(Depot(int(depot), manifest, made, files))
    return depots


def recorded_manifest(download: Path, depot: int) -> str | None:
    """The manifest DepotDownloader last downloaded into a folder, of its record:
    .DepotDownloader/<depot>_<manifest>.manifest."""
    records = sorted(
        download.glob(f".DepotDownloader/{depot}_*.manifest"),
        key=lambda path: path.stat().st_mtime,
    )
    return records[-1].stem.split("_", 1)[1] if records else None


def download_depot(
    app: int, depot: Depot, download: Path, validate: bool = False
) -> None:
    """Download a depot at its manifest into its folder; with VALIDATE, its files are checked, and
    only what differs is downloaded."""
    arguments = ["-app", str(app), "-os", "linux", "-depot", str(depot.depot)]
    arguments += ["-manifest", depot.manifest, "-dir", str(download)]
    run(arguments + (["-validate"] if validate else []))


def download_item(app: int, item: int, download: Path, validate: bool = False) -> None:
    """Download a workshop item of the workshop's app into its folder, its current version."""
    arguments = ["-app", str(app), "-pubfile", str(item), "-dir", str(download)]
    run(arguments + (["-validate"] if validate else []))
