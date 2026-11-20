"""A server's start (launch.py): its preparation in its writable layer, of a fake install in a
temporary folder, and its command line."""

import grp
import os
from pathlib import Path

import pytest

from nwi_server_kit import launch, rcon

SOURCEBANS = (
    '"SourceBans"\n{\n\t"Config"\n\t{\n'
    '\t\t"Website"\t\t"http://www.yourwebsite.net/"\n'
    '\t\t"BackupConfigs"\t"1"\n'
    '\t\t"ServerID"\t\t"-1"\n'
    '\t\t"ServerIP"\t\t""\n'
    "\t}\n}\n"
)


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A server's install of Day of Infamy with SourceMod's plugins and configs, and its environment
    cleared."""
    root = tmp_path / "server"
    game = root / "doi"
    plugins = game / "addons/sourcemod/plugins"
    (plugins / "disabled").mkdir(parents=True)
    for plugin in ("nextmap", "basebans", "basecomm", "nwi_cvar_unlocker"):
        (plugins / f"{plugin}.smx").touch()
    for plugin in ("admin-sql-threaded", "sql-admin-manager"):
        (plugins / "disabled" / f"{plugin}.smx").touch()
    (game / "addons/sourcemod/configs/sourcebans").mkdir(parents=True)
    (game / "addons/sourcemod/configs/sourcebans/sourcebans.cfg").write_text(SOURCEBANS)
    (game / "cfg").mkdir()
    (game / "gameinfo.txt").touch()
    for name in (
        "CREDENTIALS_DIRECTORY",
        "RCON_PASSWORD",
        "SERVER_PASSWORD",
        "DISABLE_PLUGINS",
        "TEST_ADMIN",
        "LAUNCH_OPTIONS",
        "SANITISER",
        "SOURCEBANS_WEBSITE",
        "SOURCEBANS_SERVER_ID",
        "SOURCEBANS_SERVER_IP",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(rcon, "RCON_DIR", tmp_path / "no-rcon")
    # RCON_GROUP ("nwi-rcon") is a system group that need not exist where the tests run; as root,
    # in the CI container, its absence would make the secret's chown fail. Use the test process's
    # own group, which always exists, so the tests don't depend on the system's state.
    monkeypatch.setattr(launch, "RCON_GROUP", grp.getgrgid(os.getgid()).gr_name)
    return root


def test_prepare(root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Twice, as a container that restarts keeps its writable layer: the same result."""
    credentials = tmp_path / "credentials"
    credentials.mkdir()
    (credentials / "server.sourcemod-databases").write_text('"Databases"\n{\n}\n\n')
    (credentials / "server.server-password").write_text("join\n")
    (credentials / "server.secret-cvars").write_text('sbpp_discord_banhook "x"\n')
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials))
    monkeypatch.setenv("DISABLE_PLUGINS", "nwi_cvar_unlocker")
    monkeypatch.setenv("TEST_ADMIN", "[U:1:246] 76561197960265974")
    monkeypatch.setenv("SOURCEBANS_WEBSITE", "bans.example.org")
    monkeypatch.setenv("SOURCEBANS_SERVER_IP", "192.0.2.7")
    (rcon.RCON_DIR).mkdir()
    for _ in range(2):
        launch.prepare(root, "coop")
    game = root / "doi"
    plugins = game / "addons/sourcemod/plugins"
    assert sorted(path.name for path in plugins.glob("*.smx")) == [
        "admin-sql-threaded.smx",
        "basecomm.smx",
        "sql-admin-manager.smx",
    ]
    assert sorted(path.name for path in (plugins / "disabled").iterdir()) == [
        "basebans.smx",
        "nextmap.smx",
        "nwi_cvar_unlocker.smx",
    ]
    configs = game / "addons/sourcemod/configs"
    assert (configs / "admins_simple.ini").read_text() == (
        '"[U:1:246]"\t"100:z"\t// Test admin (TEST_ADMIN)\n'
        '"76561197960265974"\t"100:z"\t// Test admin (TEST_ADMIN)\n'
    )
    sourcebans = (configs / "sourcebans/sourcebans.cfg").read_text()
    assert '"Website"\t\t"https://bans.example.org"' in sourcebans
    assert '"BackupConfigs"\t"0"' in sourcebans
    assert '"ServerID"\t\t"-1"' in sourcebans
    assert '"ServerIP"\t\t"192.0.2.7"' in sourcebans
    databases = configs / "databases.cfg"
    assert databases.read_text() == '"Databases"\n{\n}\n'
    assert databases.stat().st_mode & 0o777 == 0o600
    # A generated RCON password, the second start's, for nwi-rcon --server
    password = (rcon.RCON_DIR / "coop").read_text().strip()
    assert len(password) >= 32
    assert (rcon.RCON_DIR / "coop").stat().st_mode & 0o777 == 0o640
    secrets = game / "cfg/nwi-secrets.cfg"
    assert secrets.read_text() == (
        f'rcon_password "{password}"\nsv_password "join"\nsbpp_discord_banhook "x"\n'
    )
    assert secrets.stat().st_mode & 0o777 == 0o600
    assert (game / "cfg/server.cfg").read_text() == "exec nwi-secrets.cfg\n"


def test_prepare_without_credentials(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As in the container: the passwords of the environment, none generated."""
    monkeypatch.setenv("RCON_PASSWORD", "secret")
    launch.prepare(root, "coop")
    assert (root / "doi/cfg/nwi-secrets.cfg").read_text() == 'rcon_password "secret"\n'
    assert not (root / "doi/addons/sourcemod/configs/databases.cfg").exists()


@pytest.mark.parametrize(
    ("variable", "value", "error"),
    [
        ("RCON_PASSWORD", 'a"b', "quote"),
        ("TEST_ADMIN", "STEAM_9:0:1", "SteamID"),
    ],
)
def test_prepare_refuses(
    root: Path, monkeypatch: pytest.MonkeyPatch, variable: str, value: str, error: str
) -> None:
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValueError, match=error):
        launch.prepare(root, "coop")


def test_command(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """server.toml's options, then LAUNCH_OPTIONS', which win."""
    (root / "doi/server.toml").write_text(
        'hostname = "Test"\nstartup_map = "bastogne stronghold"\n'
        'tickrate = 64\nlaunch_options = ["-nobots"]\n'
    )
    monkeypatch.setenv("SERVER_PORT", "27115")
    monkeypatch.setenv("LAUNCH_OPTIONS", "+developer 2  +sv_cheats 1")
    assert launch.command(root) == [
        str(root / "srcds_linux"),
        "-game",
        "doi",
        "-usercon",
        "-port",
        "27115",
        "+tv_port",
        "27020",
        "+clientport",
        "27005",
        "+r_hunkalloclightmaps",
        "0",
        "+maxplayers",
        "64",
        "+sv_lan",
        "0",
        "-tickrate",
        "64",
        "+map",
        "bastogne stronghold",
        "-nobots",
        "+developer",
        "2",
        "+sv_cheats",
        "1",
    ]


def test_sanitiser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The newest clang's runtime of 32-bit x86."""
    for version in ("21", "22"):
        folder = tmp_path / version / "lib/i386-pc-linux-gnu"
        folder.mkdir(parents=True)
        (folder / "libclang_rt.asan.so").touch()
    monkeypatch.setattr(launch, "CLANG", tmp_path)
    monkeypatch.delenv("ASAN_OPTIONS", raising=False)
    monkeypatch.delenv("SANITISER", raising=False)
    assert launch.sanitiser_environment() == {}
    monkeypatch.setenv("SANITISER", "address,undefined")
    environment = launch.sanitiser_environment()
    assert environment["LD_PRELOAD"] == str(
        tmp_path / "22/lib/i386-pc-linux-gnu/libclang_rt.asan.so"
    )
    assert environment["ASAN_OPTIONS"] == "print_stacktrace=1:detect_leaks=1"
    monkeypatch.setenv("SANITISER", "undefined")
    with pytest.raises(ValueError, match="ubsan"):
        launch.sanitiser_environment()


def test_geoip_extension(root: Path, tmp_path: Path) -> None:
    """Without a GeoIP database the extension goes, with one it stays."""
    game = root / "doi"
    extensions = game / "addons/sourcemod/extensions"
    (extensions / "x64").mkdir(parents=True)
    for name in launch.GEOIP_EXTENSIONS:
        (extensions / name).touch()
    (extensions / "sdktools.ext.2.doi.so").touch()
    geoip = game / "addons/sourcemod/configs/geoip"
    geoip.mkdir(parents=True)
    # The package's link, to a database that isn't there
    (geoip / "GeoLite2-City.mmdb").symlink_to(tmp_path / "GeoIP/GeoLite2-City.mmdb")
    launch.configure_geoip(game)
    assert not any((extensions / name).exists() for name in launch.GEOIP_EXTENSIONS)
    assert (extensions / "sdktools.ext.2.doi.so").exists()
    (tmp_path / "GeoIP").mkdir()
    (tmp_path / "GeoIP/GeoLite2-City.mmdb").write_bytes(b"mmdb")
    (extensions / "geoip.ext.so").touch()
    launch.configure_geoip(game)
    assert (extensions / "geoip.ext.so").exists()
