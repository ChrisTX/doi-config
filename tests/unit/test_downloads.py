"""The downloads with DepotDownloader (downloads.py), with a stand-in of it on PATH: its arguments, its
retries, its listings of depots and its record of a download."""

import os
import shlex
import sys
import time
from pathlib import Path

import pytest

from nwi_server_kit import downloads

# A listing of DepotDownloader (-manifest-only), manifest_<depot>_<manifest>.txt
LISTING = """\
Content Manifest for Depot 462311

Manifest ID / date     : 1007577009454669389 / 12/5/2025 09:38:28
Total number of files  : 2
Total number of chunks : 3
Total bytes on disk    : 3072
Total bytes compressed : 1024


          Size Chunks File SHA                                 Flags Name
          2048      2 0123456789abcdef0123456789abcdef01234567     0 doi/gameinfo.txt
          1024      1 89abcdef0123456789abcdef0123456789abcdef     0 doi/maps/a map with spaces.bsp
"""

FAKE = """\
#!{python}
# The stand-in of DepotDownloader: logs its arguments, prints progress, fails FAKE_FAILURES times
# (counted in FAKE_COUNT), and copies the listings of FAKE_LISTINGS into -dir with -manifest-only.
import os, shutil, sys
from pathlib import Path

arguments = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(" ".join(arguments) + "\\n")
print("Connecting to Steam3...")
print(" 42.00% doi/maps/bastogne.bsp")
print("Pre-allocating doi/maps/bastogne.bsp")
count = Path(os.environ["FAKE_COUNT"])
failures = int(count.read_text()) if count.exists() else 0
if failures < int(os.environ.get("FAKE_FAILURES", "0")):
    count.write_text(str(failures + 1))
    print("Error: connection lost")
    sys.exit(1)
if "-manifest-only" in arguments:
    folder = Path(arguments[arguments.index("-dir") + 1])
    for listing in Path(os.environ["FAKE_LISTINGS"]).iterdir():
        shutil.copy(listing, folder)
"""


@pytest.fixture
def depotdownloader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The stand-in on PATH; its log of arguments, a line a run."""
    folder = tmp_path / "bin"
    folder.mkdir()
    fake = folder / "depotdownloader"
    fake.write_text(FAKE.format(python=sys.executable))
    fake.chmod(0o755)
    listings = tmp_path / "listings"
    listings.mkdir()
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "log"))
    monkeypatch.setenv("FAKE_COUNT", str(tmp_path / "count"))
    monkeypatch.setenv("FAKE_LISTINGS", str(listings))
    return tmp_path / "log"


def runs(log: Path) -> list[list[str]]:
    return [shlex.split(line) for line in log.read_text().splitlines()]


def test_retries(
    depotdownloader: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A failed download is tried again, up to ATTEMPTS times; the progress isn't logged."""
    monkeypatch.setenv("FAKE_FAILURES", "2")
    downloads.download_item(462310, 1234, Path("/srv/item"), validate=True)
    assert (
        runs(depotdownloader)
        == [["-app", "462310", "-pubfile", "1234", "-dir", "/srv/item", "-validate"]]
        * 3
    )
    output = capsys.readouterr().err
    assert "attempt 2 of 3" in output and "Connecting to Steam3" in output
    assert "42.00%" not in output and "Pre-allocating" not in output


def test_fails(depotdownloader: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_FAILURES", "3")
    depot = downloads.Depot(462311, "123", "20251205T093828", [])
    with pytest.raises(RuntimeError, match="DepotDownloader failed: -app 462310"):
        downloads.download_depot(462310, depot, Path("/srv/depot"))
    assert runs(depotdownloader)[0] == [
        *("-app", "462310", "-os", "linux", "-depot", "462311"),
        *("-manifest", "123", "-dir", "/srv/depot"),
    ]


def test_list_depots(depotdownloader: Path) -> None:
    """The depots of the listings: the manifest's date as a version's time, the files' paths."""
    listings = depotdownloader.parent / "listings"
    (listings / "manifest_462311_1007577009454669389.txt").write_text(LISTING)
    undated = LISTING.replace("Manifest ID / date", "Manifest")
    (listings / "manifest_1006_55.txt").write_text(undated)
    found = downloads.list_depots(462310)
    assert found[1] == downloads.Depot(
        462311,
        "1007577009454669389",
        "20251205T093828",
        ["doi/gameinfo.txt", "doi/maps/a map with spaces.bsp"],
    )
    # Without a date, the listing's time
    assert found[0].depot == 1006 and found[0].made.startswith(time.strftime("%Y"))
    assert runs(depotdownloader)[0][:5] == [
        "-app",
        "462310",
        "-os",
        "linux",
        "-manifest-only",
    ]


def test_recorded_manifest(tmp_path: Path) -> None:
    """The manifest of the newest record of the depot."""
    record = tmp_path / ".DepotDownloader"
    record.mkdir()
    assert downloads.recorded_manifest(tmp_path, 462311) is None
    for manifest, mtime in (("old", 1000), ("new", 2000)):
        path = record / f"462311_{manifest}.manifest"
        path.touch()
        os.utime(path, (mtime, mtime))
    (record / "1006_other.manifest").touch()
    assert downloads.recorded_manifest(tmp_path, 462311) == "new"
