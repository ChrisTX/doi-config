"""The layers of the installs of SourceMod and Metamod:Source (update.py)."""

import os
from pathlib import Path

import pytest

from nwi_server_kit import layers, update

from .conftest import State


@pytest.fixture
def installs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Fake installs, shaped as the game's folder, with SOURCEMOD_DIR and METAMOD_DIR naming them."""
    found = {}
    for name, variable, _ in update.INSTALLS:
        folder = tmp_path / "usr" / name
        (folder / f"addons/{name}/bin").mkdir(parents=True)
        (folder / f"addons/{name}/bin/{name}.so").write_text(f"{name} 1\n")
        monkeypatch.setenv(variable, str(folder))
        found[name] = folder
    monkeypatch.delenv("NWI_TRIES", raising=False)
    (tmp_path / "state").mkdir()
    return found


def test_installs_are_versions_on_trial(
    tmp_path: Path, installs: dict[str, Path]
) -> None:
    state = tmp_path / "state"
    sourcemod, metamod = update.snapshot_installs(state)
    assert sourcemod.parent == state / "sourcemod.v"
    assert layers.counters(sourcemod) == (3, 0)
    assert (
        sourcemod / "addons/sourcemod/bin/sourcemod.so"
    ).read_text() == "sourcemod 1\n"
    assert (metamod / "addons/metamod/bin/metamod.so").is_file()


def test_an_unchanged_install_keeps_its_version(
    tmp_path: Path, installs: dict[str, Path]
) -> None:
    state = tmp_path / "state"
    first = update.snapshot_installs(state)
    assert update.snapshot_installs(state) == first
    assert len(layers.versions(state / "sourcemod.v")) == 1


def test_a_changed_install_is_a_new_version(
    tmp_path: Path, installs: dict[str, Path]
) -> None:
    state = tmp_path / "state"
    old, _ = update.snapshot_installs(state)
    library = installs["sourcemod"] / "addons/sourcemod/bin/sourcemod.so"
    library.write_text("sourcemod 2, a package's update\n")
    # A time after the first, as a package's files have
    os.utime(
        library, ns=(library.stat().st_atime_ns, library.stat().st_mtime_ns + 10**9)
    )
    new, _ = update.snapshot_installs(state)
    assert new != old
    assert layers.versions(state / "sourcemod.v") == [old, new]
    assert layers.pick(state / "sourcemod.v") == new
    assert (old / "addons/sourcemod/bin/sourcemod.so").read_text() == "sourcemod 1\n"


def test_install_version(tmp_path: Path, installs: dict[str, Path]) -> None:
    version = update.install_version(installs["metamod"])
    stamp, fingerprint = version.split(".")
    assert len(fingerprint) == 12
    assert layers.seconds(version) == int(
        (installs["metamod"] / "addons/metamod/bin/metamod.so").stat().st_mtime
    )
    assert "_" not in version and "+" not in version
    assert stamp == layers.stamp(
        (installs["metamod"] / "addons/metamod/bin/metamod.so").stat().st_mtime
    )


def test_an_update_of_some_configs_keeps_the_others_layers(state: State) -> None:
    """With NWI_SERVER_CONFIGS, e.g. the test instance's update of one config, a layer that its
    servers don't need may be another server's: it stays. A full update removes it."""
    version = state.version("item-5", "20260101T000000.1", good=True)
    update.collect_all(state.layers, set(), unneeded=False)
    assert version.is_dir()
    update.collect_all(state.layers, set())
    assert not version.parent.exists()
