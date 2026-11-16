"""A server's start: its preparation in its writable layer and its run under the watchdog, for
nwi-server@.service and the container's entrypoint, which share them this way.

prepare configures a server in its writable layer: one assembled by nwi-server mount, whose writable
layer starts empty whenever nwi-server@.service mounts it, on every start of the server
(nwi-server@.service runs it as root with "!", as the layers belong to root), or the container's
(container.py), which keeps its writable layer when the container restarts, so
preparing it twice changes nothing. It makes the server's server.cfg and subscribed_file_ids.txt of
its server.toml (server_config.py); without one, e.g. a server of no config of servers/, its own
cfg/server.cfg comes from the secrets. It enables SourceMod's SQL admins and disables the plugins
that don't go with Day of Infamy or SourceBans++, and those of DISABLE_PLUGINS.

The secrets are the unit's credentials (nwi-server@.service imports them as server.<name>):
    sourcemod-databases  addons/sourcemod/configs/databases.cfg, SourceMod's and SourceBans++'s
                         databases
    rcon-password        the RCON password; without one, a new random one at every start
    server-password      the password to join, if the server has one
    secret-cvars         more secret settings, as lines of a config, e.g. SourceBans++'s webhooks
                         (sbpp_discord_banhook "…")
Without credentials, as in the container, RCON_PASSWORD and SERVER_PASSWORD of the environment. The
passwords and secret-cvars go into cfg/nwi-secrets.cfg, which server.cfg runs last: on the command
line, the process list would show them. A generated RCON password is written to
/run/nwi-server/rcon/<server>, which the group nwi-rcon can read (nwi-rcon --server, rcon.py).

start runs the server with the options of its server.toml (the slots, LAN or not, the workshop, the
first map, the theater and more), as the main process of nwi-server@.service (watchdog.py).

The environment, the server's environment file (/etc/nwi-server/<server>.env):
    SERVER_PORT, TV_PORT, CLIENT_PORT  the server's ports
    LAUNCH_OPTIONS    more options of the command line, separated by spaces, after server.toml's, so
                      that they win, e.g. +developer 2 for a test server
    DISABLE_PLUGINS   plugins the server starts without, by name, separated by spaces, e.g.
                      nwi_cvar_unlocker for the game's own bounds of its cvars (checks/dump_cvars.py)
    TEST_ADMIN        SteamIDs, separated by spaces, that get root in admins_simple.ini, which
                      admin-flatfile.smx reads with or without a database, e.g. on a test server of
                      no database (tests/integration/instance.py sets it; the live servers don't have it)
    SOURCEBANS_WEBSITE, SOURCEBANS_SERVER_ID, SOURCEBANS_SERVER_IP
                      SourceBans++'s web panel, the server's ID in it (left at -1, SourceBans++ looks
                      it up by the server's address and port), and its address where the server's own
                      is a private one, as in a container
    SANITISER         undefined, address or address,undefined, for a server with test builds of
                      SourceMod and Metamod:Source with these sanitisers (./aur-packages build
                      --sanitize of the AUR packages, see README.md): their 32-bit runtime of
                      compiler-rt is preloaded into srcds too, and they report to the server's output
                      with stack traces (UBSAN_OPTIONS and ASAN_OPTIONS, unless they're set)

The commands: cli/launch.py.
"""

import os
import pwd
import re
import secrets
import shutil
from pathlib import Path

from . import games, rcon, server_config, watchdog

# A SteamID as SourceMod takes it in admins_simple.ini
STEAM_ID = re.compile(r"STEAM_[0-5]:[01]:[0-9]+|\[U:1:[0-9]+\]|[0-9]{17}")
# The sanitisers' runtimes of compiler-rt, of 32-bit x86, by SANITISER
RUNTIMES = {
    "undefined": "libclang_rt.ubsan_standalone.so",
    "address": "libclang_rt.asan.so",
    "address,undefined": "libclang_rt.asan.so",
    "undefined,address": "libclang_rt.asan.so",
}
CLANG = Path("/usr/lib/clang")
RCON_GROUP = "nwi-rcon"


def move_plugin(source: Path, folder: Path) -> None:
    """Move a plugin into a folder unless it's moved already: a container that restarts keeps its
    writable layer."""
    if source.is_file():
        source.rename(folder / source.name)


def configure_plugins(game: Path) -> None:
    plugins = game / "addons/sourcemod/plugins"
    disabled = plugins / "disabled"
    # SourceMod's SQL admins
    move_plugin(disabled / "admin-sql-threaded.smx", plugins)
    move_plugin(disabled / "sql-admin-manager.smx", plugins)
    # Nextmap doesn't work with Day of Infamy, and SourceBans++ needs basebans off
    move_plugin(plugins / "nextmap.smx", disabled)
    move_plugin(plugins / "basebans.smx", disabled)
    for name in os.environ.get("DISABLE_PLUGINS", "").split():
        move_plugin(plugins / f"{name}.smx", disabled)


def add_test_admins(game: Path) -> None:
    """TEST_ADMIN's SteamIDs into admins_simple.ini, once each."""
    path = game / "addons/sourcemod/configs/admins_simple.ini"
    for admin in os.environ.get("TEST_ADMIN", "").split():
        if not STEAM_ID.fullmatch(admin):
            raise ValueError(
                "TEST_ADMIN has no SteamID like STEAM_0:0:123, [U:1:246] or "
                f"76561197960265974: {admin}"
            )
        text = path.read_text() if path.is_file() else ""
        if f'"{admin}"' not in text:
            with path.open("a") as file:
                file.write(f'"{admin}"\t"100:z"\t// Test admin (TEST_ADMIN)\n')


def configure_sourcebans(game: Path) -> None:
    path = game / "addons/sourcemod/configs/sourcebans/sourcebans.cfg"
    values = {"BackupConfigs": "0"}
    if os.environ.get("SOURCEBANS_WEBSITE"):
        values["Website"] = f"https://{os.environ['SOURCEBANS_WEBSITE']}"
    if os.environ.get("SOURCEBANS_SERVER_ID"):
        values["ServerID"] = os.environ["SOURCEBANS_SERVER_ID"]
    if os.environ.get("SOURCEBANS_SERVER_IP"):
        values["ServerIP"] = os.environ["SOURCEBANS_SERVER_IP"]
    text = path.read_text()
    for key, value in values.items():
        # The value as re.sub's replacement, its backslashes escaped
        replacement = value.replace("\\", "\\\\")
        text = re.sub(
            rf'("{re.escape(key)}"\s+)"[^"\n]*"', rf'\g<1>"{replacement}"', text
        )
    path.write_text(text)


def credential(name: str) -> str | None:
    """A credential of the unit, if it has it."""
    folder = os.environ.get("CREDENTIALS_DIRECTORY")
    if not folder:
        return None
    try:
        return (Path(folder) / f"server.{name}").read_text()
    except OSError:
        return None


def write_secret(
    path: Path, text: str, mode: int = 0o600, group: str | None = None
) -> None:
    """Write a file readable by the server's user only: under systemd, which runs prepare as root with
    the server's user, its dynamic user (DynamicUser=), in USER. With GROUP, by its members too."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(descriptor, "w") as file:
        os.fchmod(descriptor, mode)
        user = os.environ.get("USER")
        if os.geteuid() == 0:
            if group is not None:
                shutil.chown(path, group=group)
            elif user and user != "root":
                # The user and its login group, as chown USER: does
                account = pwd.getpwnam(user)
                os.fchown(descriptor, account.pw_uid, account.pw_gid)
        file.write(text)


def configure_secrets(game: Path, name: str) -> None:
    databases = credential("sourcemod-databases")
    if databases:
        write_secret(
            game / "addons/sourcemod/configs/databases.cfg",
            databases.rstrip("\n") + "\n",
        )
    password = credential("rcon-password")
    rcon_password = (
        password.rstrip("\n")
        if password is not None
        else os.environ.get("RCON_PASSWORD", "")
    )
    password = credential("server-password")
    server_password = (
        password.rstrip("\n")
        if password is not None
        else os.environ.get("SERVER_PASSWORD", "")
    )
    # A new RCON password for the servers of nwi-server@.service without one
    if not rcon_password and rcon.RCON_DIR.is_dir():
        rcon_password = secrets.token_urlsafe(24)
    if '"' in rcon_password + server_password:
        raise ValueError("a password can't have a quote")
    if rcon_password and rcon.RCON_DIR.is_dir():
        write_secret(
            rcon.RCON_DIR / name, rcon_password + "\n", mode=0o640, group=RCON_GROUP
        )
    lines = []
    if rcon_password:
        lines.append(f'rcon_password "{rcon_password}"\n')
    if server_password:
        lines.append(f'sv_password "{server_password}"\n')
    write_secret(
        game / "cfg/nwi-secrets.cfg",
        "".join(lines) + (credential("secret-cvars") or ""),
    )
    server_cfg = game / "cfg/server.cfg"
    text = server_cfg.read_text() if server_cfg.is_file() else ""
    if "exec nwi-secrets.cfg" not in text:
        with server_cfg.open("a") as file:
            file.write("exec nwi-secrets.cfg\n")


def prepare(root: Path, name: str) -> None:
    game = games.game_folder(root)
    if (game / "server.toml").is_file():
        server_config.prepare(root)
    configure_plugins(game)
    add_test_admins(game)
    configure_sourcebans(game)
    configure_secrets(game, name)


def sanitiser_environment() -> dict[str, str]:
    """The environment of a server with SANITISER: its runtime preloaded, into srcds only, as the
    watchdog is a 64-bit Python."""
    sanitiser = os.environ.get("SANITISER")
    if not sanitiser:
        return {}
    if sanitiser not in RUNTIMES:
        raise ValueError(
            f"unknown SANITISER {sanitiser} (undefined, address or address,undefined)"
        )
    runtimes = sorted(CLANG.glob(f"*/lib/i386-pc-linux-gnu/{RUNTIMES[sanitiser]}"))
    if not runtimes:
        raise ValueError(f"no {RUNTIMES[sanitiser]} of compiler-rt for 32-bit x86")
    return {
        "LD_PRELOAD": str(runtimes[-1]),
        "UBSAN_OPTIONS": os.environ.get(
            "UBSAN_OPTIONS", "print_stacktrace=1:report_error_type=1"
        ),
        "ASAN_OPTIONS": os.environ.get(
            "ASAN_OPTIONS", "print_stacktrace=1:detect_leaks=1"
        ),
    }


def command(root: Path) -> list[str]:
    """The server's command line."""
    game = games.game_folder(root)
    return [
        str(root / "srcds_linux"),
        "-game",
        game.name,
        "-usercon",
        "-port",
        os.environ.get("SERVER_PORT", "27015"),
        "+tv_port",
        os.environ.get("TV_PORT", "27020"),
        "+clientport",
        os.environ.get("CLIENT_PORT", "27005"),
        "+r_hunkalloclightmaps",
        "0",
        *server_config.options(root),
        *os.environ.get("LAUNCH_OPTIONS", "").split(),
    ]


def start(root: Path) -> int:
    line = command(root)
    environment = dict(os.environ) | sanitiser_environment()
    return watchdog.watch(
        line, watchdog.default_host(), watchdog.default_port(), env=environment
    )
