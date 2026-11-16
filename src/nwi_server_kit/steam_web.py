"""Steam's web services for the Workshop's collections: signing in by QR code, access tokens of a
refresh token, a collection's items, and adding and removing them.

A refresh token comes of a sign-in by QR code (IAuthenticationService's BeginAuthSessionViaQR and
PollAuthSessionStatus), approved in the Steam app, as the mobile app's: its access tokens, which
GenerateAccessTokenForApp makes of it, are also the community site's sign-in (steamLoginSecure). It
lasts about 200 days. The Web API has no way to change a collection's items, so they're changed as the
community site does, with its sharedfiles/addchild and removechild requests, which aren't a documented
API and may change. A collection's items are read with ISteamRemoteStorage's GetCollectionDetails,
without signing in.
"""

import base64
import json
import secrets
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

API = "https://api.steampowered.com"
COMMUNITY = "https://steamcommunity.com"
# EAuthTokenPlatformType: the mobile app's tokens are also the community site's sign-in
MOBILE_APP = 3
TIMEOUT = 60


class SteamError(RuntimeError):
    """A request that Steam refused or that failed."""


def post(
    url: str, fields: dict[str, str | int], cookies: str = "", referer: str = ""
) -> dict:
    """POST form fields; returns the JSON answer."""
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields).encode(),
        headers={"User-Agent": "nwi-server-kit"}
        | ({"Cookie": cookies} if cookies else {})
        | ({"Referer": referer} if referer else {}),
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            return json.load(answer)
    except (OSError, ValueError) as error:
        raise SteamError(f"{url}: {error}") from error


@dataclass
class QRSession:
    """A sign-in by QR code waiting for its approval in the Steam app."""

    client_id: str
    request_id: str
    challenge_url: str
    interval: float


def begin_qr(name: str = "nwi-server-kit") -> QRSession:
    """Start a sign-in by QR code: the challenge URL is the code the Steam app scans."""
    answer = post(
        f"{API}/IAuthenticationService/BeginAuthSessionViaQR/v1/",
        {"device_friendly_name": name, "platform_type": MOBILE_APP},
    ).get("response", {})
    if "client_id" not in answer:
        raise SteamError(f"no sign-in started: {answer}")
    return QRSession(
        str(answer["client_id"]),
        str(answer["request_id"]),
        str(answer["challenge_url"]),
        float(answer.get("interval", 5)),
    )


def poll(session: QRSession) -> dict | None:
    """Whether the sign-in was approved: its answer, with refresh_token and account_name, or None
    while it waits. A new challenge replaces the session's."""
    answer = post(
        f"{API}/IAuthenticationService/PollAuthSessionStatus/v1/",
        {"client_id": session.client_id, "request_id": session.request_id},
    ).get("response", {})
    if answer.get("new_client_id"):
        session.client_id = str(answer["new_client_id"])
    if answer.get("new_challenge_url"):
        session.challenge_url = str(answer["new_challenge_url"])
    return answer if answer.get("refresh_token") else None


def claims(token: str) -> dict:
    """The claims of a token (a JWT), unverified: e.g. sub, the account's SteamID, and exp."""
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError) as error:
        raise SteamError("not a Steam token") from error


def expires(token: str) -> float:
    """When a token expires, as seconds since the epoch."""
    return float(claims(token).get("exp", 0))


def access_token(refresh_token: str) -> str:
    """A new access token of a refresh token."""
    answer = post(
        f"{API}/IAuthenticationService/GenerateAccessTokenForApp/v1/",
        {"refresh_token": refresh_token, "steamid": claims(refresh_token)["sub"]},
    ).get("response", {})
    if not answer.get("access_token"):
        raise SteamError(
            "no access token: the refresh token may have expired or been revoked"
        )
    return str(answer["access_token"])


def collection_items(collection: int) -> list[int]:
    """The items of a collection, in its order."""
    answer = post(
        f"{API}/ISteamRemoteStorage/GetCollectionDetails/v1/",
        {"collectioncount": 1, "publishedfileids[0]": collection},
    ).get("response", {})
    details = answer.get("collectiondetails", [{}])[0]
    if details.get("result") != 1:
        raise SteamError(
            f"{collection} isn't a collection (result {details.get('result')})"
        )
    children = sorted(
        details.get("children", []), key=lambda child: child.get("sortorder", 0)
    )
    return [int(child["publishedfileid"]) for child in children]


class Community:
    """A session of the community site, of a refresh token, for changing collections."""

    def __init__(self, refresh_token: str) -> None:
        self.steamid = claims(refresh_token)["sub"]
        self.token = access_token(refresh_token)
        # Any value, which the requests repeat, as the site's own forms do
        self.session_id = secrets.token_hex(12)

    def change(self, action: str, collection: int, item: int) -> None:
        """Add an item to a collection (addchild) or remove it (removechild)."""
        cookies = f"steamLoginSecure={self.steamid}%7C%7C{self.token}; sessionid={self.session_id}"
        answer = post(
            f"{COMMUNITY}/sharedfiles/{action}",
            {"id": collection, "childid": item, "sessionid": self.session_id},
            cookies,
            f"{COMMUNITY}/sharedfiles/managecollection/?id={collection}",
        )
        if answer.get("success") != 1:
            raise SteamError(f"{action} of {item} to {collection}: {answer}")

    def add(self, collection: int, item: int) -> None:
        self.change("addchild", collection, item)

    def remove(self, collection: int, item: int) -> None:
        self.change("removechild", collection, item)


def sign_in(show: Callable[[str], None], timeout: float = 300) -> dict:
    """Sign in by QR code: SHOW the challenge URL (again when it changes) and wait for the approval;
    returns the answer with refresh_token and account_name."""
    session = begin_qr()
    shown = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if session.challenge_url != shown:
            show(session.challenge_url)
            shown = session.challenge_url
        answer = poll(session)
        if answer is not None:
            return answer
        time.sleep(session.interval)
    raise SteamError("the sign-in wasn't approved in time")
