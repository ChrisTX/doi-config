"""The check of the plugins' gamedata against a game install (check_gamedata.py, check-gamedata), with
stand-ins of the game's libraries built with the C compiler: their symbol tables are real ELF's."""

from collections.abc import Callable
from pathlib import Path

import pytest

from nwi_server_kit import check_gamedata
from nwi_server_kit.cli import check_gamedata as check_gamedata_cli

GAMEDATA = """\
"Games"
{
    "#default"
    {
        "#supported"
        {
            "game"  "doi"
            "game"  "insurgency"
        }
        "Signatures"
        {
            "Present"
            {
                "library"   "server"
                "linux"     "@server_function"
                "windows"   "\\\\x55\\\\x8B"
            }
            "Removed"
            {
                "linux"     "@removed_function"
            }
            "WindowsOnly"
            {
                "library"   "server"
                "windows"   "\\\\x55"
            }
            "Engine"
            {
                "library"   "engine"
                "linux"     "@engine_function"
            }
            "Matchmaking"
            {
                "library"   "matchmaking_ds"
                "linux"     "@not_checked"
            }
        }
    }
    "#default"
    {
        "#supported"
        {
            "game"  "cstrike"
        }
        "Signatures"
        {
            "OtherGame"
            {
                "library"   "server"
                "linux"     "@other_game_function"
            }
        }
    }
    "doi"
    {
        "Signatures"
        {
            "EngineRenamed"
            {
                "library"   "engine"
                "linux"     "@renamed_engine_function"
            }
        }
    }
}
"""


@pytest.fixture
def install(tmp_path: Path, build_library: Callable[[Path, Path], Path]) -> Path:
    """A Day of Infamy install: doi/ with gameinfo.txt, and its server's and engine's libraries."""
    install = tmp_path / "game"
    (install / "doi/bin").mkdir(parents=True)
    (install / "bin").mkdir()
    (install / "doi/gameinfo.txt").touch()
    for library, function in (
        ("doi/bin/server_srv.so", "server_function"),
        ("bin/engine_srv.so", "engine_function"),
    ):
        source = tmp_path / f"{function}.c"
        source.write_text(f"void {function}(void) {{}}\n")
        build_library(source, install / library)
    (tmp_path / "nwi.games.txt").write_text(GAMEDATA)
    return install


def test_missing(install: Path) -> None:
    """The game's signatures by symbol that its libraries lack: of #default's blocks for the game and
    of its own, with the server's library by default; other games' and libraries' are left out."""
    found = check_gamedata.missing(install, install.parent / "nwi.games.txt")
    assert found == [
        f"Removed: removed_function isn't in {install}/doi/bin/server_srv.so",
        f"EngineRenamed: renamed_engine_function isn't in {install}/bin/engine_srv.so",
    ]


def test_cli(install: Path, capsys: pytest.CaptureFixture[str]) -> None:
    gamedata = install.parent / "nwi.games.txt"
    assert check_gamedata_cli.main([str(install), "--gamedata", str(gamedata)]) == 1
    assert capsys.readouterr().err.count("Error: ") == 2
    text = gamedata.read_text()
    gamedata.write_text(
        text.replace("@removed_function", "@server_function").replace(
            "@renamed_engine_function", "@engine_function"
        )
    )
    assert check_gamedata_cli.main([str(install), "--gamedata", str(gamedata)]) == 0
    (install / "doi/gameinfo.txt").unlink()
    assert check_gamedata_cli.main([str(install), "--gamedata", str(gamedata)]) == 2
    assert "not one game folder" in capsys.readouterr().err
