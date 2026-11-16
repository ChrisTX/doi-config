"""The trial of new versions: blame, fallback and blessing (health.py)."""

from collections.abc import Callable
from pathlib import Path

import pytest

from nwi_server_kit import health, layers

from .conftest import State


class Server:
    """A server with a good and a new depot, a new config, and two new workshop items with a map each."""

    def __init__(self, state: State) -> None:
        self.state = state
        self.old_depot = state.version("depot-1006", "20250101T000000.1", good=True)
        self.depot = state.version("depot-1006", "20260101T000000.2")
        self.config = state.version("config-default", "20260101T000000.abc")
        self.item1 = state.version("item-1", "20260101T000000.1")
        self.item2 = state.version("item-2", "20260101T000000.1")
        state.mounted(
            "server",
            [self.depot, self.config, self.item1, self.item2],
            [self.depot, self.config],
            {"map1": self.item1, "map2": self.item2},
        )

    def counters(self, version: Path) -> tuple[int, int] | None:
        current = layers.current(version)
        assert current is not None
        return layers.counters(current)

    def fail(
        self, invocation: str, result: str = "exit-code", **status: object
    ) -> None:
        self.state.status("server", invocation, **status)
        health.stopped("server", result)


@pytest.fixture
def server(state: State, run: Callable[[str], str]) -> Server:
    run("run1")
    return Server(state)


def test_a_clean_stop_blames_nothing(server: Server) -> None:
    server.fail("run1", "success", map="map1")
    assert server.counters(server.item1) == (3, 0)
    assert server.counters(server.depot) == (3, 0)


def test_a_failure_before_the_server_answered_blames_all_on_trial(
    server: Server,
) -> None:
    server.fail("run1", ready=False)
    for version in (server.depot, server.config, server.item1, server.item2):
        assert server.counters(version) == (2, 1)


def test_a_failure_on_a_stock_map_blames_the_core(server: Server) -> None:
    server.fail("run1", map="bastogne")
    assert server.counters(server.depot) == (2, 1)
    assert server.counters(server.config) == (2, 1)
    assert server.counters(server.item1) == (3, 0)


def test_failures_on_one_map_blame_its_item(
    server: Server, run: Callable[[str], str]
) -> None:
    server.fail("run1", map="map1")
    server.fail(run("run2"), map="map1")
    assert server.counters(server.item1) == (1, 2)
    assert server.counters(server.depot) == (3, 0)


def test_failures_on_two_maps_blame_the_core_and_refund_the_items(
    server: Server, run: Callable[[str], str]
) -> None:
    server.fail("run1", map="map1")
    server.fail(run("run2"), map="map1")
    server.fail(run("run3"), map="map2")
    assert server.counters(server.item1) == (3, 0)
    assert server.counters(server.item2) == (3, 0)
    assert server.counters(server.depot) == (2, 1)
    assert server.counters(server.config) == (2, 1)


def test_a_status_of_an_earlier_run_counts_as_not_answered(
    server: Server, run: Callable[[str], str]
) -> None:
    server.state.status("server", "run1", map="map1")
    run("run2")
    health.stopped("server", "exit-code")
    assert server.counters(server.depot) == (2, 1)
    assert server.counters(server.item1) == (2, 1)


def test_used_up_tries_fall_back_and_notify(
    server: Server, run: Callable[[str], str]
) -> None:
    for invocation in ("run1", "run2", "run3"):
        server.fail(run(invocation), map="bastogne")
    assert server.counters(server.depot) == (0, 3)
    assert layers.pick(server.state.layers / "depot-1006.v") == server.old_depot
    assert server.state.notifications() == [
        "config-default_20260101T000000.abc failed",
        "depot-1006_20260101T000000.2 failed",
    ]


def test_items_are_blessed_by_maps_played_to_their_end(server: Server) -> None:
    server.state.status("server", "run1", map="map2", completed=["map1"])
    health.bless_all()
    assert server.counters(server.item1) is None
    assert server.counters(server.item2) == (3, 0)


def test_the_core_is_blessed_by_busy_minutes_over_runs(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NWI_BLESS_MINUTES", "2")
    server.state.status("server", "run1", busy_seconds=60)
    health.bless_all()
    # The same run again doesn't count twice
    health.bless_all()
    assert server.counters(server.depot) == (3, 0)
    # A new run counts its own seconds on top
    server.state.status("server", "run2", busy_seconds=60)
    health.bless_all()
    assert server.counters(server.depot) is None
    assert server.counters(server.config) is None
    assert server.counters(server.item1) == (3, 0)


def test_retry_and_approve_by_hand(server: Server) -> None:
    used_up = layers.renamed(server.depot, 0, 3)
    assert health.main(["retry", str(used_up)]) == 0
    assert server.counters(server.depot) == (3, 0)
    assert health.main(["approve", str(layers.canonical(used_up))]) == 0
    assert server.counters(server.depot) is None


@pytest.mark.parametrize("version", ["", ".", "/tmp", "../layers"])
def test_commands_take_only_versions_of_layers(server: Server, version: str) -> None:
    with pytest.raises(ValueError, match="not a version of a layer"):
        health.version_folder(version)
    assert health.main(["retry", version]) == 1


def test_status_report(server: Server, capsys: pytest.CaptureFixture[str]) -> None:
    health.status_report()
    out = capsys.readouterr().out
    assert "depot-1006.v/depot-1006_20260101T000000.2: 3 tries left, 0 failed" in out
    assert "20250101" not in out
