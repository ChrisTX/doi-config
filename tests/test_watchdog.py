"""What the watchdog records of a server's health (watchdog.py)."""

import json
from pathlib import Path

import pytest

from nwi_server_kit import watchdog


@pytest.fixture
def health(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> watchdog.Health:
    monkeypatch.setenv("INVOCATION_ID", "run1")
    monkeypatch.delenv("NWI_BLESS_PLAYERS", raising=False)
    return watchdog.Health(str(tmp_path))


def written(health: watchdog.Health) -> dict:
    with open(health.path) as file:
        return json.load(file)


def test_maps_played_busy_to_their_end_are_completed(
    health: watchdog.Health,
) -> None:
    # (map, human players): a busy at some point, b and c empty, d busy, e the current one
    for map_name, humans in [
        ("a", 0),
        ("a", 5),
        ("a", 1),
        ("b", 0),
        ("c", 0),
        ("d", 6),
        ("e", 9),
    ]:
        health.answered(map_name, humans, 10)
    status = written(health)
    assert status["completed"] == ["a", "d"]
    assert status["map"] == "e"
    assert status["ready"] is True
    assert status["invocation"] == "run1"
    assert status["busy_seconds"] == 30


def test_busy_players_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NWI_BLESS_PLAYERS", "2")
    health = watchdog.Health(str(tmp_path))
    health.answered("a", 2, 10)
    health.answered("a", 1, 10)
    assert written(health)["busy_seconds"] == 10
