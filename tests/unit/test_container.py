"""The container image's server start (container.py): the game's folder assembled of the image's files,
the mounts and the server's config, in a temporary folder."""

from collections.abc import Callable
from pathlib import Path

import pytest

from nwi_server_kit import container
from nwi_server_kit.cli import container as container_cli


@pytest.fixture
def paths(tmp_path: Path) -> container.Paths:
    """An image and the mounts of a server of Day of Infamy, with the Steam client's depot."""
    paths = container.Paths(
        repository=tmp_path / "repository",
        root=tmp_path / "game",
        state=tmp_path / "state",
        layer=tmp_path / "layer",
        mods=tmp_path / "mods",
        layers=tmp_path / "layers",
        depots=tmp_path / "depots.list",
        data=tmp_path / "data",
        secrets=tmp_path / "secrets",
    )
    (paths.root / "doi").mkdir(parents=True)
    (paths.root / "doi/gameinfo.txt").touch()
    (paths.root / "srcds_linux").touch(mode=0o755)
    (paths.root / "doi/logs").mkdir()
    (paths.root / "doi/logs/old.log").touch()
    steam = paths.layers / "depot-1006.v/depot-1006_1.2"
    (steam / "linux64").mkdir(parents=True)
    (steam / "linux64/steamclient.so").write_text("steam")
    paths.depots.write_text("depot-1006.v/depot-1006_1.2\n\n")
    (paths.layer / "addons/sourcemod/plugins").mkdir(parents=True)
    (paths.layer / "addons/sourcemod/plugins/nwi_gamedata.smx").write_text("plugin")
    (paths.mods / "custom/tobruk_invasion/maps").mkdir(parents=True)
    (paths.mods / "custom/tobruk_invasion/maps/tobruk.txt").write_text("script")
    config = paths.repository / "servers/coop"
    (config / "cfg").mkdir(parents=True)
    (config / "server.toml").write_text('hostname = "Coop"\n')
    (paths.repository / "servers/shared.txt").write_text("motd")
    (config / "motd.txt").symlink_to("../shared.txt")
    (paths.secrets / "addons/sourcemod/configs").mkdir(parents=True)
    (paths.secrets / "addons/sourcemod/configs/databases.cfg").write_text("db")
    return paths


def test_assemble(paths: container.Paths) -> None:
    """Twice, as a container that restarts keeps its writable layer: the same result."""
    for _ in range(2):
        game = container.assemble(paths, "coop")
    assert game == paths.root / "doi"
    steam = paths.root / "linux64/steamclient.so"
    assert steam.is_symlink() and steam.read_text() == "steam"
    assert (game / "addons/sourcemod/plugins/nwi_gamedata.smx").read_text() == "plugin"
    assert (game / "custom/tobruk_invasion/maps/tobruk.txt").read_text() == "script"
    # The server's config, its link resolved, and the secrets
    assert (game / "server.toml").is_file()
    motd = game / "motd.txt"
    assert not motd.is_symlink() and motd.read_text() == "motd"
    assert (game / "addons/sourcemod/configs/databases.cfg").read_text() == "db"
    # What the server keeps is linked to the data's volumes, the game's old logs replaced
    assert (game / "logs").readlink() == paths.data / "logs"
    assert (game / "addons/sourcemod/data").readlink() == paths.data / "sourcemod/data"
    assert (paths.root / "dumps").readlink() == paths.data / "dumps"


def test_without_a_config_or_mounts(paths: container.Paths) -> None:
    """A server of no config of the repository, without mods, depots or secrets."""
    for optional in (paths.mods, paths.secrets):
        for path in sorted(optional.rglob("*"), reverse=True):
            path.rmdir() if path.is_dir() else path.unlink()
        optional.rmdir()
    paths.depots.unlink()
    game = container.assemble(paths, None)
    assert not (game / "server.toml").exists()
    assert not (paths.root / "linux64").exists()


@pytest.mark.parametrize(
    ("server", "error"), [("pvp", "config pvp isn't"), (None, "no game in")]
)
def test_refused(paths: container.Paths, server: str | None, error: str) -> None:
    if server is None:
        (paths.root / "srcds_linux").unlink()
    with pytest.raises(ValueError, match=error):
        container.assemble(paths, server)


def test_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    """update and check run the update and the check of the image's state."""
    calls: list[tuple[str, list[str]]] = []

    def recorded(name: str, status: int) -> Callable[[list[str]], int]:
        def run(argv: list[str]) -> int:
            calls.append((name, argv))
            return status

        return run

    monkeypatch.setattr(container_cli.update_cli, "main", recorded("update", 0))
    monkeypatch.setattr(container_cli.check_updates, "main", recorded("check", 1))
    assert container_cli.main(["update"]) == 0
    assert container_cli.main(["check"]) == 1
    assert calls == [("update", ["--image", "/srv/state"]), ("check", ["/srv/state"])]
    assert container_cli.main(["bogus"]) == 2
