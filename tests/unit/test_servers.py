"""The game of a config source's servers, and setting up a server (games.py, servers.py)."""

import os
import subprocess
from pathlib import Path

import pytest

from nwi_server_kit import games, server_config, servers


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


def test_free_ports() -> None:
    assert servers.free_ports(set()) == {
        "SERVER_PORT": 27015,
        "TV_PORT": 27020,
        "CLIENT_PORT": 27005,
    }
    # A port of another server's is taken, whichever it is for that one
    assert servers.free_ports({27015, 27016, 27020, 27005, 27017}) == {
        "SERVER_PORT": 27018,
        "TV_PORT": 27021,
        "CLIENT_PORT": 27006,
    }


def test_used_ports_count_the_launchers_defaults(tmp_path: Path) -> None:
    (tmp_path / "a.env").write_text("SERVER_PORT=27016\n")
    (tmp_path / "b.env").write_text(
        "SERVER_PORT=27030\nTV_PORT=27031\nCLIENT_PORT=27032\n"
    )
    assert servers.used_ports(tmp_path) == {27016, 27020, 27005, 27030, 27031, 27032}
    assert servers.used_ports(tmp_path / "missing") == set()


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return make_source(
        tmp_path / "configs",
        ["doi", "insurgency"],
        {"coop": "", "checkpoint": 'game = "insurgency"\n'},
    )


def test_offered(source: Path) -> None:
    assert servers.offered(source) == [
        servers.Config("checkpoint", "insurgency", "checkpoint"),
        servers.Config("coop", "doi", "coop"),
    ]


def test_add_a_server_of_a_config(tmp_path: Path, source: Path) -> None:
    folder = tmp_path / "etc"
    first = servers.plan("coop", folder, source, "default")
    assert (first.config, first.game) == ("coop", "doi")
    assert "names none" in first.reason
    servers.write(first, single=False)
    assert first.path.read_text() == (
        "# The server coop, of nwi-server add\n"
        "SERVER_PORT=27015\nTV_PORT=27020\nCLIENT_PORT=27005\n"
    )
    assert first.path.stat().st_mode & 0o777 == 0o644
    second = servers.plan("ins", folder, source, "theirs", config="checkpoint")
    assert (second.game, second.reason) == ("insurgency", "the config checkpoint's")
    servers.write(second, single=False)
    assert games.read_env(second.path) == {
        "SERVER_PORT": "27016",
        "TV_PORT": "27021",
        "CLIENT_PORT": "27006",
        "CONFIG_SOURCE": "theirs",
        "SERVER_CONFIG_NAME": "checkpoint",
    }
    # With the one folder of configs for all servers, there are no sources to name
    third = servers.plan("ins2", folder, source, "theirs", config="checkpoint")
    assert "CONFIG_SOURCE" not in servers.env_text(third, single=True)


def test_add_a_server_without_a_config(tmp_path: Path, source: Path) -> None:
    new = servers.plan("plain", tmp_path, source, "default", game="insurgency")
    assert (new.config, new.game) == (None, "insurgency")
    assert "GAME=insurgency\n" in servers.env_text(new, single=False)


@pytest.mark.parametrize(
    ("name", "options", "error"),
    [
        ("plain", {}, "no config plain: name one with --config"),
        (
            "a",
            {"config": "missing"},
            "no config missing; its configs: checkpoint, coop",
        ),
        ("a", {"config": "checkpoint", "game": "doi"}, "is of insurgency, not doi"),
        ("a", {"game": "hl2"}, "hl2 isn't a game of the tools"),
        ("a/b", {"config": "coop"}, "not a server's name"),
        ("taken", {"config": "coop"}, "exists already"),
    ],
)
def test_add_refuses(
    tmp_path: Path, source: Path, name: str, options: dict[str, str], error: str
) -> None:
    (tmp_path / "taken.env").write_text("")
    with pytest.raises(ValueError, match=error):
        servers.plan(name, tmp_path, source, "default", **options)


def test_the_configs_of_a_source_without_a_version_are_cloned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = make_source(
        tmp_path / "repository", ["insurgency"], {"checkpoint": ""}
    )
    # Not the repository of a git hook that runs the tests (GIT_DIR, GIT_INDEX_FILE, …)
    for variable in [name for name in os.environ if name.startswith("GIT_")]:
        monkeypatch.delenv(variable)
    # git keeps no empty folders
    for folder in ("common", "insurgency"):
        (repository / "game" / folder / "cfg/server.cfg").write_text("")
    for command in (
        ["init", "--quiet", "--initial-branch", "main"],
        ["add", "."],
        ["-c", "user.name=test", "-c", "user.email=test@example.org", "commit", "--quiet",
         "--no-gpg-sign", "-m", "configs"],
    ):  # fmt: skip
        subprocess.run(["git", "-C", str(repository), *command], check=True)
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "theirs.env").write_text(f"URL={repository}\nREF=main\n")
    monkeypatch.setenv("NWI_SOURCES_DIR", str(sources))
    monkeypatch.setenv("NWI_LAYERS", str(tmp_path / "layers"))
    monkeypatch.delenv("NWI_CONFIG", raising=False)
    monkeypatch.setattr(games, "CHECKOUT", tmp_path / "no-checkout")
    with servers.source_configs("theirs") as configs:
        assert servers.offered(configs) == [
            servers.Config("checkpoint", "insurgency", "checkpoint")
        ]
        clone = configs
    assert not clone.exists()
    with (
        pytest.raises(ValueError, match="has no repository"),
        servers.source_configs("missing"),
    ):
        pass
