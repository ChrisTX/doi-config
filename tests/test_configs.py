"""The servers' settings and environment files, and the record of their workshop items (games.py,
server_config.py, update.py)."""

from pathlib import Path

import pytest
from srctools import Keyvalues

from nwi_server_kit import games, layers, server_config, update


def test_read_env(tmp_path: Path) -> None:
    env = tmp_path / "server.env"
    env.write_text(
        "# a comment\n"
        "; another\n"
        "SERVER_PORT=27016\n"
        "  GAME = insurgency  \n"
        'QUOTED="a b"\n'
        "SINGLE='c=d'\n"
        "not a variable\n"
    )
    assert games.read_env(env) == {
        "SERVER_PORT": "27016",
        "GAME": "insurgency",
        "QUOTED": "a b",
        "SINGLE": "c=d",
    }


def write_toml(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "server.toml"
    path.write_text(text)
    return path


def test_server_cfg(tmp_path: Path) -> None:
    settings = server_config.load(
        write_toml(
            tmp_path,
            'hostname = "Coop"\n'
            'startup_map = "bastogne stronghold"\n'
            'playlist = "nwi/coop_commando"\n'
            'mapcycle = "mapcycle_coop.txt"\n'
            'configs_after = ["doi-config/basic_coop.cfg"]\n',
        )
    )
    cfg = server_config.server_cfg(settings).splitlines()
    assert 'hostname "Coop"' in cfg
    assert 'tv_name "Coop | SourceTV"' in cfg
    assert cfg[-4:] == [
        'exec "doi-config/playlists/nwi/coop_commando.cfg"',
        'exec "doi-config/basic_settings.cfg"',
        'exec "doi-config/basic_coop.cfg"',
        'mapcyclefile "cfg/mapcycle_coop.txt"',
    ]


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ('hostname = "a"\n', "startup_map is missing"),
        ('hostname = "a"\nstartup_map = "b"\nbogus = 1\n', "unknown key bogus"),
        (
            'hostname = "a"\nstartup_map = "b"\nmaxplayers = true\n',
            "maxplayers is a number",
        ),
        ('hostname = "a"\nstartup_map = "b"\ngame = "csgo"\n', "game is one of"),
        (
            'hostname = "a"\nstartup_map = "b"\nruleset = "x"\n',
            "a ruleset needs a playlist",
        ),
    ],
)
def test_load_refuses_broken_settings(tmp_path: Path, text: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        server_config.load(write_toml(tmp_path, text))


def test_a_quote_in_a_config_is_refused() -> None:
    with pytest.raises(ValueError, match="quote"):
        server_config.quote('a"b')


def test_workshop_record(tmp_path: Path) -> None:
    """The record the game reads to take the items as installed, of the items' versions."""
    items = {}
    for item, manifest, size in ((111, "5555", 3), (222, "6666", 5)):
        version = (
            tmp_path / f"item-{item}.v" / f"item-{item}_20260101T000000.{manifest}+3"
        )
        content = version / f"steamapps/workshop/content/447820/{item}"
        content.mkdir(parents=True)
        (content / "map.bsp").write_bytes(b"x" * size)
        items[item] = version
    root = tmp_path / "root"
    update.write_record(root, 447820, items)
    record = Keyvalues.parse(
        (root / "steamapps/workshop/appworkshop_447820.acf").read_text()
    ).find_key("AppWorkshop")
    assert record["appid"] == "447820"
    assert record["SizeOnDisk"] == "8"
    installed = record.find_key("WorkshopItemsInstalled")
    assert installed.find_key("111")["manifest"] == "5555"
    assert installed.find_key("222")["size"] == "5"
    updated = str(layers.seconds("20260101T000000.5555"))
    assert (
        record.find_key("WorkshopItemDetails").find_key("222")["timeupdated"] == updated
    )


def test_remove_clones(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The clones of removed config sources go, those still set up or named stay."""
    sources_dir = tmp_path / "configs"
    sources_dir.mkdir()
    (sources_dir / "kept.env").write_text("URL=https://example.org/kept.git\n")
    monkeypatch.setenv("NWI_SOURCES_DIR", str(sources_dir))
    clones = tmp_path / "state/downloads/configs"
    for name in ("default", "kept", "named", "removed"):
        (clones / name / ".git").mkdir(parents=True)
    update.remove_clones(tmp_path / "state", ["named"])
    assert sorted(path.name for path in clones.iterdir()) == [
        "default",
        "kept",
        "named",
    ]
