"""The game of a config source's servers (games.py)."""

from pathlib import Path

import pytest

from nwi_server_kit import games, server_config


def make_source(root: Path, games_of: list[str], configs: dict[str, str]) -> Path:
    """A config source's configs: game/common, the games' folders and servers/<config>/server.toml."""
    (root / "game/common/cfg").mkdir(parents=True)
    for game in games_of:
        (root / "game" / game / "cfg").mkdir(parents=True)
    for name, text in configs.items():
        (root / "servers" / name).mkdir(parents=True)
        (root / "servers" / name / "server.toml").write_text(
            f'hostname = "{name}"\nstartup_map = "ministry_coop checkpoint"\n' + text
        )
    return root


@pytest.mark.parametrize(
    ("folders", "game"),
    [
        ([], "doi"),
        (["doi"], "doi"),
        (["insurgency"], "insurgency"),
        (["doi", "insurgency"], "doi"),
    ],
)
def test_source_game(tmp_path: Path, folders: list[str], game: str) -> None:
    assert games.source_game(make_source(tmp_path, folders, {})) == game


def test_a_server_takes_its_sources_game(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configs = make_source(
        tmp_path / "configs",
        ["insurgency"],
        {"checkpoint": "", "named": 'game = "doi"\n'},
    )
    monkeypatch.setenv("NWI_CONFIG", str(configs))
    assert games.server("checkpoint", {}).game == "insurgency"
    assert games.server("named", {}).game == "doi"
    # Without a config, its environment file's game, else the source's
    assert games.server("plain", {}).game == "insurgency"
    assert games.server("plain", {"GAME": "doi"}).game == "doi"


def test_server_settings_take_the_installs_game_without_their_own(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "insurgency"
    folder.mkdir()
    (folder / "gameinfo.txt").write_text("")
    toml = folder / "server.toml"
    toml.write_text('hostname = "a"\nstartup_map = "ministry_coop checkpoint"\n')
    assert server_config.server_settings(tmp_path)[0] == folder
    toml.write_text(toml.read_text() + 'game = "doi"\n')
    with pytest.raises(ValueError, match="the server is of doi"):
        server_config.server_settings(tmp_path)
