"""The round test of a config on a Windows server, over SSH (instance.py windows-rounds): the Windows
builds of the games, SourceMod and Metamod:Source, with the gamedata of windows and windows64, which
the Linux servers never run.

The machine needs OpenSSH's server, whose shell runs PowerShell, and an install of the game with
Metamod:Source, which the test changes while it runs, so one of the tests'. The test makes the server's
files here, as the container does (container.assemble, launch.prepare): a SourceMod package from the
machine (e.g. a build of patches/sourcemod), game/common, game/<game>, the config's mods of the state
and the config. The repository's plugins and the round test's are compiled on the machine, by the
package's spcomp: a 64-bit server needs plugins of SourceMod 1.13's compiler, the servers' of Linux
are of 1.12's.
Without a database, SourceBans++ isn't there. It copies them into the install, keeping the files they
replace, starts the server detached, through WMI, as a process of SSH's session would end with it,
under ProcDump if the machine has it, which writes a dump at a crash, and runs the round test
(rounds.py) with RCON through an SSH tunnel, as the machine's firewall needn't let it in. Then it stops
the server and puts the install's files back; the server's logs stay, until the next run. A run that
was cut short is undone at the next one's start.

The workshop items aren't copied: the server downloads them itself, as on a Windows server, into the
install's steamapps/workshop, which keeps them for the next runs. The first run of a config with many
takes a while.
"""

import base64
import os
import secrets
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from nwi_server_kit import launch, rcon, server_config
from tests.integration import rounds

# The work folder of a run in the install: what it copied, the files it replaced and the dumps
WORK = ".nwi-test"
# Seconds for the server to answer RCON: its first start downloads the config's workshop items
START_SECONDS = 1800

# The scripts on the machine, each after the assignments of its variables (powershell()): $Install, the
# install's folder (with srcds.exe), and $Work, the run's in it
PREAMBLE = """\
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Stage = Join-Path $Work "stage"
$Originals = Join-Path $Work "originals"
$Manifest = Join-Path $Work "files.txt"
function Relative($Path, $Root) { $Path.Substring($Root.Length).TrimStart("\\", "/") }
"""

# Stop the install's server and ProcDump
STOP = """\
Get-CimInstance Win32_Process | Where-Object {
    ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($Install, [StringComparison]::OrdinalIgnoreCase)) -or
    ($_.Name -like "procdump*" -and $_.CommandLine -like "*$Install*")
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep 2
"""

# Put the install's files back: remove those the run copied, then move back those they replaced; an
# original is moved away before its file is listed, so that a run cut short loses none
RESTORE = """\
if (Test-Path -LiteralPath $Manifest) {
    foreach ($relative in Get-Content -LiteralPath $Manifest) {
        $target = Join-Path $Install $relative
        if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Force }
    }
    Remove-Item -LiteralPath $Manifest -Force
}
if (Test-Path -LiteralPath $Originals) {
    $root = (Resolve-Path -LiteralPath $Originals).Path
    foreach ($file in Get-ChildItem -LiteralPath $Originals -Recurse -File) {
        $target = Join-Path $Install (Relative $file.FullName $root)
        New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
        Move-Item -LiteralPath $file.FullName $target -Force
    }
    Remove-Item -LiteralPath $Originals -Recurse -Force
}
if (Test-Path -LiteralPath $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force }
New-Item -ItemType Directory -Force $Stage | Out-Null
"""

# Copy the staged files into the install
APPLY = """\
$root = (Resolve-Path -LiteralPath $Stage).Path
$listed = [Collections.Generic.List[string]]::new()
foreach ($file in Get-ChildItem -LiteralPath $Stage -Recurse -File) {
    $relative = Relative $file.FullName $root
    $target = Join-Path $Install $relative
    if (Test-Path -LiteralPath $target) {
        $original = Join-Path $Originals $relative
        New-Item -ItemType Directory -Force (Split-Path $original) | Out-Null
        Move-Item -LiteralPath $target $original
    }
    Add-Content -LiteralPath $Manifest $relative
    New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
    Copy-Item -LiteralPath $file.FullName $target
    $listed.Add($relative)
}
"copied $($listed.Count) files"
"""

# Compile the plugins of $Plugins (names, separated by semicolons) in the stage's game $Game with the
# compiler of its SourceMod, into plugins, or plugins/disabled for those of $Disabled
COMPILE = """\
$sourcemod = Join-Path $Stage "$Game\\addons\\sourcemod"
$scripting = Join-Path $sourcemod "scripting"
$compiler = "spcomp64.exe", "spcomp.exe" | ForEach-Object { Join-Path $scripting $_ } |
    Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $compiler) { throw "the SourceMod package has no spcomp" }
$disabled = $Disabled -split " "
foreach ($name in $Plugins -split ";") {
    $folder = if ($disabled -contains $name) { "plugins\\disabled" } else { "plugins" }
    $output = Join-Path $sourcemod "$folder\\$name.smx"
    New-Item -ItemType Directory -Force (Split-Path $output) | Out-Null
    $source = Join-Path $scripting "$name.sp"
    $include = "-i" + (Join-Path $scripting "include")
    # Its warnings on stderr aren't PowerShell's errors
    $ErrorActionPreference = "Continue"
    $log = & $compiler $include "-o$output" $source 2>&1
    $ErrorActionPreference = "Stop"
    if ($LASTEXITCODE -ne 0) { throw "spcomp failed on $name.sp: $($log -join "`n")" }
}
"compiled $(($Plugins -split ';').Count) plugins with $(Split-Path -Leaf $compiler)"
"""

# Start the server, detached, without the logs of an earlier run: $Executable, $Arguments, $Logs (the
# game's SourceMod logs) and $ProcDump, empty without
START = """\
Remove-Item (Join-Path $Install "$Logs\\*") -Force -ErrorAction SilentlyContinue
$line = '"' + (Join-Path $Install $Executable) + '" ' + $Arguments
$dumps = Join-Path $Work "dumps"
Remove-Item -LiteralPath $dumps -Recurse -Force -ErrorAction SilentlyContinue
if ($ProcDump) {
    New-Item -ItemType Directory -Force $dumps | Out-Null
    $line = '"' + $ProcDump + '" -accepteula -ma -e -x "' + $dumps + '" ' + $line
}
$result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = $line; CurrentDirectory = $Install
}
if ($result.ReturnValue -ne 0) { throw "the server didn't start: $($result.ReturnValue)" }
"""

# Whether the server runs, or ProcDump that starts it: their process IDs, nothing if neither does
RUNNING = """\
Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -like "srcds*" -and $_.ExecutablePath -and
        $_.ExecutablePath.StartsWith($Install, [StringComparison]::OrdinalIgnoreCase)) -or
    ($_.Name -like "procdump*" -and $_.CommandLine -like "*$Install*")
} | ForEach-Object { $_.ProcessId }
"""

# The SourceMod logs of $Pattern, in order
LOGS = """\
$folder = Join-Path $Install $Logs
if (Test-Path -LiteralPath $folder) {
    Get-ChildItem -LiteralPath $folder -Filter $Pattern | Sort-Object Name |
        ForEach-Object { [IO.File]::ReadAllText($_.FullName) }
}
"""

# The dumps of the run
DUMPS = """\
$dumps = Join-Path $Work "dumps"
if (Test-Path -LiteralPath $dumps) { Get-ChildItem -LiteralPath $dumps -File | ForEach-Object FullName }
"""


def quote(text: str) -> str:
    """A string of PowerShell, its value as it is."""
    return "'" + text.replace("'", "''") + "'"


def script(body: str, **variables: str) -> str:
    """A script of the machine: its variables, the preamble and the body."""
    assignments = "".join(
        f"${name} = {quote(value)}\n" for name, value in variables.items()
    )
    return assignments + PREAMBLE + body


def encoded(text: str) -> str:
    """A script for powershell -EncodedCommand: UTF-16LE in Base64, which no shell changes on its way."""
    return base64.b64encode(text.encode("utf-16-le")).decode("ascii")


def windows_command_line(arguments: list[str]) -> str:
    """Arguments as Windows' command line has them, quoted as its C runtime splits them."""
    return subprocess.list2cmdline(arguments)


@dataclass
class Host:
    """A Windows machine by its SSH destination, and the install of the game on it."""

    destination: str
    install: str

    @property
    def work(self) -> str:
        return self.install.rstrip("\\/") + "\\" + WORK

    def command(self, body: str, **variables: str) -> list[str]:
        """SSH's command line of a script on the machine, with the install's variables."""
        text = script(body, Install=self.install, Work=self.work, **variables)
        return [
            "ssh",
            "-o",
            "BatchMode=yes",
            self.destination,
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded(text),
        ]

    def powershell(self, body: str, **variables: str) -> str:
        """Run a script on the machine; its output."""
        result = subprocess.run(
            self.command(body, **variables), capture_output=True, check=False
        )
        output = result.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        if result.returncode != 0:
            error = result.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(
                f"{self.destination}: a script failed: {error or output}"
            )
        return output

    def fetch(self, folder: str, target: Path) -> None:
        """Copy a folder of the machine here, with its tar, which runs in the folder: no path on a
        command line, which PowerShell and cmd would both parse."""
        target.mkdir(parents=True, exist_ok=True)
        body = 'Set-Location -LiteralPath $Folder\ncmd /c "tar -cf - ."\n'
        with subprocess.Popen(
            self.command(body, Folder=folder), stdout=subprocess.PIPE
        ) as process:
            assert process.stdout is not None
            with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
                archive.extractall(target, filter="data")
        if process.returncode != 0:
            raise RuntimeError(f"{self.destination}: no folder {folder}")

    def upload(self, folder: Path) -> None:
        """Copy a folder's files into the run's stage, with the machine's tar."""
        body = (
            'Set-Location -LiteralPath $Stage\ncmd /c "tar -xf -"\nexit $LASTEXITCODE\n'
        )
        with subprocess.Popen(self.command(body), stdin=subprocess.PIPE) as process:
            assert process.stdin is not None
            with tarfile.open(fileobj=process.stdin, mode="w|") as archive:
                for path in sorted(folder.iterdir()):
                    archive.add(path, arcname=path.name)
            process.stdin.close()
        if process.returncode != 0:
            raise RuntimeError(f"{self.destination}: the files didn't arrive")


@contextmanager
def environment(values: dict[str, str]) -> Iterator[None]:
    """The environment with these values, the unit's credentials left out."""
    with mock.patch.dict(os.environ, values):
        os.environ.pop("CREDENTIALS_DIRECTORY", None)
        yield


@dataclass
class Stage:
    """The server's files, by the install's folders, and its options."""

    root: Path
    arguments: list[str]
    # The plugins to compile, by name, the repository's and the round test's
    plugins: list[str]


def stage(
    root: Path,
    game: str,
    config: Path,
    state: Path,
    packages: list[Path],
    repository: Path,
    password: str,
    port: int,
    settings: dict[str, str],
) -> Stage:
    """Make the server's files in ROOT, the install's folders, see the module's documentation: of the
    config's folder CONFIG, the config's folder of the state STATE (its mods, the config without the
    items it left out, the game's gameinfo.txt) and the SourceMod packages."""
    folder = root / game
    for package in packages:
        shutil.copytree(package, folder, dirs_exist_ok=True)
    for source in (
        repository / "game/common",
        repository / "game" / game,
        state / "mods",
        config,
        state / "config",
    ):
        if source.is_dir():
            shutil.copytree(source, folder, symlinks=False, dirs_exist_ok=True)
    scripting = folder / "addons/sourcemod/scripting"
    shutil.copyfile(rounds.PLUGIN, scripting / rounds.PLUGIN.name)
    plugins = sorted(
        path.stem
        for path in (repository / "game/common/addons/sourcemod/scripting").glob("*.sp")
    ) + [rounds.PLUGIN.stem]
    # The game's own files are the install's: gameinfo.txt only while prepare finds the game by it
    gameinfo = folder / "gameinfo.txt"
    shutil.copyfile(state / "game" / game / "gameinfo.txt", gameinfo)
    try:
        values = {
            "RCON_PASSWORD": password,
            "SERVER_PORT": str(port),
            "LAUNCH_OPTIONS": settings.get("LAUNCH_OPTIONS", ""),
            "TEST_ADMIN": settings.get("TEST_ADMIN", ""),
            "DISABLE_PLUGINS": settings.get("DISABLE_PLUGINS", ""),
        }
        # As launch.prepare, but SourceBans++'s, which isn't there, and without a folder of the
        # machine's RCON passwords
        with environment(values), mock.patch.object(rcon, "RCON_DIR", root / "no-rcon"):
            server_config.prepare(root)
            launch.configure_plugins(folder)
            launch.configure_geoip(folder)
            launch.add_test_admins(folder)
            launch.configure_secrets(folder, config.name)
            arguments = launch.command(root)[1:]
    finally:
        gameinfo.unlink()
    return Stage(root, ["-console", "-norestart", *arguments], plugins)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def tunnel(destination: str, port: int) -> Iterator[int]:
    """A local port to the machine's port, through SSH."""
    local = free_port()
    with subprocess.Popen(
        [
            "ssh",
            "-N",
            "-o",
            "BatchMode=yes",
            "-o",
            "ExitOnForwardFailure=yes",
            "-L",
            f"127.0.0.1:{local}:127.0.0.1:{port}",
            destination,
        ]
    ) as process:
        try:
            yield local
        finally:
            process.terminate()


def wait_for_rcon(
    connect: Callable[[], object],
    running: Callable[[], bool],
    seconds: float = START_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Wait until the server answers RCON; a RuntimeError if it ends or takes too long."""
    deadline = clock() + seconds
    while True:
        try:
            connect()
            return
        except OSError:
            pass
        if not running():
            raise RuntimeError("the server ended before it answered RCON")
        if clock() > deadline:
            raise RuntimeError(
                f"the server didn't answer RCON within {seconds:.0f} seconds"
            )
        sleep(10)


@dataclass
class Run:
    """A config's run on the machine: the round test's result and the dumps there."""

    result: rounds.Result
    dumps: list[str]


def run(
    host: Host,
    game: str,
    bits: int,
    config: Path,
    state: Path,
    packages: list[str],
    repository: Path,
    settings: dict[str, str],
    procdump: str = "",
    port: int = 27015,
) -> Run:
    """The round test of a config on the machine, see the module's documentation."""
    password = secrets.token_urlsafe(24)
    settings_toml = config / "server.toml"
    startup_map = str(server_config.load(settings_toml)["startup_map"]).split(" ")[0]
    host.powershell(STOP + RESTORE)
    with tempfile.TemporaryDirectory() as temporary:
        local = Path(temporary)
        fetched = []
        for index, package in enumerate(packages):
            target = local / f"package-{index}"
            host.fetch(package, target)
            fetched.append(target)
        staged = stage(
            local / "stage",
            game,
            config,
            state,
            fetched,
            repository,
            password,
            port,
            settings,
        )
        host.upload(staged.root)
    logs = f"{game}\\addons\\sourcemod\\logs"
    try:
        print(
            host.powershell(
                COMPILE,
                Game=game,
                Plugins=";".join(staged.plugins),
                Disabled=settings.get("DISABLE_PLUGINS", ""),
            ).strip()
        )
        print(host.powershell(APPLY).strip())
        host.powershell(
            START,
            Executable="srcds_x64.exe" if bits == 64 else "srcds.exe",
            Arguments=windows_command_line(staged.arguments),
            Logs=logs,
            ProcDump=procdump,
        )
        with tunnel(host.destination, port) as local_port:

            def command(text: str) -> str:
                with rcon.connect("127.0.0.1", local_port, password) as sock:
                    return rcon.run(sock, text)

            def read(pattern: str) -> str:
                return host.powershell(LOGS, Logs=logs, Pattern=pattern)

            try:
                wait_for_rcon(
                    lambda: command("status"),
                    lambda: bool(host.powershell(RUNNING).strip()),
                )
            except RuntimeError as error:
                result = rounds.Result(failures=[str(error)])
            else:
                if bits == 64:
                    # SourceMod's gamedata has no game rules of 64-bit Windows (sdktools.games)
                    command("nwi_test_rounds_game_state 0")
                result = rounds.run(
                    command,
                    lambda: read("L*.log"),
                    lambda: read("errors_*.log"),
                    rounds.is_coop(settings_toml),
                    startup_map,
                    game,
                )
    finally:
        host.powershell(STOP)
        dumps = host.powershell(DUMPS).split()
        host.powershell(RESTORE)
    return Run(result, dumps)
