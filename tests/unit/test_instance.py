"""The test instance's parts that don't need Podman (tests/integration/instance.py): its settings,
the admins' SteamIDs, up's options, the files it writes and the configs it finds."""

import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from tests.integration import instance


def test_settings(tmp_path: Path) -> None:
    """The file's settings, unless the environment has them; comments and blank lines are skipped."""
    path = tmp_path / "test-instance.env"
    path.write_text("# mine\n\nTEST_ADMIN=[U:1:2]\nSANITISER=undefined\n")
    settings = instance.read_settings(path, {"SANITISER": "address", "HOME": "/x"})
    assert settings == {"TEST_ADMIN": "[U:1:2]", "SANITISER": "address"}
    assert instance.read_settings(tmp_path / "none", {}) == {}
    path.write_text("PATH=/tmp\n")
    with pytest.raises(instance.InstanceError, match="not a setting"):
        instance.read_settings(path, {})


@pytest.mark.parametrize(
    ("steam_id", "expected"),
    [
        ("STEAM_1:1:123", "STEAM_0:1:123"),
        ("STEAM_0:0:0042", "STEAM_0:0:42"),
        ("[U:1:246]", "STEAM_0:0:123"),
        ("[U:1:247]", "STEAM_0:1:123"),
        ("76561197960265974", "STEAM_0:0:123"),
    ],
)
def test_steam2(steam_id: str, expected: str) -> None:
    assert instance.steam2(steam_id) == expected


@pytest.mark.parametrize(
    "steam_id",
    [
        "STEAM_9:0:1",
        "[U:1:0]",
        "[U:2:5]",
        "103582791429521412",
        "abc",
        "7656119796026597",
    ],
)
def test_steam2_refuses(steam_id: str) -> None:
    """A malformed ID, account 0, a group's (type 7) or a too short SteamID64."""
    with pytest.raises(instance.InstanceError, match="SteamID"):
        instance.steam2(steam_id)


def test_up_options() -> None:
    settings = {"LAUNCH_OPTIONS": "+sv_cheats 1"}
    up = instance.parse_up(["--developer", "2", "ins-test", "--", "-nobots"], settings)
    assert up == instance.Up(
        "ins-test", False, ["+sv_cheats", "1", "+developer", "2", "-nobots"]
    )
    assert instance.parse_up(["--db-only"], {}) == instance.Up(db_only=True)


@pytest.mark.parametrize(
    ("args", "error"),
    [
        (["--developer"], "needs a level"),
        (["--developer", "x"], "needs a level"),
        (["--bogus"], "unknown option"),
        (["coop", "--", "a b"], "with a space"),
        (["coop", "--", ""], "empty"),
    ],
)
def test_up_refuses(args: list[str], error: str) -> None:
    with pytest.raises(instance.InstanceError, match=error):
        instance.parse_up(args, {})


def test_server_env() -> None:
    env = instance.server_env(["STEAM_0:0:1"], ["+developer", "2"])
    lines = dict(line.split("=", 1) for line in env.splitlines())
    assert lines["SERVER_PORT"] == "27015" and lines["CLIENT_PORT"] == "27025"
    assert len(lines["RCON_PASSWORD"]) >= 16
    assert lines["TEST_ADMIN"] == "STEAM_0:0:1"
    assert lines["LAUNCH_OPTIONS"] == "+developer 2"
    assert "TEST_ADMIN" not in instance.server_env([], [])


def test_sql() -> None:
    server, admins = instance.instance_sql("doi", ["STEAM_0:0:1", "STEAM_0:1:2"])
    assert "'Day of Infamy', 'web.png', 'doi'" in server
    assert "modfolder = 'doi'" in server
    assert admins.count("INSERT INTO sm_admins") == 2
    assert "'Test admin 2', 'STEAM_0:1:2'" in admins
    assert instance.instance_sql("insurgency", [])[1] == ""


def test_databases_cfg() -> None:
    text = instance.databases_cfg("secret", 3307)
    for entry in ("default", "sourcebans", "clientprefs"):
        assert f'"{entry}"' in text
    assert text.count('"port"\t"3307"') == 3
    assert text.count('"pass"\t"secret"') == 3
    assert '"storage-local"' in text


def test_configs(tmp_path: Path) -> None:
    """A config of servers/, or a test's, which a container gets mounted among the image's."""
    for folder in ("servers/coop", "tests/integration/servers/soak"):
        (tmp_path / folder).mkdir(parents=True)
        (tmp_path / folder / "server.toml").touch()
    assert instance.config_folder("coop", tmp_path) == tmp_path / "servers/coop"
    assert instance.config_mounts(["coop", "soak"], tmp_path) == [
        "-v",
        f"{tmp_path}/tests/integration/servers/soak:/opt/nwi-server-kit/servers/soak:ro",
    ]
    with pytest.raises(instance.InstanceError, match="no config pvp"):
        instance.config_folder("pvp", tmp_path)


def fake_commands(
    monkeypatch: pytest.MonkeyPatch, answers: dict[tuple[str, ...], str]
) -> None:
    """Commands answered by ANSWERS, by their arguments; aurutils missing."""

    def run(*args: str, capture: bool = False, check: bool = True) -> str:
        if args not in answers:
            raise subprocess.CalledProcessError(1, args)
        return answers[args]

    monkeypatch.setattr(instance, "run", run)
    monkeypatch.setattr(instance, "succeeds", lambda *args: False)


def test_find_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without aurutils, the one file:// repository of pacman.conf, or the one AUR_REPO names."""
    (tmp_path / "custom.db").touch()
    fake_commands(
        monkeypatch,
        {
            ("pacman-conf", "--repo-list"): "core\ncustom\nother\n",
            ("pacman-conf", "--repo=core"): "",
            ("pacman-conf", "--repo=core", "Server"): "https://mirror/core\n",
            ("pacman-conf", "--repo=custom", "Server"): f"file://{tmp_path}/\n",
            ("pacman-conf", "--repo=other", "Server"): "file:///srv/other\n",
        },
    )
    with pytest.raises(instance.InstanceError, match="2 local repositories"):
        instance.find_repo({})
    assert instance.find_repo({"AUR_REPO": "custom"}) == ("custom", tmp_path)
    with pytest.raises(instance.InstanceError, match="no local"):
        instance.find_repo({"AUR_REPO": "missing"})


def test_version_key() -> None:
    names = ["sourcebans-pp-1.10.0-1.pkg.tar.zst", "sourcebans-pp-1.9.2-3.pkg.tar.zst"]
    assert max(names, key=lambda name: instance.version_key(Path(name))) == names[0]


def test_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert instance.main(["bogus"]) == 2
    assert "instance.py up" in capsys.readouterr().err


def test_package_file(tmp_path: Path) -> None:
    """A package's file of a repository's database (a tar of each package's desc)."""
    database = tmp_path / "aurutils.db"
    with tarfile.open(database, "w:gz") as archive:
        for name, file in (
            ("sourcebans-pp", "sourcebans-pp-2.2.3-5-any.pkg.tar.zst"),
            ("sourcemod", "sourcemod-1.12-1-x86_64.pkg.tar.zst"),
        ):
            desc = f"%FILENAME%\n{file}\n\n%NAME%\n{name}\n".encode()
            info = tarfile.TarInfo(f"{name}-1/desc")
            info.size = len(desc)
            archive.addfile(info, io.BytesIO(desc))
    found = instance.package_file(database, "sourcebans-pp")
    assert found == "sourcebans-pp-2.2.3-5-any.pkg.tar.zst"
    with pytest.raises(instance.InstanceError, match="no metamod"):
        instance.package_file(database, "metamod")


def test_repository_setting() -> None:
    assert not instance.Instance({}).local
    assert instance.Instance({"NWI_TEST_REPO": "local"}).local
    with pytest.raises(instance.InstanceError, match="public or local"):
        _ = instance.Instance({"NWI_TEST_REPO": "mine"}).local
