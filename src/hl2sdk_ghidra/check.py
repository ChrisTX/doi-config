"""SourceMod's gamedata (gamedata.py) checked against a game's program in Ghidra: each vtable offset by
the method in that slot of every class's vtable (OK, WRONG with the slots the method is in, NOTHERE if
the library doesn't have it), and each signature by symbol (@name) of the program's library by whether
the symbol exists (OK, MISSING).

Each class's primary vtable (Itanium: offset to top, typeinfo, then the slots) is read once, up to the
next vtable, a null pointer, an address that isn't a function, or the end of the memory.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import ghidra
from .gamedata import Entry

if TYPE_CHECKING:
    from ghidra.program.model.listing import Program

# Gamedata names that differ from the methods', SourceMod's names of all games (checked with Day of
# Infamy, Insurgency, TF2, CS:S and L4D2)
ALIAS = {
    "SetEntityModel": "SetModel",
    "WeaponEquip": "Weapon_Equip",
    "GroundEntChanged": "NetworkStateChanged_m_hGroundEntity",
    "SetUserCvar": "SetUserCVar",
    "SetClientName": "SetName",
    "PlayerRunCmd": "PlayerRunCommand",
}
# Offsets that aren't vtable slots: SourceMod's of all games, and those of a game's own gamedata
FIELDS = frozenset(
    {
        "CSendPropExtra_UtlVector::m_Offset",
        "EntInfo",
        "GetTEName",
        "GetTENext",
        "TE_GetServerClass",
        "EntityListeners",
        "GetDataDescMap",
        # CBaseClient's field that CBaseServer::UpdateUserSettings checks (Day of Infamy's own)
        "InfoChanged",
        # sm-cstrike.games (CS:S): fields of the weapons' info, the players and the teams
        "WeaponName",
        "WeaponPrice",
        "ClanTagOffset",
        "CTTeamScoreOffset",
        "TTeamScoreOffset",
        "MVPs",
    }
)
# The results that are failures of the check
FAILED = frozenset({"WRONG", "MISSING"})
# The label Ghidra gives a vtable in its class's namespace
VTABLE = "vtable"
# The slots read of a vtable at most
MAX_SLOTS = 700


@dataclass(frozen=True)
class Result:
    """The check of an entry: OK, WRONG, NOTHERE or MISSING, and what was found."""

    status: str
    entry: Entry
    detail: str

    def __str__(self) -> str:
        kind = "offset" if self.entry.kind == "Offsets" else "signature"
        return (
            f"{self.status:<7} {kind} {self.entry.name} {self.entry.value}{self.detail}"
        )


def vtables(found: "Program") -> dict[str, list[str | None]]:
    """The methods of every class's primary vtable, by the class's name, slot by slot."""
    from ghidra.program.model.mem import MemoryAccessException

    table = found.getSymbolTable()
    starts = {}
    for symbol in table.getAllSymbols(True):
        if symbol.getName() == VTABLE and symbol.getParentNamespace() is not None:
            starts[symbol.getParentNamespace().getName(True)] = symbol.getAddress()
    labels = {start.getOffset() for start in starts.values()}
    memory = found.getMemory()
    functions = found.getFunctionManager()
    pointer = found.getDefaultPointerSize()
    names: dict[int, str | None] = {}
    result = {}
    for cls, start in sorted(starts.items()):
        slots: list[str | None] = []
        for index in range(MAX_SLOTS):
            offset = start.getOffset() + pointer * (2 + index)
            if index > 0 and offset in labels:
                break
            try:
                location = ghidra.address(found, offset)
                value = (
                    memory.getLong(location)
                    if pointer == 8
                    else memory.getInt(location) & 0xFFFFFFFF
                )
            except MemoryAccessException:
                break
            if value == 0:
                break
            if value not in names:
                function = functions.getFunctionAt(ghidra.address(found, value))
                names[value] = None if function is None else str(function.getName())
            if names[value] is None:
                break
            slots.append(names[value])
        result[cls] = slots
    return result


def check_offset(slots: dict[str, list[str | None]], entry: Entry) -> Result:
    """Check a vtable offset by the method in that slot of every class's vtable."""
    method = ALIAS.get(entry.name, entry.name)
    index = int(entry.value)
    at = [
        cls
        for cls, methods in slots.items()
        if index < len(methods) and methods[index] == method
    ]
    if at:
        return Result("OK", entry, f" ({len(at)} classes, e.g. {at[0]})")
    where: dict[int, list[str]] = {}
    for cls, methods in slots.items():
        for slot, name in enumerate(methods):
            if name == method:
                where.setdefault(slot, []).append(cls)
    if not where:
        return Result("NOTHERE", entry, f" (no method {method} in this library)")
    found = " ".join(
        f"{slot} ({len(classes)}, e.g. {classes[0]})"
        for slot, classes in sorted(where.items())
    )
    return Result("WRONG", entry, f", but {method} is at: {found}")


def check(found: "Program", entries: list[Entry], library: str) -> list[Result]:
    """Check the gamedata's entries against the program, the library LIBRARY (server or engine)."""
    table = found.getSymbolTable()
    results = []
    offsets = [
        entry
        for entry in entries
        if entry.kind == "Offsets" and entry.name not in FIELDS
    ]
    slots = vtables(found) if offsets else {}
    for entry in entries:
        if entry.kind == "Signatures":
            if entry.library != library or not entry.value.startswith("@"):
                continue
            symbol = entry.value[1:]
            exists = (
                table.getSymbols(symbol).hasNext()
                or not table.getGlobalSymbols(symbol).isEmpty()
            )
            results.append(Result("OK" if exists else "MISSING", entry, ""))
        elif entry in offsets:
            results.append(check_offset(slots, entry))
    return results
