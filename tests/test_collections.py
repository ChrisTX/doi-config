"""The Workshop's collections: their sync with the lists, without held items (workshop.py), and the
requests to Steam (steam_web.py), with Steam replaced by fakes."""

import base64
import io
import json
import time
import urllib.parse
from pathlib import Path

import pytest

from nwi_server_kit import steam_web, workshop

from .conftest import State


def token(seconds: float, steamid: str = "76561198000000001") -> str:
    """A fake refresh token (JWT) that expires in SECONDS."""
    payload = json.dumps({"sub": steamid, "exp": int(time.time() + seconds)}).encode()
    return (
        "eyJhbGciOiJFZERTQSJ9."
        + base64.urlsafe_b64encode(payload).decode().rstrip("=")
        + ".sig"
    )


class FakeSteam:
    """A collection's items and the changes asked for."""

    def __init__(self, items: dict[int, list[int]], fail: bool = False) -> None:
        self.items = items
        self.changes: list[tuple[str, int, int]] = []
        self.fail = fail

    def collection_items(self, collection: int) -> list[int]:
        return list(self.items[collection])

    def community(self, refresh_token: str) -> "FakeSteam":
        return self

    def add(self, collection: int, item: int) -> None:
        self.change("add", collection, item)

    def remove(self, collection: int, item: int) -> None:
        self.change("remove", collection, item)

    def change(self, action: str, collection: int, item: int) -> None:
        if self.fail:
            raise steam_web.SteamError("refused")
        self.changes.append((action, collection, item))


@pytest.fixture
def configs(tmp_path: Path) -> Path:
    folder = tmp_path / "configs"
    (folder / "workshop").mkdir(parents=True)
    (folder / "workshop/collections.toml").write_text(
        '[collections.900]\nlist = "doi-config/workshop-pvp.txt"\n'
    )
    (folder / "game/cfg/doi-config").mkdir(parents=True)
    (folder / "game/cfg/doi-config/workshop-pvp.txt").write_text("1\n2 // a map\n3\n")
    return folder


@pytest.fixture
def steam(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeSteam:
    fake = FakeSteam({900: [2, 3, 4]})
    monkeypatch.setattr(steam_web, "collection_items", fake.collection_items)
    monkeypatch.setattr(steam_web, "Community", fake.community)
    (tmp_path / "token").write_text(token(100 * 24 * 3600))
    monkeypatch.setenv("NWI_STEAM_TOKEN", str(tmp_path / "token"))
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    return fake


def test_collections_follow_the_lists_without_held_items(
    state: State, configs: Path, steam: FakeSteam
) -> None:
    held = {"held": {"default": {"3": "50"}}, "signed": {}}
    (state.layers / "workshop.json").write_text(json.dumps(held))
    workshop.sync_collections(state.layers, ["default"], lambda source: configs)
    # 1 is on the list, 3 is held, 4 isn't on the list any more
    assert steam.changes == [("add", 900, 1), ("remove", 900, 3), ("remove", 900, 4)]
    assert state.notifications() == []


def test_without_a_sign_in_nothing_changes(
    state: State, configs: Path, steam: FakeSteam, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NWI_STEAM_TOKEN")
    workshop.sync_collections(state.layers, ["default"], lambda source: configs)
    assert steam.changes == []


def test_a_failure_is_told_once(state: State, configs: Path, steam: FakeSteam) -> None:
    steam.fail = True
    for _ in range(2):
        workshop.sync_collections(state.layers, ["default"], lambda source: configs)
    assert state.notifications() == ["Workshop collection 900 not changed"]


def test_an_expiring_sign_in_is_told_once(
    state: State, configs: Path, steam: FakeSteam, tmp_path: Path
) -> None:
    (tmp_path / "token").write_text(token(5 * 24 * 3600))
    for _ in range(2):
        workshop.sync_collections(state.layers, ["default"], lambda source: configs)
    assert state.notifications() == ["The Workshop sign-in expires soon"]


def test_sources_without_collections(
    state: State, tmp_path: Path, steam: FakeSteam
) -> None:
    workshop.sync_collections(
        state.layers, ["default"], lambda source: tmp_path / "none"
    )
    assert steam.changes == []


def test_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """What the community session sends: its cookies, the form, the access token of the refresh
    token."""
    sent: list[tuple[str, dict, dict]] = []

    def urlopen(request: object, timeout: float) -> io.BytesIO:
        url = request.full_url  # type: ignore[attr-defined]
        fields = dict(urllib.parse.parse_qsl(request.data.decode()))  # type: ignore[attr-defined]
        sent.append((url, fields, dict(request.header_items())))  # type: ignore[attr-defined]
        if "GenerateAccessTokenForApp" in url:
            return io.BytesIO(
                json.dumps({"response": {"access_token": "ACCESS"}}).encode()
            )
        return io.BytesIO(b'{"success": 1}')

    monkeypatch.setattr(steam_web.urllib.request, "urlopen", urlopen)
    refresh = token(3600)
    community = steam_web.Community(refresh)
    community.remove(900, 3)
    url, fields, headers = sent[0]
    assert url.endswith("/IAuthenticationService/GenerateAccessTokenForApp/v1/")
    assert fields == {"refresh_token": refresh, "steamid": "76561198000000001"}
    url, fields, headers = sent[1]
    assert url == "https://steamcommunity.com/sharedfiles/removechild"
    assert fields == {"id": "900", "childid": "3", "sessionid": community.session_id}
    assert headers["Cookie"] == (
        f"steamLoginSecure=76561198000000001%7C%7CACCESS; sessionid={community.session_id}"
    )


def test_a_refused_change(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(steam_web, "access_token", lambda refresh: "ACCESS")
    monkeypatch.setattr(steam_web, "post", lambda *args, **kwargs: {"success": 2})
    with pytest.raises(steam_web.SteamError, match="addchild"):
        steam_web.Community(token(3600)).add(900, 1)


def test_collection_items(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = {
        "response": {
            "collectiondetails": [
                {
                    "result": 1,
                    "children": [
                        {"publishedfileid": "7", "sortorder": 2},
                        {"publishedfileid": "5", "sortorder": 1},
                    ],
                }
            ]
        }
    }
    monkeypatch.setattr(steam_web, "post", lambda *args, **kwargs: answer)
    assert steam_web.collection_items(900) == [5, 7]
    answer["response"]["collectiondetails"][0]["result"] = 9
    with pytest.raises(steam_web.SteamError, match="isn't a collection"):
        steam_web.collection_items(900)


def test_claims() -> None:
    refresh = token(3600)
    assert steam_web.claims(refresh)["sub"] == "76561198000000001"
    assert abs(steam_web.expires(refresh) - time.time() - 3600) < 5
    with pytest.raises(steam_web.SteamError):
        steam_web.claims("not a token")
