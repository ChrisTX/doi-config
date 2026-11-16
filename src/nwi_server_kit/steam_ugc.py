"""Uploads to the Workshop through the Steamworks API (ISteamUGC), as the Steam client that runs on the
machine, signed in, does them: the account that owns an item, or one of its contributors.

The library, libsteam_api.so, is NWI_STEAM_API, or the Steamworks SDK's in /opt/steamworks-sdk. It's
loaded by its path only: games ship their own, so the SDK's mustn't be where the loader looks for
libraries. The API is used through its flat functions (steam_api_flat.h) with ctypes, and its call
results by manual dispatch (steam_api.h), polled until they're there. The app is the Workshop's (the
consumer app, e.g. 447820 of Day of Infamy), which the account has to own; Steam shows it as played
while the upload runs.
"""

import ctypes
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

LIBRARY = Path("/opt/steamworks-sdk/redistributable_bin/linux64/libsteam_api.so")
# The Workshops' apps of the games, by the names of their folders (games.py), for new items; an item's
# app is the Web API's consumer_app_id
CONSUMER_APPS = {"doi": 447820, "insurgency": 222880}
# The version of ISteamUGC of the SDK (1.65); the Steam client keeps the older ones
UGC_ACCESSOR = "SteamAPI_SteamUGC_v021"
# Callback IDs: k_iSteamUtilsCallbacks (700) + 3, k_iSteamUGCCallbacks (3400) + 3 and + 4
CALL_COMPLETED = 703
CREATE_ITEM = 3403
SUBMIT_ITEM_UPDATE = 3404
# EWorkshopFileType, ERemoteStoragePublishedFileVisibility
COMMUNITY = 0
VISIBILITIES = {"public": 0, "friends": 1, "private": 2, "unlisted": 3}
# EItemUpdateStatus
STATUSES = {
    1: "preparing",
    2: "reading the content",
    3: "uploading the content",
    4: "uploading the preview",
    5: "committing",
}
INIT_RESULTS = {
    1: "failed",
    2: "no Steam client: is Steam running and signed in?",
    3: "the Steam client is too old",
}
# EResult, the common ones of uploads
RESULTS = {
    2: "failed",
    8: "invalid parameter",
    9: "file not found",
    15: "access denied: does the account own the game and the item?",
    16: "timeout",
    25: "limit exceeded: the item or the account's storage is too big",
    44: "not signed in",
}
LEGAL_AGREEMENT = "https://steamcommunity.com/sharedfiles/workshoplegalagreement"
POLL = 0.1

uint64 = ctypes.c_uint64


class SteamworksError(RuntimeError):
    """The Steamworks API couldn't be used, or Steam refused a request."""


# The structures are packed to 4 bytes on Linux (VALVE_CALLBACK_PACK_SMALL): #pragma pack, which ctypes
# has only with the MSVC layout, the same as GCC's for structures without bit fields
class CallbackMsg(ctypes.Structure):
    _layout_ = "ms"
    _pack_ = 4
    _fields_ = [
        ("user", ctypes.c_int32),
        ("callback", ctypes.c_int),
        ("param", ctypes.c_void_p),
        ("size", ctypes.c_int),
    ]


class CallCompleted(ctypes.Structure):
    _layout_ = "ms"
    _pack_ = 4
    _fields_ = [
        ("call", uint64),
        ("callback", ctypes.c_int),
        ("size", ctypes.c_uint32),
    ]


class CreateItemResult(ctypes.Structure):
    _layout_ = "ms"
    _pack_ = 4
    _fields_ = [
        ("result", ctypes.c_int),
        ("item", uint64),
        ("legal_agreement", ctypes.c_bool),
    ]


class SubmitItemUpdateResult(ctypes.Structure):
    _layout_ = "ms"
    _pack_ = 4
    _fields_ = [
        ("result", ctypes.c_int),
        ("legal_agreement", ctypes.c_bool),
        ("item", uint64),
    ]


class StringArray(ctypes.Structure):
    _fields_ = [
        ("strings", ctypes.POINTER(ctypes.c_char_p)),
        ("count", ctypes.c_int32),
    ]


# The flat functions used: their results and arguments; `self` is the interface's pointer
FUNCTIONS: dict[str, tuple[object, list[object]]] = {
    "SteamAPI_InitFlat": (ctypes.c_int, [ctypes.c_char_p]),
    "SteamAPI_Shutdown": (None, []),
    "SteamAPI_IsSteamRunning": (ctypes.c_bool, []),
    "SteamAPI_GetHSteamPipe": (ctypes.c_int32, []),
    "SteamAPI_ManualDispatch_Init": (None, []),
    "SteamAPI_ManualDispatch_RunFrame": (None, [ctypes.c_int32]),
    "SteamAPI_ManualDispatch_GetNextCallback": (
        ctypes.c_bool,
        [ctypes.c_int32, ctypes.POINTER(CallbackMsg)],
    ),
    "SteamAPI_ManualDispatch_FreeLastCallback": (None, [ctypes.c_int32]),
    "SteamAPI_ManualDispatch_GetAPICallResult": (
        ctypes.c_bool,
        [
            ctypes.c_int32,
            uint64,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_bool),
        ],
    ),
    UGC_ACCESSOR: (ctypes.c_void_p, []),
    "SteamAPI_ISteamUGC_CreateItem": (
        uint64,
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int],
    ),
    "SteamAPI_ISteamUGC_StartItemUpdate": (
        uint64,
        [ctypes.c_void_p, ctypes.c_uint32, uint64],
    ),
    "SteamAPI_ISteamUGC_SetItemTitle": (
        ctypes.c_bool,
        [ctypes.c_void_p, uint64, ctypes.c_char_p],
    ),
    "SteamAPI_ISteamUGC_SetItemDescription": (
        ctypes.c_bool,
        [ctypes.c_void_p, uint64, ctypes.c_char_p],
    ),
    "SteamAPI_ISteamUGC_SetItemVisibility": (
        ctypes.c_bool,
        [ctypes.c_void_p, uint64, ctypes.c_int],
    ),
    "SteamAPI_ISteamUGC_SetItemTags": (
        ctypes.c_bool,
        [ctypes.c_void_p, uint64, ctypes.POINTER(StringArray), ctypes.c_bool],
    ),
    "SteamAPI_ISteamUGC_SetItemContent": (
        ctypes.c_bool,
        [ctypes.c_void_p, uint64, ctypes.c_char_p],
    ),
    "SteamAPI_ISteamUGC_SetItemPreview": (
        ctypes.c_bool,
        [ctypes.c_void_p, uint64, ctypes.c_char_p],
    ),
    "SteamAPI_ISteamUGC_SubmitItemUpdate": (
        uint64,
        [ctypes.c_void_p, uint64, ctypes.c_char_p],
    ),
    "SteamAPI_ISteamUGC_GetItemUpdateProgress": (
        ctypes.c_int,
        [ctypes.c_void_p, uint64, ctypes.POINTER(uint64), ctypes.POINTER(uint64)],
    ),
}


def library_path() -> Path:
    """The Steamworks API's library: NWI_STEAM_API, or the SDK's."""
    path = Path(os.environ.get("NWI_STEAM_API") or LIBRARY)
    if not path.is_file():
        raise SteamworksError(
            f"no Steamworks API at {path}: install the Steamworks SDK (steamworks-sdk) or set "
            "NWI_STEAM_API to its redistributable_bin/linux64/libsteam_api.so"
        )
    return path


def describe(result: int) -> str:
    return f"{RESULTS.get(result, 'error')} (EResult {result})"


@dataclass
class Update:
    """What an upload changes of an item; None leaves it as it is."""

    content: Path | None = None
    title: str | None = None
    description: str | None = None
    preview: Path | None = None
    visibility: str | None = None
    tags: list[str] | None = None
    note: str = ""
    # Told the progress: the status and the bytes done and in all
    progress: Callable[[str, int, int], None] = field(
        default=lambda status, done, total: None
    )


class Steamworks:
    """The Steamworks API of an app, with the Steam client: a context, shut down when it ends."""

    def __init__(self, app: int, library: Path | None = None) -> None:
        self.app = app
        # The API takes the app of the environment (or of a steam_appid.txt in the working folder)
        os.environ["SteamAppId"] = str(app)
        os.environ["SteamGameId"] = str(app)
        self.lib = ctypes.CDLL(str(library or library_path()))
        for name, (result, arguments) in FUNCTIONS.items():
            try:
                function = getattr(self.lib, name)
            except AttributeError as error:
                raise SteamworksError(
                    f"the Steamworks API has no {name}: is it the SDK's?"
                ) from error
            function.restype = result
            function.argtypes = arguments
        message = ctypes.create_string_buffer(1024)
        status = self.lib.SteamAPI_InitFlat(message)
        if status != 0:
            raise SteamworksError(
                f"Steamworks API: {INIT_RESULTS.get(status, 'failed')} "
                f"({message.value.decode(errors='replace')})"
            )
        self.lib.SteamAPI_ManualDispatch_Init()
        self.pipe = self.lib.SteamAPI_GetHSteamPipe()
        self.ugc = getattr(self.lib, UGC_ACCESSOR)()
        if not self.ugc:
            self.close()
            raise SteamworksError("the Steam client has no ISteamUGC of this version")

    def close(self) -> None:
        self.lib.SteamAPI_Shutdown()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def wait(
        self,
        call: int,
        result: ctypes.Structure,
        callback: int,
        tick: Callable[[], None] = lambda: None,
    ) -> None:
        """Wait for the result of a call, into RESULT, calling TICK in between."""
        if call == 0:
            raise SteamworksError("Steam didn't take the request")
        lib = self.lib
        message = CallbackMsg()
        while True:
            lib.SteamAPI_ManualDispatch_RunFrame(self.pipe)
            done = False
            while lib.SteamAPI_ManualDispatch_GetNextCallback(
                self.pipe, ctypes.byref(message)
            ):
                try:
                    if message.callback != CALL_COMPLETED:
                        continue
                    completed = CallCompleted.from_address(message.param)
                    if completed.call != call:
                        continue
                    failed = ctypes.c_bool()
                    if (
                        not lib.SteamAPI_ManualDispatch_GetAPICallResult(
                            self.pipe,
                            call,
                            ctypes.byref(result),
                            ctypes.sizeof(result),
                            callback,
                            ctypes.byref(failed),
                        )
                        or failed.value
                    ):
                        raise SteamworksError(
                            "the request failed: Steam may have lost its connection"
                        )
                    done = True
                finally:
                    lib.SteamAPI_ManualDispatch_FreeLastCallback(self.pipe)
            if done:
                return
            if not lib.SteamAPI_IsSteamRunning():
                raise SteamworksError("Steam stopped")
            tick()
            time.sleep(POLL)

    def create_item(self) -> tuple[int, bool]:
        """A new, empty item of the app: its ID, and whether the account still has to accept the
        Workshop's legal agreement, without which it stays hidden."""
        result = CreateItemResult()
        self.wait(
            self.lib.SteamAPI_ISteamUGC_CreateItem(self.ugc, self.app, COMMUNITY),
            result,
            CREATE_ITEM,
        )
        if result.result != 1:
            raise SteamworksError(f"no item created: {describe(result.result)}")
        return result.item, result.legal_agreement

    def update_item(self, item: int, update: Update) -> bool:
        """Change an item; whether the account still has to accept the legal agreement."""
        lib = self.lib
        handle = lib.SteamAPI_ISteamUGC_StartItemUpdate(self.ugc, self.app, item)
        changes: list[tuple[str, bool]] = []
        if update.title is not None:
            changes.append(
                (
                    "title",
                    lib.SteamAPI_ISteamUGC_SetItemTitle(
                        self.ugc, handle, update.title.encode()
                    ),
                )
            )
        if update.description is not None:
            changes.append(
                (
                    "description",
                    lib.SteamAPI_ISteamUGC_SetItemDescription(
                        self.ugc, handle, update.description.encode()
                    ),
                )
            )
        if update.visibility is not None:
            changes.append(
                (
                    "visibility",
                    lib.SteamAPI_ISteamUGC_SetItemVisibility(
                        self.ugc, handle, VISIBILITIES[update.visibility]
                    ),
                )
            )
        if update.tags is not None:
            strings = (ctypes.c_char_p * max(len(update.tags), 1))(
                *(tag.encode() for tag in update.tags)
            )
            array = StringArray(strings, len(update.tags))
            changes.append(
                (
                    "tags",
                    lib.SteamAPI_ISteamUGC_SetItemTags(
                        self.ugc, handle, ctypes.byref(array), False
                    ),
                )
            )
        if update.content is not None:
            changes.append(
                (
                    "content",
                    lib.SteamAPI_ISteamUGC_SetItemContent(
                        self.ugc, handle, str(update.content.resolve()).encode()
                    ),
                )
            )
        if update.preview is not None:
            changes.append(
                (
                    "preview",
                    lib.SteamAPI_ISteamUGC_SetItemPreview(
                        self.ugc, handle, str(update.preview.resolve()).encode()
                    ),
                )
            )
        refused = [name for name, taken in changes if not taken]
        if refused:
            raise SteamworksError(f"Steam refused the item's {', '.join(refused)}")
        done, total = uint64(), uint64()

        def tick() -> None:
            status = lib.SteamAPI_ISteamUGC_GetItemUpdateProgress(
                self.ugc, handle, ctypes.byref(done), ctypes.byref(total)
            )
            if status in STATUSES:
                update.progress(STATUSES[status], done.value, total.value)

        result = SubmitItemUpdateResult()
        self.wait(
            lib.SteamAPI_ISteamUGC_SubmitItemUpdate(
                self.ugc, handle, update.note.encode()
            ),
            result,
            SUBMIT_ITEM_UPDATE,
            tick,
        )
        if result.result != 1:
            raise SteamworksError(f"item {item} not updated: {describe(result.result)}")
        return result.legal_agreement
