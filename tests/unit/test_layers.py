"""The versions of the layers and their tries counters (layers.py)."""

from pathlib import Path

import pytest

from nwi_server_kit import layers

from .conftest import State


@pytest.mark.parametrize(
    ("name", "counters", "canonical"),
    [
        ("depot-1006_20260101T000000.1", None, "depot-1006_20260101T000000.1"),
        ("depot-1006_20260101T000000.1+3", (3, 0), "depot-1006_20260101T000000.1"),
        ("depot-1006_20260101T000000.1+2-1", (2, 1), "depot-1006_20260101T000000.1"),
        ("depot-1006_20260101T000000.1+0-3", (0, 3), "depot-1006_20260101T000000.1"),
    ],
)
def test_counters(name: str, counters: tuple[int, int] | None, canonical: str) -> None:
    path = Path("/state/depot-1006.v") / name
    assert layers.counters(path) == counters
    assert layers.canonical(path).name == canonical
    assert layers.version_of(path) == "20260101T000000.1"


def test_snapshot_is_on_trial_and_made_once(state: State) -> None:
    first = state.version("config-default", "20260101T000000.abc")
    assert first.name == "config-default_20260101T000000.abc+3"
    assert (first / "file").read_text() == "content\n"
    (state.source / "file").write_text("changed\n")
    # The same version again is the one there is, whatever its counters
    again = state.version("config-default", "20260101T000000.abc")
    assert again == first
    assert (again / "file").read_text() == "content\n"


def test_snapshot_tries_from_the_environment(
    state: State, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NWI_TRIES", "5")
    assert state.version("plugins-default", "20260101T000000.1").name.endswith("+5")


@pytest.mark.parametrize("version", ["20260101T000000_1", "20260101T000000.1+3"])
def test_snapshot_refuses_separators(state: State, version: str) -> None:
    with pytest.raises(ValueError, match="can't have"):
        state.version("depot-1006", version)


def test_versions_are_ordered_by_time_then_the_rest(state: State) -> None:
    for version in ("20260102T000000.1", "20260101T000000.9", "20260101T000000.10"):
        state.version("depot-1006", version)
    names = [
        layers.version_of(path)
        for path in layers.versions(state.layers / "depot-1006.v")
    ]
    assert names == ["20260101T000000.10", "20260101T000000.9", "20260102T000000.1"]


def test_pick_passes_over_versions_without_tries(state: State) -> None:
    layer = state.layers / "depot-1006.v"
    good = state.version("depot-1006", "20260101T000000.1", good=True)
    trial = state.version("depot-1006", "20260102T000000.2")
    assert layers.pick(layer) == trial
    used_up = layers.renamed(trial, 0, 3)
    assert layers.pick(layer) == good
    assert layers.latest(layer) == used_up


def test_pick_takes_the_newest_if_all_used_up_their_tries(
    state: State, capsys: pytest.CaptureFixture[str]
) -> None:
    layer = state.layers / "depot-1006.v"
    used_up = layers.renamed(state.version("depot-1006", "20260101T000000.1"), 0, 3)
    assert layers.pick(layer) == used_up
    assert "used up its tries" in capsys.readouterr().err


def test_picked_without_versions(state: State) -> None:
    assert layers.pick(state.layers / "depot-1006.v") is None
    with pytest.raises(ValueError, match="update first"):
        layers.picked(state.layers / "depot-1006.v")


def test_current_follows_renames(state: State) -> None:
    trial = state.version("depot-1006", "20260101T000000.1")
    canonical = layers.canonical(trial)
    assert layers.current(canonical) == trial
    blessed = layers.renamed(trial, None)
    assert blessed == canonical
    assert layers.current(canonical) == canonical
    assert layers.current(canonical.with_name("depot-1006_20990101T000000.1")) is None


def test_keep_if_new(state: State, tmp_path: Path) -> None:
    layer = state.layers / "mods-default.v"

    def built(content: str) -> Path:
        folder = tmp_path / f"built-{content}"
        folder.mkdir()
        (folder / "mod.cfg").write_text(content)
        return folder

    first = layers.keep_if_new(built("a"), layer)
    assert layers.counters(first) == (3, 0)
    # The same files are the newest version, not another
    assert layers.keep_if_new(built("a"), layer) == first
    assert not (tmp_path / "built-a").exists()


def test_collect_keeps_the_newest_good_and_those_in_use(state: State) -> None:
    layer = state.layers / "depot-1006.v"
    oldest = state.version("depot-1006", "20260101T000000.1", good=True)
    good = state.version("depot-1006", "20260102T000000.2", good=True)
    used = state.version("depot-1006", "20260103T000000.3")
    state.version("depot-1006", "20260104T000000.4")
    newest = state.version("depot-1006", "20260105T000000.5")
    removed = layers.collect(layer, 1, {layers.canonical(used)})
    assert removed == [oldest, layer / "depot-1006_20260104T000000.4+3"]
    assert layers.versions(layer) == [good, used, newest]


def test_in_use_reads_the_records(state: State) -> None:
    version = state.version("depot-1006", "20260101T000000.1")
    state.mounted("server", [version], [version], {})
    assert layers.in_use() == {layers.canonical(version)}
