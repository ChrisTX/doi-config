#!/usr/bin/env python3
"""A local test instance of a server in a Podman pod, with a new MariaDB that has SourceBans++'s and
SourceMod's tables, the server registered in SourceBans++ and optionally an admin. Nothing of it reaches
the live servers: the passwords are generated, and without its config the Discord forward stays silent.

Usage:
    instance.py build [--local] [--testing] [PODMAN BUILD OPTION...]
        build the image (podman build, see docs/kit/Containers.md) with the packages of the public repository, or
        with --local (or NWI_TEST_REPO=local) of the local pacman repository, e.g. for packages not
        published yet; with --testing with Arch Linux's testing repositories, for packages built
        against them, as on a machine that uses them
    instance.py update [CONFIG...]
        update the games, the workshop items and the mods of the configs (all of servers/ by default,
        which includes Insurgency's test server) in the state folder with the image's updater
        (nwi-server container update), which the server mounts; the first downloads the games and the
        items. An update of some configs keeps what the others have, but doesn't update it
    instance.py up [--db-only] [--developer LEVEL] [CONFIG] [-- OPTION...]
        start the test instance of a config (coop-commando by default), anew; with --db-only only its
        database, for the systemd units on this machine; with --developer the server's developer
        messages of LEVEL (+developer LEVEL, 1 or 2), and with OPTION... more options of its command
        line, e.g. -- +sv_cheats 1, which the systemd units get too (LAUNCH_OPTIONS of nwi-server start)
    instance.py soak [--hours HOURS] [LOG]
        the soak test: update and start soak-bots (tests/integration/servers), from the sanitiser image
        with SANITISER, log it with tests/integration/soak_watch.py for HOURS (8 by default) to LOG
        (soak-<time>.tsv in the working folder) and the server's output next to it (LOG without .tsv,
        .log), then remove it
    instance.py rounds [CONFIG...]
        the round test: update and start each config (coop-commando and soak-bots by default) in turn,
        let bots play its rounds and check that they do (tests/integration/rounds.py), then remove it;
        exit status 1 if a config failed
    instance.py stress [--seconds SECONDS] [--rate RATE] [--floods FLOOD,...] [CONFIG]
        the stress test of the network: update and start a config (coop-commando by default), flood its
        game port from spoofed addresses with and without deploy/nftables/nwi-game-ports.nft while a
        client queries it and starts connections, check that with the table it keeps its tick and
        serves the client (tests/integration/stress.py, in a network namespace of the pod's, with
        podman unshare), then remove it; SECONDS each flood (20 by default) at RATE packets a second
        (20000), FLOOD... of tests/integration/stress.py (all by default); with SANITISER also no
        sanitiser report in the server's output; exit status 1 if a check failed
    instance.py dump-cvars [--with-descriptions] GAME
        dump the cvars and commands of GAME (doi, insurgency) into checks/cvars/<GAME>.json for
        checks/check_configs.py (checks/dump_cvars.py): update and start its test server (coop-commando
        or ins-test) without nwi_cvar_unlocker, for the game's own bounds and flags, then remove it;
        with --with-descriptions their help texts too, into checks/cvars/descriptions/<GAME>.json,
        which git ignores, for editors on this machine
    instance.py down
        remove the test instance, its database and volumes
    instance.py rcon COMMAND...
        run a command on the server over RCON
    instance.py logs
        follow the server's log

A config is one of servers/, or of tests/integration/servers/, the tests' own, e.g. soak-bots, which the
containers get mounted among the image's (servers/<config>): they run in the container only. A config's
own cfg folder goes into the game's, e.g. a test's configs and mapcycle.

The packages come from the public repository (https://repo.rev-crew.info/aurutils), verified with its
key, deploy/container/aurutils.asc, or from the local pacman repository, which aurutils builds into,
found like aurutils finds it (aur repo --status, or the one file:// repository of pacman.conf without
aurutils), whose database's signature names its key. The repository's package of the SourceBans++ web
panel has the database's tables.

The settings, of the environment or of ${XDG_CONFIG_HOME:-~/.config}/nwi-server-kit/test-instance.env,
one VAR=value a line, e.g. TEST_ADMIN=[U:1:123], the environment's taking precedence:
    AUR_REPO, AUR_DBROOT  the local repository's name and folder, as for aurutils
    NWI_TEST_DIR          the test instance's files (${XDG_STATE_HOME:-~/.local/state}/nwi-test)
    NWI_STATE             the state folder with the game, the workshop items and the mods
                          (${XDG_STATE_HOME:-~/.local/state}/nwi-server, as for the Quadlet units)
    DISABLE_PLUGINS       plugins the server starts without, by name, e.g. nwi_cvar_unlocker for the
                          game's own bounds in checks/dump_cvars.py
    TEST_ADMIN            SteamIDs that get root admin, separated by spaces, each as STEAM_0:…,
                          STEAM_1:…, [U:1:…] or SteamID64: in the database, and in admins_simple.ini
                          through the server's environment file (nwi-server prepare), so also on
                          servers without the database
    TEST_DB_PORT          the database's port on 127.0.0.1 with --db-only (3306)
    SANITISER             undefined, address or address,undefined: up starts the server from the
                          sanitiser image (localhost/nwi-server-sanitiser, tests/integration/sanitiser,
                          see docs/kit/Testing.md), with its runtime preloaded
    LAUNCH_OPTIONS        options of the server's command line for every up, separated by spaces,
                          before those of up's own
    NWI_TEST_REPO         public (the default) or local: the repository of build and of the database's
                          tables
"""

import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
# The package from the checkout, and the round test next to this file, also when run as a script
sys.path[:0] = [str(REPOSITORY / "src"), str(REPOSITORY)]
from nwi_server_kit import rcon as rcon_client
from tests.integration import rounds as round_checks
from tests.integration.soak_watch import REPORT

SETTINGS = (
    "AUR_REPO",
    "AUR_DBROOT",
    "NWI_TEST_DIR",
    "NWI_STATE",
    "DISABLE_PLUGINS",
    "TEST_ADMIN",
    "TEST_DB_PORT",
    "SANITISER",
    "LAUNCH_OPTIONS",
    "NWI_TEST_REPO",
)
IMAGE = "localhost/nwi-server"
SANITISER_IMAGE = "localhost/nwi-server-sanitiser"
POD = "nwi-test"
# The image's user is this one, who owns the state folder
USERNS = "keep-id:uid=1000,gid=1000"
# What the server keeps, the pod's volumes and where the image has them
VOLUMES = {
    "dumps": "/srv/nwi-data/dumps",
    "logs": "/srv/nwi-data/logs",
    "sm-logs": "/srv/nwi-data/sourcemod/logs",
    "sm-data": "/srv/nwi-data/sourcemod/data",
}
SOURCEMOD_SQL = Path(
    "/usr/lib/sourcemod/addons/sourcemod/configs/sql-init-scripts/mysql"
)
GNUPG = "/etc/pacman.d/gnupg"
# The public repository and its key, pinned in the repository
PUBLIC_REPO = "aurutils"
PUBLIC_URL = "https://repo.rev-crew.info/aurutils"
PUBLIC_KEY = REPOSITORY / "deploy/container/aurutils.asc"
PUBLIC_FINGERPRINT = "50D39A5279BF71B8046B3A70713B08F8AD610C32"
SOURCEBANS = "sourcebans-pp"


class InstanceError(RuntimeError):
    """What stops a command, with the message for the user."""


# The test server of each game whose cvars dump-cvars dumps
DUMP_CONFIGS = {"doi": "coop-commando", "insurgency": "ins-test"}


def read_settings(path: Path, environ: Mapping[str, str]) -> dict[str, str]:
    """The settings: the environment's, and those of the settings file it doesn't set. The file is read,
    not sourced: it holds settings, not commands."""
    settings = {name: environ[name] for name in SETTINGS if name in environ}
    if not path.is_file():
        return settings
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"([A-Z_]+)=(.*)", line)
        if match is None or match.group(1) not in SETTINGS:
            raise InstanceError(f"{path}: not a setting of the test instance: {line}")
        settings.setdefault(match.group(1), match.group(2))
    return settings


def steam2(steam_id: str) -> str:
    """A SteamID as STEAM_0:Y:Z, the form SourceBans++ matches admins by (SourceMod takes all forms
    itself), converted as SourceMod's AdminCache::GetUnifiedSteamIdentity does."""
    account = None
    if match := re.fullmatch(r"STEAM_[0-5]:([01]):([0-9]+)", steam_id):
        return f"STEAM_0:{match.group(1)}:{int(match.group(2))}"
    if match := re.fullmatch(r"\[U:1:([0-9]+)\]", steam_id):
        account = int(match.group(1))
    elif re.fullmatch(r"[0-9]{17}", steam_id):
        number = int(steam_id)
        # An individual account (type 1) of a valid universe (1-4), instance up to 4 (web)
        universe, kind = number >> 56, (number >> 52) & 0xF
        instance = (number >> 32) & 0xFFFFF
        if 1 <= universe <= 4 and kind == 1 and instance <= 4:
            account = number & 0xFFFFFFFF
    if account is None or not 0 < account <= 0xFFFFFFFF:
        raise InstanceError(
            "TEST_ADMIN has no SteamID like STEAM_0:0:123, [U:1:246] or "
            f"76561197960265974: {steam_id}"
        )
    return f"STEAM_0:{account & 1}:{account >> 1}"


def password() -> str:
    return secrets.token_urlsafe(18).replace("-", "").replace("_", "")


def config_folder(config: str, repository: Path = REPOSITORY) -> Path:
    """A config's folder, of servers/ or tests/integration/servers/: its server.toml has the server's
    settings."""
    for folder in (repository / "servers", repository / "tests/integration/servers"):
        if (folder / config / "server.toml").is_file():
            return folder / config
    raise InstanceError(f"no config {config} in servers/ or tests/integration/servers/")


def config_mounts(configs: list[str], repository: Path = REPOSITORY) -> list[str]:
    """The mounts of the tests' configs among the image's, for a container."""
    mounts = []
    for config in configs:
        folder = config_folder(config, repository)
        if folder.parent == repository / "tests/integration/servers":
            mounts += ["-v", f"{folder}:/opt/nwi-server-kit/servers/{config}:ro"]
    return mounts


@dataclass
class Up:
    """up's options."""

    config: str = "coop-commando"
    db_only: bool = False
    launch_options: list[str] = field(default_factory=list)


def parse_up(args: list[str], settings: Mapping[str, str]) -> Up:
    up = Up(launch_options=settings.get("LAUNCH_OPTIONS", "").split())
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--db-only":
            up.db_only = True
        elif arg == "--developer":
            level = args[index + 1] if index + 1 < len(args) else ""
            if not level.isdigit():
                raise InstanceError("--developer needs a level, e.g. --developer 2")
            up.launch_options += ["+developer", level]
            index += 1
        elif arg == "--":
            up.launch_options += args[index + 1 :]
            break
        elif arg.startswith("-"):
            raise InstanceError(f"unknown option {arg}")
        else:
            up.config = arg
        index += 1
    for option in up.launch_options:
        # One option a word: the environment file separates them by spaces
        if not option or re.search(r"\s", option):
            raise InstanceError(f"a launch option with a space or empty: {option!r}")
    return up


def server_env(admins: list[str], launch_options: list[str]) -> str:
    """The server's environment file of the test instance."""
    lines = [
        # A client port other than the game's 27005, which a client on this machine sends from
        "SERVER_PORT=27015",
        "TV_PORT=27020",
        "CLIENT_PORT=27025",
        "SERVER_PASSWORD=",
        "SOURCEBANS_SERVER_IP=127.0.0.1",
        f"RCON_PASSWORD={password()}",
    ]
    # For admins_simple.ini (nwi-server prepare) and the command line (nwi-server start)
    if admins:
        lines.append(f"TEST_ADMIN={' '.join(admins)}")
    if launch_options:
        lines.append(f"LAUNCH_OPTIONS={' '.join(launch_options)}")
    return "\n".join(lines) + "\n"


def instance_sql(game: str, admins: list[str]) -> tuple[str, str]:
    """The test server, of its game's mod, which the panel has for Insurgency but not for Day of
    Infamy, and root on it for the admins for SourceMod and SourceBans++, without a web panel login
    (the password isn't a hash); SourceBans++'s admin names are unique."""
    name = "Day of Infamy" if game == "doi" else "Insurgency"
    server = (
        "-- The test server, which SourceBans++ finds by its address (SOURCEBANS_SERVER_IP) and port,\n"
        "-- of its game's mod\n"
        "INSERT IGNORE INTO sb_mods (mid, name, icon, modfolder, steam_universe, enabled) VALUES\n"
        f"(100, '{name}', 'web.png', '{game}', 0, 1);\n"
        "INSERT INTO sb_servers (sid, ip, port, rcon, modid, enabled)\n"
        f"SELECT 1, '127.0.0.1', 27015, '', mid, 1 FROM sb_mods WHERE modfolder = '{game}';\n"
    )
    root = ""
    for number, admin in enumerate(admins, 1):
        root += (
            "INSERT INTO sm_admins (authtype, identity, password, flags, name, immunity) VALUES\n"
            f"('steam', '{admin}', NULL, 'z', 'Test admin {number}', 100);\n"
            "INSERT INTO sb_admins (user, authid, password, gid, email, extraflags, immunity, "
            "srv_flags) VALUES\n"
            f"('Test admin {number}', '{admin}', '!', -1, '', 0, 100, 'z');\n"
            "INSERT INTO sb_admins_servers_groups (admin_id, group_id, srv_group_id, server_id)\n"
            f"SELECT aid, 0, -1, 1 FROM sb_admins WHERE authid = '{admin}';\n"
        )
    return server, root


def databases_cfg(db_password: str, port: int) -> str:
    """SourceMod's databases.cfg of the test's database."""
    text = '"Databases"\n{\n\t"driver_default"\t"mysql"\n'
    for entry in ("default", "sourcebans", "clientprefs"):
        text += (
            f'\n\t"{entry}"\n\t{{\n\t\t"driver"\t"mysql"\n\t\t"host"\t"127.0.0.1"\n'
            f'\t\t"port"\t"{port}"\n\t\t"database"\t"doi"\n\t\t"user"\t"doi"\n'
            f'\t\t"pass"\t"{db_password}"\n\t}}\n'
        )
    text += '\n\t"storage-local"\n\t{\n\t\t"driver"\t"sqlite"\n\t\t"database"\t"sourcemod-local"\n\t}\n}\n'
    return text


def run(*args: str, capture: bool = False, check: bool = True) -> str:
    """Run a command; its output with CAPTURE."""
    result = subprocess.run(
        args, check=check, text=True, stdout=subprocess.PIPE if capture else None
    )
    return result.stdout if capture else ""


def succeeds(*args: str) -> bool:
    return (
        subprocess.run(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def find_repo(settings: Mapping[str, str]) -> tuple[str, Path]:
    """The local repository's name and folder."""
    if succeeds("sh", "-c", "command -v aur"):
        status = run("aur", "repo", "--status", capture=True)
        values = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
        name, root = values.get("repo", ""), Path(values.get("root", ""))
    else:
        wanted = settings.get("AUR_REPO")
        found = []
        for repo in run("pacman-conf", "--repo-list", capture=True).split():
            if wanted and repo != wanted:
                continue
            servers = run("pacman-conf", f"--repo={repo}", "Server", capture=True)
            server = (servers.splitlines() or [""])[0]
            if server.startswith("file://"):
                found.append((repo, Path(server.removeprefix("file://").rstrip("/"))))
        if wanted and not found:
            raise InstanceError(
                f"pacman.conf has no local (file://) repository {wanted}"
            )
        if len(found) != 1:
            names = " ".join(repo for repo, _ in found)
            raise InstanceError(
                f"{len(found)} local repositories in pacman.conf ({names}), name one with AUR_REPO"
            )
        name, root = found[0]
        root = Path(settings.get("AUR_DBROOT") or root)
    if not (root / f"{name}.db").is_file():
        raise InstanceError(f"no database of the repository {name} in {root}")
    return name, root


def repo_key(name: str, root: Path) -> str:
    """The fingerprint of the key the repository's database is signed with."""
    database = root / f"{name}.db"
    status = subprocess.run(
        [
            "gpg",
            "--homedir",
            GNUPG,
            "--no-permission-warning",
            "--status-fd",
            "1",
            "--verify",
            f"{database}.sig",
            str(database),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    ).stdout
    for line in status.splitlines():
        if line.startswith("[GNUPG:] VALIDSIG "):
            return line.split()[2]
    raise InstanceError(f"the database of {name} in {root} has no valid signature")


class Instance:
    """The test instance of this machine, with its settings."""

    def __init__(self, settings: Mapping[str, str]) -> None:
        self.settings = settings
        state_home = Path(
            os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state"
        )
        self.dir = Path(settings.get("NWI_TEST_DIR") or state_home / "nwi-test")
        self.state = Path(settings.get("NWI_STATE") or state_home / "nwi-server")
        self.server_image = SANITISER_IMAGE if settings.get("SANITISER") else IMAGE
        self.db_port = int(settings.get("TEST_DB_PORT") or 3306)

    @property
    def local(self) -> bool:
        repo = self.settings.get("NWI_TEST_REPO", "public")
        if repo not in ("public", "local"):
            raise InstanceError(f"NWI_TEST_REPO is public or local, not {repo}")
        return repo == "local"

    def build(self, args: list[str]) -> None:
        testing: list[str] = []
        local = self.local
        while args[:1] in (["--testing"], ["--local"]):
            if args[0] == "--testing":
                testing = ["--build-arg", "TESTING=1"]
            else:
                local = True
            args = args[1:]
        with tempfile.TemporaryDirectory() as work:
            repo: list[str] = []
            if local:
                name, root = find_repo(self.settings)
                key = Path(work) / "repo-key.asc"
                key.write_text(
                    run(
                        "gpg",
                        "--homedir",
                        GNUPG,
                        "--no-permission-warning",
                        "--export",
                        "-a",
                        repo_key(name, root),
                        capture=True,
                    )
                )
                repo = [
                    "--build-arg",
                    f"REPO_NAME={name}",
                    "--build-arg",
                    "REPO_SERVER=file:///mnt/repo",
                ]
            else:
                # The public repository needs no folder: an empty one for the build context
                root, key = Path(work), PUBLIC_KEY
            run(
                "podman",
                "build",
                "--format",
                "docker",
                "--build-context",
                f"repo={root}",
                "--secret",
                f"id=repo-key,src={key}",
                *repo,
                *testing,
                "-f",
                str(REPOSITORY / "deploy/container/Containerfile"),
                "-t",
                IMAGE,
                str(REPOSITORY),
                *args,
            )

    def sourcebans_package(self, work: Path) -> Path:
        """The package of SourceBans++'s web panel: the local repository's newest, or the public one's,
        downloaded and verified with its key."""
        if self.local:
            _, root = find_repo(self.settings)
            packages = sorted(
                root.glob(f"{SOURCEBANS}-[0-9]*.pkg.tar.zst"), key=version_key
            )
            if not packages:
                raise InstanceError(
                    f"{root} has no {SOURCEBANS} package with SourceBans++'s tables"
                )
            return packages[-1]
        database = work / f"{PUBLIC_REPO}.db"
        download(f"{PUBLIC_URL}/{PUBLIC_REPO}.db", database)
        name = package_file(database, SOURCEBANS)
        package = work / name
        download(f"{PUBLIC_URL}/{name}", package)
        download(f"{PUBLIC_URL}/{name}.sig", Path(f"{package}.sig"))
        verify(package, work)
        return package

    def update(self, configs: list[str]) -> None:
        mounts = config_mounts(configs)
        if not succeeds("podman", "image", "exists", IMAGE):
            raise InstanceError(f"no image {IMAGE}, build it first: instance.py build")
        # The configs' games and items (nwi-server games), without the servers' environment files: all
        # configs' without configs
        env = ["-e", f"NWI_SERVER_CONFIGS={' '.join(configs)}"] if configs else []
        self.state.mkdir(parents=True, exist_ok=True)
        run(
            "podman",
            "run",
            "--rm",
            "--userns",
            USERNS,
            "--health-cmd",
            "none",
            *env,
            *mounts,
            "-v",
            f"{self.state}:/srv/state",
            IMAGE,
            "update",
        )

    def write_database(self, game: str, admins: list[str], db_only: bool) -> None:
        """The tables of SourceBans++ (from the web panel's package, its placeholders filled in),
        SourceMod's admins and client preferences (from the image, or this machine's SourceMod for the
        systemd units), the test server and the admins."""
        init = self.dir / "init"
        init.mkdir(parents=True, exist_ok=True)
        # The downloads apart from the database's scripts: MariaDB's entrypoint takes an archive among
        # them for a backup to restore
        downloads = self.dir / "downloads"
        downloads.mkdir(exist_ok=True)
        package = self.sourcebans_package(downloads)
        # One at a time: the tables have to come before their data
        tables = "".join(
            run(
                "bsdtar",
                "-xOf",
                str(package),
                f"usr/share/sourcebans-pp/install/includes/sql/{sql}",
                capture=True,
            )
            for sql in ("struc.sql", "data.sql")
        )
        (init / "01-sourcebans.sql").write_text(
            tables.replace("{prefix}", "sb").replace("{charset}", "utf8mb4")
        )
        scripts = [
            str(SOURCEMOD_SQL / "create_admins.sql"),
            str(SOURCEMOD_SQL / "clientprefs-mysql.sql"),
        ]
        cat = (
            ["cat"]
            if db_only
            else ["podman", "run", "--rm", "--entrypoint", "cat", IMAGE]
        )
        (init / "02-sourcemod.sql").write_text(run(*cat, *scripts, capture=True))
        server, root_sql = instance_sql(game, admins)
        (init / "03-test.sql").write_text(server)
        (init / "04-admin.sql").write_text(root_sql)

    def wait(
        self, container: str, check: list[str], interval: float, what: str
    ) -> None:
        while not succeeds("podman", "exec", container, *check):
            running = run(
                "podman",
                "inspect",
                "-f",
                "{{.State.Running}}",
                container,
                capture=True,
                check=False,
            ).strip()
            if running != "true":
                raise InstanceError(f"the {what} stopped, see podman logs {container}")
            time.sleep(interval)

    def up(self, args: list[str]) -> None:
        up = parse_up(args, self.settings)
        folder = config_folder(up.config)
        mounts = config_mounts([up.config])
        if up.db_only and mounts:
            raise InstanceError(
                f"{up.config} is a test's config, which runs in the container only"
            )
        game = run(
            sys.executable,
            "-m",
            "nwi_server_kit",
            "server-config",
            "game",
            str(folder / "server.toml"),
            capture=True,
        ).strip()
        admins = [
            steam2(admin) for admin in self.settings.get("TEST_ADMIN", "").split()
        ]
        if not up.db_only:
            if not succeeds("podman", "image", "exists", self.server_image):
                raise InstanceError(
                    f"no image {self.server_image}, build it first (see docs/kit/Testing.md)"
                )
            if not os.access(
                self.state / "servers" / up.config / "game/srcds_linux", os.X_OK
            ):
                raise InstanceError(
                    f"no {game} in {self.state}, download it first: instance.py update"
                )
        if succeeds("podman", "pod", "exists", POD):
            raise InstanceError(
                "the test instance is running, remove it first: instance.py down"
            )
        self.remove_dir()
        # The test's passwords, for the user only: the containers get the files bind-mounted
        self.dir.mkdir(mode=0o700, parents=True)
        db_password = password()
        (self.dir / "db.env").write_text(
            f"MARIADB_DATABASE=doi\nMARIADB_USER=doi\nMARIADB_PASSWORD={db_password}\n"
            "MARIADB_RANDOM_ROOT_PASSWORD=1\n"
        )
        (self.dir / "server.env").write_text(server_env(admins, up.launch_options))
        self.write_database(game, admins, up.db_only)
        configs = self.dir / "secrets/addons/sourcemod/configs"
        configs.mkdir(parents=True)
        # The server of the systemd units reaches the database at its port on this machine, the
        # container's within the pod
        (configs / "databases.cfg").write_text(
            databases_cfg(db_password, self.db_port if up.db_only else 3306)
        )
        # A private address of the pod's own: by default, rootless Podman's pasta gives the pod the
        # host's address, and the server ignores connections that seem to come from its own address
        ports = (
            ["-p", f"127.0.0.1:{self.db_port}:3306/tcp"]
            if up.db_only
            else [
                "-p",
                "27015:27015/udp",
                "-p",
                "27015:27015/tcp",
                "-p",
                "27020:27020/udp",
            ]
        )
        run(
            "podman",
            "pod",
            "create",
            "--name",
            POD,
            "--userns",
            USERNS,
            "--network",
            "pasta:-a,10.0.2.100,-n,24,-g,10.0.2.2",
            *ports,
            capture=True,
        )
        # The database on a tmpfs: it's the test's only, and with the pod's user namespace for the
        # server, a volume would belong to an ID that MariaDB's user isn't
        run(
            "podman",
            "run",
            "-d",
            "--pod",
            POD,
            "--name",
            f"{POD}-db",
            "--env-file",
            str(self.dir / "db.env"),
            "--tmpfs",
            "/var/lib/mysql:rw,mode=1777",
            "-v",
            f"{self.dir / 'init'}:/docker-entrypoint-initdb.d:ro",
            "docker.io/library/mariadb:lts",
            capture=True,
        )
        print("Waiting for the database")
        self.wait(
            f"{POD}-db",
            ["healthcheck.sh", "--connect", "--innodb_initialized"],
            2,
            "database",
        )
        if up.db_only:
            self.print_db_only(up.config)
            return
        self.start_server(up.config, mounts)

    def print_db_only(self, config: str) -> None:
        print(
            f"The database of the test instance of {config} is up at 127.0.0.1:{self.db_port}. For "
            f"nwi-server@{config}.service, its settings and its database as a credential, which "
            "stays plain for the test (systemd-creds encrypt for a real server), as root; its RCON "
            f"password is a new one at every start (nwi-rcon --server {config}):"
        )
        # The settings without the passwords, which the container's environment has
        settings = [
            line
            for line in (self.dir / "server.env").read_text().splitlines()
            if not line.startswith(("RCON_PASSWORD=", "SERVER_PASSWORD="))
        ]
        systemd_env = self.dir / "server-systemd.env"
        systemd_env.write_text("\n".join(settings) + "\n")
        databases = self.dir / "secrets/addons/sourcemod/configs/databases.cfg"
        print(
            f"\n  install -D -m 644 {shlex.quote(str(systemd_env))} /etc/nwi-server/{config}.env"
        )
        print(
            f"  install -D -m 600 {shlex.quote(str(databases))} "
            f"/etc/credstore/nwi-server@{config}.sourcemod-databases"
        )

    def start_server(self, config: str, mounts: list[str]) -> None:
        servers = self.state / "servers" / config
        volumes = [
            arg
            for name, path in VOLUMES.items()
            for arg in ("-v", f"{POD}-{name}:{path}")
        ]
        geoip = (
            ["-v", "/var/lib/GeoIP:/var/lib/GeoIP:ro"]
            if Path("/var/lib/GeoIP").is_dir()
            else []
        )
        # Plugins nwi-server prepare disables, e.g. for checks/dump_cvars.py, and the sanitisers nwi-server
        # start preloads the runtime of
        env = [
            arg
            for name in ("DISABLE_PLUGINS", "SANITISER")
            if self.settings.get(name)
            for arg in ("-e", f"{name}={self.settings[name]}")
        ]
        # The state's game and workshop items with an overlay of the container's own, its mods read-only
        run(
            "podman",
            "run",
            "-d",
            "--pod",
            POD,
            "--name",
            f"{POD}-server",
            "--env-file",
            str(self.dir / "server.env"),
            "-e",
            f"SERVER_NAME={config}",
            *env,
            *mounts,
            "-v",
            f"{servers / 'game'}:/srv/game:O",
            "-v",
            f"{servers / 'workshop/steamapps/workshop'}:/srv/game/steamapps/workshop:O",
            "-v",
            f"{servers / 'mods'}:/srv/mods:ro",
            "-v",
            f"{self.state}:/srv/layers:ro",
            "-v",
            f"{servers / 'depots'}:/srv/depots.list:ro",
            "-v",
            f"{self.dir / 'secrets'}:/run/secrets/nwi-server:ro",
            *geoip,
            *volumes,
            "--health-on-failure",
            "restart",
            self.server_image,
            capture=True,
        )
        print("Waiting for the server")
        self.wait(
            f"{POD}-server",
            [
                "python3",
                "-m",
                "nwi_server_kit",
                "watchdog",
                "--check",
                "--port",
                "27015",
                "--timeout",
                "2",
            ],
            3,
            "server",
        )
        # The server drops connections from 127.0.0.1, which pasta passes on from the pod's own address
        route = run("ip", "-4", "route", "get", "192.0.2.1", capture=True, check=False)
        match = re.search(r" src ([0-9.]+)", route)
        address = match.group(1) if match else "<the host address>"
        print(
            f"The test instance of {config} is up: connect {address}:27015 (not 127.0.0.1), "
            "RCON with instance.py rcon"
        )

    def remove_dir(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def down(self) -> None:
        # The server's shutdown takes up to about 10 seconds, Podman's own grace before it kills: the
        # Quadlet unit's (StopTimeout=30)
        run("podman", "pod", "stop", "--ignore", "-t", "30", POD, capture=True)
        run("podman", "pod", "rm", "-f", "--ignore", POD, capture=True)
        for name in VOLUMES:
            subprocess.run(
                ["podman", "volume", "rm", "-f", f"{POD}-{name}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        self.remove_dir()

    def rcon_password(self) -> str:
        for line in (self.dir / "server.env").read_text().splitlines():
            if line.startswith("RCON_PASSWORD="):
                return line.removeprefix("RCON_PASSWORD=")
        raise InstanceError("the test instance has no RCON password: is it up?")

    def rcon(self, args: list[str]) -> int:
        env = os.environ | {
            "RCON_PASSWORD": self.rcon_password(),
            "PYTHONPATH": str(REPOSITORY / "src"),
        }
        return subprocess.run(
            [sys.executable, "-m", "nwi_server_kit", "rcon", *args],
            env=env,
            check=False,
        ).returncode

    def logs(self) -> int:
        return subprocess.run(
            ["podman", "logs", "-f", f"{POD}-server"], check=False
        ).returncode

    def soak(self, args: list[str]) -> int:
        hours = "8"
        if args[:1] == ["--hours"]:
            if len(args) < 2:
                raise InstanceError("--hours needs a number")
            hours, args = args[1], args[2:]
        log = Path(args[0] if args else f"soak-{time.strftime('%Y%m%d-%H%M')}.tsv")
        self.update(["soak-bots"])
        self.up(["soak-bots"])
        # The server's output next to the log, and the test instance removed, also when it's stopped early
        output = log.with_suffix(".log") if log.suffix == ".tsv" else Path(f"{log}.log")
        try:
            print(
                f"Watching the soak test for {hours} hours: {log}, the server's output in {output}"
            )
            env = os.environ | {"RCON_PASSWORD": self.rcon_password()}
            return subprocess.run(
                [
                    sys.executable,
                    str(REPOSITORY / "tests/integration/soak_watch.py"),
                    "--container",
                    f"{POD}-server",
                    "--hours",
                    hours,
                    str(log),
                ],
                env=env,
                check=False,
            ).returncode
        finally:
            with output.open("w") as file:
                subprocess.run(
                    ["podman", "logs", f"{POD}-server"],
                    stdout=file,
                    stderr=file,
                    check=False,
                )
            self.down()

    def stress(self, args: list[str]) -> int:
        """The stress test of a config, see the usage and tests/integration/stress.py."""
        options: list[str] = []
        while args[:1] in (["--seconds"], ["--rate"], ["--floods"]):
            if len(args) < 2:
                raise InstanceError(f"{args[0]} needs a number")
            options, args = [*options, *args[:2]], args[2:]
        if len(args) > 1:
            raise InstanceError(
                "stress [--seconds SECONDS] [--rate RATE] [--floods FLOOD,...] [CONFIG]"
            )
        config = args[0] if args else "coop-commando"
        tickrate = str(server_settings(config).get("tickrate", 128))
        self.update([config])
        self.up([config])
        try:
            # A flood without the table can fill the connection table so that the server's own
            # watchdog gets no answer and aborts it: the server comes back for the next flood
            run(
                "podman", "update", "--restart", "on-failure", f"{POD}-server",
                capture=True,
            )  # fmt: skip
            infra = run(
                "podman", "pod", "inspect", "--format", "{{.InfraContainerID}}", POD,
                capture=True,
            ).strip()  # fmt: skip
            pid = run(
                "podman", "inspect", "--format", "{{.State.Pid}}", infra, capture=True
            ).strip()
            # As root of rootless Podman's user namespace, which owns the pod's network namespace
            status = subprocess.run(
                [
                    "podman",
                    "unshare",
                    sys.executable,
                    str(REPOSITORY / "tests/integration/stress.py"),
                    "--pod-pid",
                    pid,
                    "--tickrate",
                    tickrate,
                    *options,
                    str(REPOSITORY / "deploy/nftables/nwi-game-ports.nft"),
                ],
                env=os.environ | {"RCON_PASSWORD": self.rcon_password()},
                check=False,
            ).returncode
            logs = subprocess.run(
                ["podman", "logs", f"{POD}-server"],
                capture_output=True,
                text=True,
                check=False,
            )
            reports = [
                line
                for line in (logs.stdout + logs.stderr).splitlines()
                if REPORT.search(line)
            ]
            if reports:
                print(
                    f"FAILED: {len(reports)} sanitiser reports in the server's output, the first: "
                    f"{reports[0]}",
                    file=sys.stderr,
                )
                return 1
            return status
        finally:
            self.down()

    def dump_cvars(self, args: list[str]) -> int:
        """The dump of a game's cvars and commands, see the usage and checks/dump_cvars.py."""
        descriptions = args[:1] == ["--with-descriptions"]
        args = args[1:] if descriptions else args
        if len(args) != 1 or args[0] not in DUMP_CONFIGS:
            raise InstanceError(
                f"dump-cvars [--with-descriptions] GAME: GAME is one of {', '.join(DUMP_CONFIGS)}"
            )
        game, config = args[0], DUMP_CONFIGS[args[0]]
        disabled = self.settings.get("DISABLE_PLUGINS", "").split()
        self.settings = {
            **self.settings,
            "DISABLE_PLUGINS": " ".join([*disabled, "nwi_cvar_unlocker"]),
        }
        self.update([config])
        self.up([config])
        cvars = REPOSITORY / "checks/cvars"
        options = (
            ["--descriptions", str(cvars / "descriptions" / f"{game}.json")]
            if descriptions
            else []
        )
        try:
            with (cvars / f"{game}.json").open("w") as output:
                return subprocess.run(
                    [
                        sys.executable,
                        str(REPOSITORY / "checks/dump_cvars.py"),
                        *options,
                    ],
                    env=os.environ | {"RCON_PASSWORD": self.rcon_password()},
                    stdout=output,
                    check=False,
                ).returncode
        finally:
            self.down()

    def rounds(self, args: list[str]) -> int:
        """The round test of each config, see the usage and tests/integration/rounds.py."""
        configs = args or ["coop-commando", "soak-bots"]
        self.update(configs)
        failed = []
        for config in configs:
            settings = server_settings(config)
            game = str(settings.get("game", "doi"))
            startup_map = str(settings.get("startup_map", "")).split(" ")[0]
            if not startup_map:
                raise InstanceError(f"{config} has no startup_map")
            self.up([config])
            try:
                result = self.round_test(config, game, startup_map)
            finally:
                self.down()
            print(f"{config}: {'passed' if result.passed else 'FAILED'}")
            for seconds, event in result.events:
                print(f"  {seconds:4d} s  {event}")
            if result.teams is not None:
                teams = result.teams
                print(
                    f"  teams: {teams.bots[0]} and {teams.bots[1]} bots, "
                    f"{teams.deaths} deaths, game state {teams.state}"
                )
            for failure in result.failures:
                print(f"  {failure}")
            if not result.passed:
                failed.append(config)
        if failed:
            print(f"Failed: {', '.join(failed)}", file=sys.stderr)
        return 1 if failed else 0

    def round_test(
        self, config: str, game: str, startup_map: str
    ) -> "round_checks.Result":
        """Put the test plugin into the running server, compiled by its spcomp, and run the test."""
        server = f"{POD}-server"
        sourcemod = f"/srv/game/{game}/addons/sourcemod"
        run(
            "podman",
            "cp",
            str(round_checks.PLUGIN),
            f"{server}:/tmp/nwi_test_rounds.sp",
        )
        run(
            "podman",
            "exec",
            server,
            "spcomp",
            "-o",
            f"{sourcemod}/plugins/nwi_test_rounds.smx",
            "/tmp/nwi_test_rounds.sp",
            capture=True,
        )
        password = self.rcon_password()

        def command(text: str) -> str:
            sock = rcon_client.connect("127.0.0.1", 27015, password)
            with sock:
                return rcon_client.run(sock, text)

        def read(pattern: str) -> str:
            return run(
                "podman",
                "exec",
                server,
                "sh",
                "-c",
                f"cat {sourcemod}/logs/{pattern} 2>/dev/null || true",
                capture=True,
            )

        command("sm plugins load nwi_test_rounds")
        return round_checks.run(
            command,
            lambda: read("L*.log"),
            lambda: read("errors_*.log"),
            round_checks.is_coop(config_folder(config) / "server.toml"),
            startup_map,
            game,
        )


def server_settings(config: str) -> dict[str, object]:
    """A config's server.toml."""
    with (config_folder(config) / "server.toml").open("rb") as file:
        return tomllib.load(file)


def download(url: str, target: Path) -> None:
    try:
        with urllib.request.urlopen(url, timeout=60) as answer:
            target.write_bytes(answer.read())
    except OSError as error:
        raise InstanceError(f"{url}: {error}") from error


def package_file(database: Path, name: str) -> str:
    """The file of a package of a pacman repository's database, by its name."""
    with tarfile.open(database) as archive:
        for member in archive:
            if not member.name.endswith("/desc"):
                continue
            file = archive.extractfile(member)
            text = file.read().decode() if file else ""
            values = dict(re.findall(r"%([A-Z]+)%\n([^\n]*)", text))
            if values.get("NAME") == name and "FILENAME" in values:
                return values["FILENAME"]
    raise InstanceError(f"the public repository has no {name}")


def verify(path: Path, work: Path) -> None:
    """Verify a file's signature (<file>.sig) with the public repository's key, by its fingerprint."""
    with tempfile.TemporaryDirectory(dir=work) as home:
        run(
            "gpg",
            "--homedir",
            home,
            "--quiet",
            "--import",
            str(PUBLIC_KEY),
            capture=True,
        )
        status = subprocess.run(
            [
                "gpg",
                "--homedir",
                home,
                "--status-fd",
                "1",
                "--verify",
                f"{path}.sig",
                str(path),
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ).stdout
    if f"[GNUPG:] VALIDSIG {PUBLIC_FINGERPRINT} " not in status:
        raise InstanceError(
            f"{path.name} isn't signed with the public repository's key"
        )


def version_key(path: Path) -> list[int | str]:
    """A package's file name, sorted by its version as sort -V does."""
    return [
        int(part) if part.isdigit() else part for part in re.split(r"(\d+)", path.name)
    ]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    usage = __doc__.split("Usage:")[1].split("\n\n")[0] if __doc__ else ""
    if not args or args[0] not in (
        "build",
        "update",
        "up",
        "down",
        "rcon",
        "logs",
        "soak",
        "rounds",
        "stress",
        "dump-cvars",
    ):
        print(f"Usage:{usage}", file=sys.stderr)
        return 2
    command, rest = args[0], args[1:]
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    os.environ["PYTHONPATH"] = str(REPOSITORY / "src")
    try:
        instance = Instance(
            read_settings(config_home / "nwi-server-kit/test-instance.env", os.environ)
        )
        if command == "build":
            instance.build(rest)
        elif command == "update":
            instance.update(rest)
        elif command == "up":
            instance.up(rest)
        elif command == "down":
            instance.down()
        elif command == "rcon":
            return instance.rcon(rest)
        elif command == "logs":
            return instance.logs()
        elif command == "rounds":
            return instance.rounds(rest)
        elif command == "stress":
            return instance.stress(rest)
        elif command == "dump-cvars":
            return instance.dump_cvars(rest)
        else:
            return instance.soak(rest)
    except InstanceError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(
            f"Error: {shlex.join(map(str, error.cmd))} failed ({error.returncode})",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
