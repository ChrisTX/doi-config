"""The round test on Windows (tests/integration/windows.py): the server's files it makes, its scripts of
the machine, run with PowerShell here on temporary folders, and its wait for the server."""

import base64
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.integration import instance, windows

REPOSITORY = Path(__file__).resolve().parents[2]
PWSH = shutil.which("pwsh")


def test_scripts_keep_their_values() -> None:
    text = windows.script("$Install", Install="D:\\it's here")
    assert text.startswith("$Install = 'D:\\it''s here'\n")
    assert base64.b64decode(windows.encoded("ä")).decode("utf-16-le") == "ä"
    # A map with its mode is one argument of the command line
    line = windows.windows_command_line(["-game", "doi", "+map", "bastogne stronghold"])
    assert line == '-game doi +map "bastogne stronghold"'


def powershell(body: str, install: Path) -> str:
    assert PWSH is not None
    text = windows.script(body, Install=str(install), Work=str(install / windows.WORK))
    return subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", text],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.mark.skipif(PWSH is None, reason="needs PowerShell (pwsh)")
def test_files_are_put_back(tmp_path: Path) -> None:
    """The run's files replace the install's, which come back afterwards; the server's own stay."""
    install = tmp_path / "install"
    (install / "doi/cfg").mkdir(parents=True)
    (install / "doi/cfg/server.cfg").write_text("the install's")
    (install / "doi/gameinfo.txt").write_text("game")
    powershell(windows.RESTORE, install)
    stage = install / windows.WORK / "stage"
    (stage / "doi/cfg").mkdir(parents=True)
    (stage / "doi/cfg/server.cfg").write_text("the run's")
    (stage / "doi/addons/sourcemod").mkdir(parents=True)
    (stage / "doi/addons/sourcemod/core.cfg").write_text("new")
    assert "copied 2 files" in powershell(windows.APPLY, install)
    assert (install / "doi/cfg/server.cfg").read_text() == "the run's"
    assert (install / "doi/addons/sourcemod/core.cfg").read_text() == "new"
    (install / "doi/addons/sourcemod/logs").mkdir()
    (install / "doi/addons/sourcemod/logs/L1.log").write_text("log")
    powershell(windows.RESTORE, install)
    assert (install / "doi/cfg/server.cfg").read_text() == "the install's"
    assert not (install / "doi/addons/sourcemod/core.cfg").exists()
    assert (install / "doi/addons/sourcemod/logs/L1.log").is_file()
    assert (install / "doi/gameinfo.txt").read_text() == "game"
    # Again, as at the next run's start: nothing left to put back
    powershell(windows.RESTORE, install)
    assert (install / "doi/cfg/server.cfg").read_text() == "the install's"


@pytest.mark.skipif(PWSH is None, reason="needs PowerShell (pwsh)")
def test_a_run_cut_short_loses_no_file(tmp_path: Path) -> None:
    """An original moved away, but not listed yet: it comes back all the same."""
    install = tmp_path / "install"
    work = install / windows.WORK
    (work / "originals/doi/cfg").mkdir(parents=True)
    (work / "originals/doi/cfg/server.cfg").write_text("the install's")
    powershell(windows.RESTORE, install)
    assert (install / "doi/cfg/server.cfg").read_text() == "the install's"
    assert not (work / "originals").exists()


def test_stage(tmp_path: Path) -> None:
    """The server's files as the container has them, of a SourceMod package and the config, prepared,
    without the game's own; and its command line."""
    package = tmp_path / "package"
    (package / "addons/sourcemod/plugins/disabled").mkdir(parents=True)
    (package / "addons/sourcemod/plugins/nextmap.smx").write_text("")
    (package / "addons/sourcemod/plugins/disabled/admin-sql-threaded.smx").write_text(
        ""
    )
    state = tmp_path / "state"
    (state / "game/doi").mkdir(parents=True)
    (state / "game/doi/gameinfo.txt").write_text("game")
    (state / "mods/custom").mkdir(parents=True)
    (state / "mods/custom/map.txt").write_text("mod")
    staged = windows.stage(
        tmp_path / "stage",
        "doi",
        REPOSITORY / "servers/coop-commando",
        state,
        [package],
        REPOSITORY,
        "secret",
        27115,
        {"TEST_ADMIN": "[U:1:246]"},
    )
    game = staged.root / "doi"
    plugins = game / "addons/sourcemod/plugins"
    assert (plugins / "disabled/nextmap.smx").is_file()
    assert (plugins / "admin-sql-threaded.smx").is_file()
    assert (game / "custom/map.txt").read_text() == "mod"
    assert (game / "motd.txt").is_file()
    assert (game / "subscribed_file_ids.txt").is_file()
    assert 'rcon_password "secret"' in (game / "cfg/nwi-secrets.cfg").read_text()
    assert "exec nwi-secrets.cfg" in (game / "cfg/server.cfg").read_text()
    assert (
        "[U:1:246]" in (game / "addons/sourcemod/configs/admins_simple.ini").read_text()
    )
    assert not (game / "gameinfo.txt").exists()
    # The plugins are compiled on the machine, by its SourceMod's compiler
    assert "nwi_gamedata" in staged.plugins
    assert staged.plugins[-1] == "nwi_test_rounds"
    assert (game / "addons/sourcemod/scripting/nwi_test_rounds.sp").is_file()
    assert staged.arguments[:4] == ["-console", "-norestart", "-game", "doi"]
    assert staged.arguments[staged.arguments.index("-port") + 1] == "27115"
    assert "bastogne stronghold" in staged.arguments
    assert "-workshop" in staged.arguments


def test_wait_for_rcon() -> None:
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    def refused() -> None:
        raise ConnectionRefusedError

    tries: list[float] = []

    def answers_later() -> None:
        tries.append(now[0])
        if len(tries) < 3:
            raise ConnectionRefusedError

    windows.wait_for_rcon(
        answers_later, lambda: True, clock=lambda: now[0], sleep=sleep
    )
    assert len(tries) == 3
    with pytest.raises(RuntimeError, match="ended"):
        windows.wait_for_rcon(refused, lambda: False, clock=lambda: now[0], sleep=sleep)
    with pytest.raises(RuntimeError, match="within 60 seconds"):
        windows.wait_for_rcon(
            refused, lambda: True, 60, clock=lambda: now[0], sleep=sleep
        )


def test_parse_windows_rounds() -> None:
    settings = {"WINDOWS_SOURCEMOD": "D:\\sm64;D:\\sm 32"}
    parsed = instance.parse_windows_rounds(["--bits", "32", "vm"], settings)
    assert parsed == instance.WindowsRounds(
        "vm", ["coop-commando"], 32, ["D:\\sm64", "D:\\sm 32"]
    )
    parsed = instance.parse_windows_rounds(
        ["--sourcemod", "E:\\sm", "vm", "ins-test"], settings
    )
    assert parsed.packages == ["E:\\sm"]
    assert parsed.configs == ["ins-test"]
    for args, error in (
        (["vm"], "no SourceMod package"),
        (["--bits", "16", "vm"], "32 or 64"),
        ([], "needs the machine"),
    ):
        with pytest.raises(instance.InstanceError, match=error):
            instance.parse_windows_rounds(args, {})
