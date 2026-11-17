"""The scan of a game client's workshop items (client_scan.py, workshop scan-client), in a fake
Steam folder of two libraries: Steam's records, the versions scanned once, the client's own caches,
and the notifications."""

from pathlib import Path

import pytest

from nwi_server_kit import client_scan
from nwi_server_kit.cli import workshop as workshop_cli


def record(items: dict[int, str]) -> str:
    """An appworkshop_<app>.acf of items and their manifests, as Steam writes it."""
    installed = "".join(
        f'\t\t"{item}"\n\t\t{{\n\t\t\t"size"\t\t"1"\n\t\t\t"manifest"\t\t"{manifest}"\n\t\t}}\n'
        for item, manifest in items.items()
    )
    return f'"AppWorkshop"\n{{\n\t"appid"\t\t"447820"\n\t"WorkshopItemsInstalled"\n\t{{\n{installed}\t}}\n}}\n'


@pytest.fixture
def steam(tmp_path: Path) -> Path:
    """Steam with a second library: Day of Infamy's items in the second, a clean one, one with a
    config, and one with the client's own sound caches."""
    root = tmp_path / "Steam"
    library = tmp_path / "SteamLibrary"
    (root / "steamapps").mkdir(parents=True)
    (root / "steamapps/libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{root}"\n\t}}\n'
        f'\t"1"\n\t{{\n\t\t"path"\t\t"{library}"\n\t}}\n}}\n'
    )
    content = library / "steamapps/workshop/content/447820"
    for item, files in {
        1: {"maps/clean.txt": "x"},
        2: {"cfg/autoexec.cfg": "rcon_password x"},
        3: {"pak.vpk.sound.cache": "c", "sound/sound.cache": "c"},
    }.items():
        for name, text in files.items():
            (content / str(item) / name).parent.mkdir(parents=True, exist_ok=True)
            (content / str(item) / name).write_text(text)
    (library / "steamapps/workshop/appworkshop_447820.acf").write_text(
        record({1: "101", 2: "201", 3: "301"})
    )
    return root


def test_libraries(steam: Path, tmp_path: Path) -> None:
    assert client_scan.libraries(steam) == [steam, tmp_path / "SteamLibrary"]
    assert client_scan.libraries(tmp_path / "none") == [tmp_path / "none"]
    library = tmp_path / "SteamLibrary"
    assert client_scan.installed_items(library, 447820) == {
        1: "101",
        2: "201",
        3: "301",
    }
    assert client_scan.installed_items(library, 222880) == {}


def test_scan_once(steam: Path, tmp_path: Path) -> None:
    """Each version once: a new manifest is scanned again; the client's caches pass."""
    state = tmp_path / "state.json"
    results = client_scan.scan_client(steam, state)
    assert {result.item: result.findings for result in results} == {
        1: [],
        2: ["cfg/autoexec.cfg: in cfg/, which isn't a folder of content"],
        3: [],
    }
    assert client_scan.scan_client(steam, state) == []
    acf = tmp_path / "SteamLibrary/steamapps/workshop/appworkshop_447820.acf"
    acf.write_text(record({1: "102", 2: "201", 3: "301"}))
    assert [result.item for result in client_scan.scan_client(steam, state)] == [1]


def test_cli(
    steam: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exit status 1 and a notification of an item with findings."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(client_scan, "notify", lambda *args: sent.append(args))
    assert workshop_cli.main(["scan-client", "--steam", str(steam), "--notify"]) == 1
    assert "Day of Infamy: 2: cfg/autoexec.cfg" in capsys.readouterr().out
    assert len(sent) == 1 and "id=2" in sent[0][1]
    assert workshop_cli.main(["scan-client", "--steam", str(steam)]) == 0


def test_without_clamd(
    steam: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without clamd one notification, not a finding of every item, and nothing marked scanned."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("NWI_CLAMD", str(tmp_path / "none.ctl"))
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(client_scan, "notify", lambda *args: sent.append(args))
    assert workshop_cli.main(["scan-client", "--steam", str(steam), "--notify"]) == 2
    assert len(sent) == 1 and "weren't scanned" in sent[0][0]
    assert not (tmp_path / "xdg/nwi-server-kit/client-scan.json").exists()


def fake_workshop(monkeypatch: pytest.MonkeyPatch, files: dict[str, str]) -> None:
    """The Web API's details of items 5 (Day of Infamy's) and 6 (another game's), and a download
    of item 5 with FILES."""

    def details(items: list[int]) -> list[dict[str, object]]:
        known = {
            5: {
                "result": 1,
                "publishedfileid": "5",
                "consumer_app_id": 447820,
                "title": "Mod",
            },
            6: {
                "result": 1,
                "publishedfileid": "6",
                "consumer_app_id": 440,
                "title": "Hat",
            },
        }
        return [known.get(item, {"result": 9}) for item in items]

    def download(app: int, item: int, folder: Path, validate: bool = False) -> None:
        assert (app, item) == (447820, 5)
        for name, text in files.items():
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            (folder / name).write_text(text)

    monkeypatch.setattr(client_scan.games, "item_details", details)
    monkeypatch.setattr(client_scan.downloads, "download_item", download)


def test_scan_item(monkeypatch: pytest.MonkeyPatch) -> None:
    """An item's current version, scanned as the servers scan theirs: a client's cache is a finding."""
    fake_workshop(monkeypatch, {"maps/a.txt": "x", "pak.vpk.sound.cache": "c"})
    title, findings = client_scan.scan_item(5)
    assert title == "Mod"
    assert findings == ["pak.vpk.sound.cache: a file at the top that isn't a VPK"]
    with pytest.raises(ValueError, match="app 440"):
        client_scan.scan_item(6)
    with pytest.raises(ValueError, match="isn't an available"):
        client_scan.scan_item(7)


def test_scan_item_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_workshop(monkeypatch, {"maps/a.txt": "x"})
    assert workshop_cli.main(["scan-item", "5"]) == 0
    assert "5 (Mod): no findings" in capsys.readouterr().out
    assert workshop_cli.main(["scan-item", "5", "7"]) == 2
