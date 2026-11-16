"""The trial of new versions of the layers (layers.py): blessed once they proved themselves on a
server, counted down when a server fails with them, so that a version that keeps failing is passed over
for the one before.

Usage:
    nwi-server health [status]          the versions on trial and how far they got
    nwi-server health bless             bless the versions that proved themselves (nwi-bless.service)
    nwi-server health approve VERSION…  bless versions by hand
    nwi-server health retry VERSION…    give versions their tries again, e.g. after a fix elsewhere

A server's watchdog (watchdog.py) writes how it goes to /run/nwi-server/health/<server>/status.json:
its run (INVOCATION_ID), whether it answered yet (ready), its map, its busy seconds, those with at
least NWI_BLESS_PLAYERS human players (4 by default), and the maps played to their end while busy
(completed). Of what the server's mount records (mount.py), the versions on trial are blessed:

- the core ones (the depots, the configs, the plugins, the mods, and the workshop items without maps)
  after NWI_BLESS_MINUTES busy minutes (120 by default), counted over all servers and runs that use
  them, in /var/lib/nwi-server/health/versions.json;
- a workshop item with maps once one of its maps was played to its end while busy, the server changing
  to the next map.

When a server fails (nwi-server unmount, ExecStopPost=, with systemd's SERVICE_RESULT), the failure is
blamed by where it happened: before the server answered, on all its versions on trial; on a good or the
game's own map, on its core versions on trial; on a map of an item on trial, on that item, unless the
server failed on another map of an item on trial too with the same core versions, which blames the core
versions instead, and the items blamed before get their tries back. A version blamed counts a try down;
once it has none left, the servers pass it over, and the admins are notified (notify.py). The failures
of a server are in /var/lib/nwi-server/health/<server>.json.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

from . import layers, notify

RUN = Path("/run/nwi-server/health")
IN_USE = layers.IN_USE
STATE = Path("/var/lib/nwi-server/health")
LAYERS = Path("/var/lib/nwi-server/layers")


def busy_players() -> int:
    """How many human players make a server busy."""
    return int(os.environ.get("NWI_BLESS_PLAYERS", "4"))


def busy_seconds() -> float:
    """How long the core versions have to run busy to be blessed."""
    return 60 * float(os.environ.get("NWI_BLESS_MINUTES", "120"))


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def write_json(path: Path, value: Any) -> None:
    """Write a file whole or not at all."""
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.new")
    temporary.write_text(json.dumps(value, indent=1) + "\n")
    temporary.rename(path)


def on_trial(version: str) -> Path | None:
    """The version of a canonical path, as it's named now, if it's on trial."""
    path = layers.current(Path(version))
    return path if path is not None and layers.counters(path) is not None else None


def bless(version: str, why: str) -> bool:
    """Bless a version on trial; whether it was on trial."""
    path = on_trial(version)
    if path is None:
        return False
    layers.renamed(path, None)
    print(f"Blessed {layers.canonical(path)}: {why}", file=sys.stderr)
    return True


def charge(version: str, why: str) -> bool:
    """Count a try of a version on trial down, and notify the admins once it has none left; whether it
    was on trial with tries left."""
    path = on_trial(version)
    counters = layers.counters(path) if path is not None else None
    if path is None or counters is None or counters[0] == 0:
        return False
    left, done = counters
    layers.renamed(path, left - 1, done + 1)
    print(
        f"Blamed {layers.canonical(path)}, {left - 1} tries left: {why}",
        file=sys.stderr,
    )
    if left == 1:
        layer = path.parent
        fallback = layers.pick(layer)
        notify.queue(
            f"{layers.canonical(path).name} failed",
            f"{layers.canonical(path)} used up its tries: {why}.\n\n"
            + (
                f"The servers fall back to {fallback.name}."
                if fallback is not None
                and layers.canonical(fallback) != layers.canonical(path)
                else "There's no version to fall back to, the servers keep using it."
            )
            + "\n\nOnce fixed, give it its tries again with: nwi-server health retry "
            + str(layers.canonical(path)),
        )
    return True


def refund(version: str) -> None:
    """Give a version on trial back a try it was blamed for."""
    path = on_trial(version)
    counters = layers.counters(path) if path is not None else None
    if path is not None and counters is not None and counters[1] > 0:
        layers.renamed(path, counters[0] + 1, counters[1] - 1)
        print(f"Unblamed {layers.canonical(path)}", file=sys.stderr)


def apply(name: str, record: dict, status: dict) -> None:
    """Bless what a server's status shows proven (see the module's documentation), counting only what
    the server's state doesn't have yet. Called with the layers' lock held."""
    state_path = STATE / f"{name}.json"
    server = read_json(state_path, {"failures": []})
    if server.get("invocation") != status.get("invocation"):
        server.update(invocation=status.get("invocation"), seconds=0, completed=0)
    seconds = float(status.get("busy_seconds", 0)) - server["seconds"]
    if seconds > 0:
        totals = read_json(STATE / "versions.json", {})
        for version in record["core"]:
            if on_trial(version) is None:
                totals.pop(version, None)
                continue
            totals[version] = totals.get(version, 0) + seconds
            if totals[version] >= busy_seconds():
                bless(version, f"{totals[version] / 60:.0f} busy minutes")
                totals.pop(version)
        write_json(STATE / "versions.json", totals)
        server["seconds"] = float(status.get("busy_seconds", 0))
    completed = status.get("completed", [])
    for map_name in completed[server["completed"] :]:
        item = record["maps"].get(map_name)
        if item is not None:
            bless(item, f"{map_name} was played to its end on {name}")
    server["completed"] = len(completed)
    write_json(state_path, server)


def server_files(name: str) -> tuple[dict | None, dict | None]:
    """A mounted server's record and its watchdog's status, None where there's none."""
    record = read_json(IN_USE / name, None)
    status = read_json(RUN / name / "status.json", None)
    return record, status


def bless_all() -> None:
    """Bless what the mounted servers proved (nwi-server health bless)."""
    if not IN_USE.is_dir():
        return
    with layers.lock(LAYERS.resolve()):
        for path in sorted(IN_USE.iterdir()):
            record, status = server_files(path.name)
            if record is not None and status is not None:
                apply(path.name, record, status)


def stopped(name: str, result: str) -> None:
    """After a server stopped, as systemd's ExecStopPost=, with its SERVICE_RESULT: bless what it proved
    up to then, and blame a failure, see the module's documentation."""
    record, status = server_files(name)
    if record is None:
        return
    # A status of an earlier run doesn't tell where this one failed
    if status is not None and status.get("invocation") != os.environ.get(
        "INVOCATION_ID"
    ):
        status = None
    with layers.lock(LAYERS.resolve()):
        if status is not None:
            apply(name, record, status)
        if result == "success":
            return
        state_path = STATE / f"{name}.json"
        server = read_json(state_path, {"failures": []})
        core = sorted(version for version in record["core"] if on_trial(version))
        map_name = (
            status.get("map") if status is not None and status.get("ready") else None
        )
        item = record["maps"].get(map_name) if map_name else None
        item = item if item is not None and on_trial(item) else None
        where = f"{name} failed ({result})" + (f" on {map_name}" if map_name else "")
        if map_name is None:
            blamed = [version for version in record["versions"] if on_trial(version)]
            why = f"{name} failed ({result}) before it answered"
        elif item is None:
            blamed, why = core, where
        else:
            # The failures with the same core versions, on maps of items on trial
            earlier = [
                failure
                for failure in server["failures"]
                if failure["core"] == core and failure.get("item")
            ]
            if {failure["map"] for failure in earlier} - {map_name}:
                blamed, why = core, f"{where}, as on other maps"
                for failure in earlier:
                    for version in failure["charged"]:
                        if version == failure["item"]:
                            refund(version)
                    failure["charged"] = [
                        version
                        for version in failure["charged"]
                        if version != failure["item"]
                    ]
            else:
                blamed, why = [item], where
        charged = [version for version in blamed if charge(version, why)]
        if not charged:
            print(f"{where}, with no version on trial to blame", file=sys.stderr)
        server["failures"] = [
            *server["failures"][-19:],
            {"map": map_name, "item": item, "core": core, "charged": charged},
        ]
        write_json(state_path, server)


def version_folder(version: str) -> Path:
    """The version of a layer a command names, as it's named now: a folder NAME_VERSION, with or without
    counters, of a layer NAME.v of the updater's state. Nothing else is renamed."""
    state = LAYERS.resolve()
    path = layers.current(Path(version).resolve()) if version else None
    if (
        path is None
        or state not in path.parents
        or not path.parent.name.endswith(".v")
        or not path.name.startswith(path.parent.name.removesuffix(".v") + "_")
    ):
        raise ValueError(f"not a version of a layer in {state}: {version!r}")
    return path


def status_report() -> None:
    """Print the versions on trial, their tries and their busy minutes."""
    state = LAYERS.resolve()
    totals = read_json(STATE / "versions.json", {})
    found = sorted(
        path
        for path in [*state.glob("*.v/*+*"), *state.glob("*/*.v/*+*")]
        if layers.counters(path) is not None
    )
    if not found:
        print("No version is on trial.")
    for path in found:
        left, done = layers.counters(path) or (0, 0)
        minutes = totals.get(str(layers.canonical(path)), 0) / 60
        print(
            f"{layers.canonical(path).relative_to(state)}: {left} tries left, {done} failed, "
            f"{minutes:.0f} of {busy_seconds() / 60:.0f} busy minutes"
        )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    command = args[0] if args else "status"
    try:
        if command == "status" and len(args) <= 1:
            status_report()
        elif command == "bless" and len(args) == 1:
            bless_all()
        elif command in ("approve", "retry") and len(args) > 1:
            with layers.lock(LAYERS.resolve()):
                for version in args[1:]:
                    path = version_folder(version)
                    if command == "approve":
                        bless(str(path), "approved by hand")
                    else:
                        layers.renamed(path, layers.tries())
                        print(
                            f"{layers.canonical(path)} is on trial again",
                            file=sys.stderr,
                        )
        else:
            print(__doc__.split("Usage:")[1].split("\n\n")[0].rstrip(), file=sys.stderr)
            return 2
    except (ValueError, OSError) as error:
        print(f"nwi-server health: {error}", file=sys.stderr)
        return 1
    return 0
