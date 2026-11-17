"""Uploads to the Workshop (steam_ugc.py, workshop upload), with a stand-in of the Steamworks API's
library, fake_steam_api.c, built with the C compiler: the structures and the functions' arguments
cross the C ABI as with the SDK's."""

import ctypes
from collections.abc import Callable
from pathlib import Path

import pytest

from nwi_server_kit import games, steam_ugc
from nwi_server_kit.cli import workshop as workshop_cli

SOURCE = Path(__file__).with_name("fake_steam_api.c")


@pytest.fixture(scope="module")
def library(
    tmp_path_factory: pytest.TempPathFactory,
    build_library: Callable[[Path, Path], Path],
) -> Path:
    return build_library(SOURCE, tmp_path_factory.mktemp("steam") / "libsteam_api.so")


@pytest.fixture
def steam(library: Path, monkeypatch: pytest.MonkeyPatch) -> ctypes.CDLL:
    """The stand-in, its log emptied, as NWI_STEAM_API."""
    monkeypatch.setenv("NWI_STEAM_API", str(library))
    monkeypatch.setattr(steam_ugc, "POLL", 0)
    monkeypatch.delenv("FAKE_STEAM_RESULT", raising=False)
    for name in ("SteamAppId", "SteamGameId"):
        monkeypatch.delenv(name, raising=False)
    fake = ctypes.CDLL(str(library))
    fake.fake_log.restype = ctypes.c_char_p
    fake.fake_reset()
    return fake


def log(fake: ctypes.CDLL) -> list[str]:
    return fake.fake_log().decode().splitlines()


def test_structures() -> None:
    """As the SDK packs them on Linux, to 4 bytes: the 64-bit IDs at 4 and 8."""
    assert ctypes.sizeof(steam_ugc.CreateItemResult) == 16
    assert steam_ugc.CreateItemResult.item.offset == 4
    assert ctypes.sizeof(steam_ugc.SubmitItemUpdateResult) == 16
    assert steam_ugc.SubmitItemUpdateResult.item.offset == 8
    assert ctypes.sizeof(steam_ugc.CallCompleted) == 16
    assert ctypes.sizeof(steam_ugc.CallbackMsg) == 20


def test_a_new_item(steam: ctypes.CDLL, tmp_path: Path) -> None:
    content = tmp_path / "content"
    content.mkdir()
    progress: list[tuple[str, int, int]] = []
    with steam_ugc.Steamworks(447820) as api:
        item, agreement = api.create_item()
        assert (item, agreement) == (3600000000123, True)
        update = steam_ugc.Update(
            content=content,
            title="Vietnam",
            visibility="private",
            tags=["Theater", "Coop"],
            note="first",
            progress=lambda *step: progress.append(step),
        )
        assert api.update_item(item, update) is False
    assert log(steam) == [
        "init 447820",
        "create 447820 0",
        "start 447820 3600000000123",
        "title Vietnam",
        "visibility 2",
        "tag Theater",
        "tag Coop",
        f"content {content}",
        "submit first",
        "shutdown",
    ]
    assert progress[0] == ("uploading the content", 50, 100)


def test_a_refused_update(steam: ctypes.CDLL, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_STEAM_RESULT", "15")
    with (
        steam_ugc.Steamworks(447820) as api,
        pytest.raises(steam_ugc.SteamworksError, match="access denied"),
    ):
        api.update_item(5, steam_ugc.Update(note="x"))


def test_without_the_library(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NWI_STEAM_API", str(tmp_path / "none.so"))
    with pytest.raises(steam_ugc.SteamworksError, match="steamworks-sdk"):
        steam_ugc.Steamworks(447820)


def test_upload_stages_vpks_with_their_archives(
    steam: ctypes.CDLL, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An update of an item, of the app the Web API names; the VPKs, the archives of a _dir.vpk too,
    copied into one folder, which Steam reads before the upload ends."""
    seen: list[list[str]] = []
    original = steam_ugc.Steamworks.update_item

    def update_item(
        self: steam_ugc.Steamworks, item: int, update: steam_ugc.Update
    ) -> bool:
        assert update.content is not None
        seen.append(sorted(path.name for path in update.content.iterdir()))
        return original(self, item, update)

    monkeypatch.setattr(steam_ugc.Steamworks, "update_item", update_item)
    monkeypatch.setattr(
        games,
        "item_details",
        lambda items: [
            {"result": 1, "publishedfileid": "77", "consumer_app_id": 222880}
        ],
    )
    for name in ("a.vpk", "b_dir.vpk", "b_000.vpk", "b_001.vpk", "c_000.vpk"):
        (tmp_path / name).write_bytes(b"x")
    paths = [str(tmp_path / name) for name in ("a.vpk", "b_dir.vpk")]
    assert workshop_cli.main(["upload", *paths, "--item", "77", "--note", "fix"]) == 0
    assert seen == [["a.vpk", "b_000.vpk", "b_001.vpk", "b_dir.vpk"]]
    # Neither created nor made private: only the content and the note change
    lines = log(steam)
    assert lines[1] == "start 222880 77"
    assert lines[2].startswith("content /") and "nwi-upload-" in lines[2]
    assert lines[3:] == ["submit fix", "shutdown"]


def test_a_new_item_needs_a_title(steam: ctypes.CDLL, tmp_path: Path) -> None:
    (tmp_path / "a.vpk").write_bytes(b"x")
    assert workshop_cli.main(["upload", str(tmp_path / "a.vpk")]) == 1
    assert log(steam) == []


def test_loose_files_are_no_upload(steam: ctypes.CDLL, tmp_path: Path) -> None:
    (tmp_path / "map.bsp").write_bytes(b"x")
    arguments = ["upload", str(tmp_path / "map.bsp"), "--title", "Map"]
    assert workshop_cli.main(arguments) == 1
