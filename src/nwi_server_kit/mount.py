"""The mount of a server's layers (nwi-server mount NAME UNIT, nwi-server unmount NAME), as root, for
nwi-server@.service (ExecStartPre=+, in the system's mount namespace), which runs the server in
/run/nwi-server/<name>, overlays of versions of the updater's layers (update.py), of each the newest that's good or has tries
left (layers.pick()):

    <runtime>          the record of the server's workshop items (appworkshop_<app>.acf, which the
                       game reads), the items, its game's other depots, e.g. the Steam client
                       library's, and its game's own, with a writable layer
    <runtime>/<game>   of its config source: servers/<config> (its links resolved), the compiled
                       plugins, the mods for the game, game/; then SourceMod and Metamod:Source
                       (sourcemod.v, metamod.v), the game's folder of its own depot, with a
                       writable layer

The server's game, config and config source are its environment file's (games.py): CONFIG_SOURCE,
SERVER_CONFIG_NAME and GAME, the variables of the unit.

The server and the updater run as users of their own (DynamicUser=), whose state systemd keeps as the
user nobody's on disk and maps to the unit's user. So the layers are mounted with an ID mapping of
nobody to the server's user, which sees the updater's files as its own; overlayfs takes only layers of
one mapping, so the server's config, which mount copies as root, is mapped alike, which leaves its
files root's, read-only to the server, root kept as root for copying them up. The updater's copies of
SourceMod and Metamod:Source are its own, as the other layers. So is the server's own state
(/var/lib/nwi-server/servers/<name>), whose paths it keeps are bind-mounted into the server. Its
writable layers are folders of its own in /run/nwi-server/.work/<name>, not on the mapped state:
overlayfs writes there as root, whom the mapping doesn't have. They start empty whenever the layers
are mounted, so new versions of the lower layers always show.

The versions a server uses are in /run/nwi-server/in-use/<name>, which the update keeps (layers.py),
as JSON: all of them (versions), the core ones, which the server's busy time blesses, and of the
workshop items with maps the maps (maps, of each map the item), which a map played to its end blesses
(health.py). The server's watchdog writes how it goes to /run/nwi-server/health/<name>, made here as
the server's. When the server stopped, nwi-server unmount, as systemd's ExecStopPost=, blames a
failure on the versions on trial (health.py) before it unmounts the layers.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import downloads, games, health, layers, workshop
from .server_config import load as load_settings
from .update import INSTALLS, write_record

RUN = Path("/run/nwi-server")
STATE = Path("/var/lib/nwi-server")
# The owner on disk of the dynamic users' state, which systemd maps to the units' users
NOBODY = 65534


def mounts_of(name: str) -> list[str]:
    """The mounts of a server: its overlays, their mapped layers and the bind mounts of its state."""
    targets = subprocess.run(
        ["findmnt", "-rn", "-o", "TARGET"], capture_output=True, text=True, check=True
    ).stdout.split("\n")
    runtime, work = f"{RUN}/{name}", f"{RUN}/.work/{name}/"
    return [
        target
        for target in targets
        if target == runtime or target.startswith((f"{runtime}/", work))
    ]


def unmount(name: str) -> None:
    """Unmount a server's layers, left over or mounted, the deepest first, and remove its writable
    layers and records."""
    for target in sorted(mounts_of(name), reverse=True):
        # Busy for a moment after the server stopped, while systemd takes down its mount namespace,
        # which has the mounts too; detached at last, as every start mounts them anew
        for _ in range(5):
            if (
                subprocess.run(
                    ["umount", target], capture_output=True, check=False
                ).returncode
                == 0
            ):
                break
            time.sleep(1)
        else:
            subprocess.run(["umount", "--lazy", target], check=True)
    shutil.rmtree(RUN / ".work" / name, ignore_errors=True)
    shutil.rmtree(health.RUN / name, ignore_errors=True)
    (RUN / "rcon" / name).unlink(missing_ok=True)
    (RUN / "in-use" / name).unlink(missing_ok=True)
    if (RUN / name).is_dir():
        (RUN / name).rmdir()


def mapped(source: Path, target: Path, owner: int, uid: int) -> Path:
    """SOURCE at TARGET as the server's, with the files of OWNER mapped to its user, and root's as
    root's: overlayfs can't copy up a file whose owner the mapping doesn't have, e.g. when
    nwi-server prepare moves a plugin of the packages."""
    if not target.exists():
        target.mkdir(parents=True)
    idmap = f"b:0:0:1 b:{owner}:{uid}:1"
    subprocess.run(
        ["mount", "--bind", "-o", f"X-mount.idmap={idmap}", str(source), str(target)],
        check=True,
    )
    return target


def overlay(lower: list[Path], upper: Path, work: Path, target: Path) -> None:
    """An overlay of the lower layers, the top first, each an option of its own (lowerdir+, Linux 6.8):
    the kernel takes no more than 256 characters for all of them in one lowerdir. Without xino, which a
    64-bit kernel may turn on by itself (OVERLAY_FS_XINO_AUTO), e.g. with the writable layer on tmpfs:
    its inode numbers beyond 32 bits make the 32-bit server's stat() fail."""
    options = [f"lowerdir+={layer}" for layer in lower]
    options += [f"upperdir={upper}", f"workdir={work}", "xino=off"]
    subprocess.run(
        ["mount", "-t", "overlay", "overlay", "-o", ",".join(options), str(target)],
        check=True,
    )


def app_of(item: Path) -> int:
    """The workshop's app of an item's version, laid out as steamapps/workshop/content/<app>/<item>."""
    return int(next((item / "steamapps/workshop/content").iterdir()).name)


def dropped_maps(state: Path, game: str, item: int, version: Path | None) -> list[str]:
    """The maps of an item left out: of the version the server runs, else of its newest version, else
    of its download, e.g. a new item whose only version is held."""
    version = version or layers.latest(layers.folder(state / game, f"item-{item}"))
    if version is not None:
        return maps_of(version)
    download = state / "downloads/items" / str(item)
    return sorted(path.stem for path in download.glob("maps/*.bsp"))


def leave_out(config: Path, configs: Path, dropped: set[int], maps: set[str]) -> None:
    """Leave items whose version the server runs isn't the Workshop's out of the server's copy of its
    config: of its workshop list and, their maps, of its mapcycle; a startup map of theirs becomes the
    mapcycle's first (workshop.py)."""
    settings = load_settings(config / "server.toml")
    print(
        f"Workshop items whose version isn't the Workshop's, left out: "
        f"{' '.join(map(str, sorted(dropped)))}"
        + (f"; maps: {' '.join(sorted(maps))}" if maps else ""),
        file=sys.stderr,
    )
    if "workshop" in settings:
        target = config / "cfg" / settings["workshop"]
        target.parent.mkdir(parents=True, exist_ok=True)
        text = (configs / "game/cfg" / settings["workshop"]).read_text()
        target.write_text(workshop.filter_list(text, dropped))
    if not maps:
        return
    cycle = ""
    if "mapcycle" in settings:
        target = config / "cfg" / settings["mapcycle"]
        target.parent.mkdir(parents=True, exist_ok=True)
        cycle = workshop.filter_mapcycle(
            (configs / "game/cfg" / settings["mapcycle"]).read_text(), maps
        )
        target.write_text(cycle)
    if settings["startup_map"].split()[0] in maps:
        first = next(
            (line.strip() for line in cycle.splitlines() if line.split()), None
        )
        if first is None:
            print(
                f"The startup map {settings['startup_map']} is left out, but nothing replaces it",
                file=sys.stderr,
            )
            return
        toml = config / "server.toml"
        toml.write_text(
            re.sub(
                r"^startup_map\s*=.*$",
                f'startup_map = "{first}"',
                toml.read_text(),
                count=1,
                flags=re.MULTILINE,
            )
        )
        print(
            f"Startup map {settings['startup_map']} left out, {first} instead",
            file=sys.stderr,
        )


def maps_of(item: Path) -> list[str]:
    """The maps of a workshop item's version, maps/<map>.bsp, laid out as
    steamapps/workshop/content/<app>/<item>."""
    return sorted(
        path.stem for path in item.glob("steamapps/workshop/content/*/*/maps/*.bsp")
    )


def mount(name: str, unit: str) -> None:
    """Mount the server's layers, see the module's documentation."""
    # Out of the server's folder, systemd's WorkingDirectory=, which would keep it busy
    os.chdir("/")
    state = (STATE / "layers").resolve()
    # The versions it picks aren't renamed or removed until its record has them
    with layers.lock(state):
        _mount(name, unit, state)


def _mount(name: str, unit: str, state: Path) -> None:
    uid_text = subprocess.run(
        ["systemctl", "show", "-P", "UID", unit],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if not uid_text.isdigit() or int(uid_text) == 0:
        raise ValueError(
            f"{unit} has no user of its own (DynamicUser=): {uid_text or 'none'}"
        )
    uid = int(uid_text)
    # The folders on disk, which systemd links to from /var/lib for the dynamic users
    os.environ["NWI_LAYERS"] = str(state)
    server = games.server(name, dict(os.environ), pick=True)
    configs = games.config_folder(server.source, pick=True)
    game = server.game
    kept = (STATE / "servers" / name).resolve()
    runtime, work = RUN / name, RUN / ".work" / name

    depots = (state / game / "depots").read_text().split()[0::2]
    depot_versions = [
        layers.picked(layers.folder(state, f"depot-{depot}")) for depot in depots
    ]
    approvals = workshop.load(configs)
    listed = games.workshop_items([server], game)
    items = {}
    for item in listed:
        version = layers.pick(
            layers.folder(state / game, f"item-{item}"),
            workshop.allowed_versions(state, server.source, item, approvals),
        )
        if version is not None:
            items[item] = version
    # The items whose version the server runs isn't the Workshop's, which clients would download
    dropped = {item for item in listed if item not in items}
    dropped |= {
        item
        for item, version in items.items()
        if downloads.recorded_manifest(
            state / "downloads/items" / str(item), app_of(version)
        )
        != workshop.manifest_of(version)
    }
    plugins = layers.picked(layers.folder(state, f"plugins-{server.source}"))
    mods = layers.picked(layers.folder(state / game, f"mods-{server.source}"))
    installs = [layers.picked(layers.folder(state, name)) for name, _, _ in INSTALLS]

    # The paths, relative to the server's root, that are kept between starts. The game's caches and the
    # crash handler's logs are written anew on every start.
    kept_paths = [
        "dumps",  # crash dumps
        f"{game}/logs",
        f"{game}/addons/sourcemod/logs",
        # SourceBans++'s and SourceComms' queues while the database is unreachable, the server's ID
        f"{game}/addons/sourcemod/data",
    ]

    unmount(name)
    runtime.mkdir(parents=True, mode=0o755)
    (RUN / ".work").mkdir(mode=0o700, exist_ok=True)
    work.mkdir(mode=0o700)
    # The RCON passwords, which nwi-server prepare writes, for the admins of the group nwi-rcon
    (RUN / "rcon").mkdir(mode=0o750, exist_ok=True)
    shutil.chown(RUN / "rcon", group="nwi-rcon")
    for folder in ("upper", "work"):
        for part in ("root", "game"):
            (work / folder / part).mkdir(parents=True)
            os.chown(work / folder / part, uid, uid)
            os.chown(work / folder, uid, uid)

    # The record of the server's items, for its items only
    record = work / "record"
    (record / "steamapps/workshop").mkdir(parents=True)
    if items:
        write_record(record, app_of(next(iter(items.values()))), items)
    # The server's config, copied with its symbolic links resolved: a link to another server's file, like
    # private-mp's motd.txt, points out of the server's folder, which the overlay wouldn't have
    lower_game = []
    if server.config is not None:
        shutil.copytree(
            configs / "servers" / server.config, work / "config", symlinks=False
        )
        if dropped:
            left_out_maps = {
                name
                for item in dropped
                for name in dropped_maps(state, game, item, items.get(item))
            }
            leave_out(work / "config", configs, dropped, left_out_maps)
        lower_game.append(mapped(work / "config", work / "lower/config", NOBODY, uid))
    lower_game += [
        mapped(plugins, work / "lower/plugins", NOBODY, uid),
        mapped(mods, work / "lower/mods", NOBODY, uid),
        mapped(configs / "game", work / "lower/configs", NOBODY, uid),
    ]
    lower_game += [
        mapped(version, work / f"lower/{name}", NOBODY, uid)
        for (name, _, _), version in zip(INSTALLS, installs, strict=True)
    ]
    lower_root = [mapped(record, work / "lower/record", NOBODY, uid)]
    lower_root += [
        mapped(version, work / f"lower/item-{item}", NOBODY, uid)
        for item, version in items.items()
    ]
    lower_root += [
        mapped(version, work / f"lower/depot-{depot}", NOBODY, uid)
        for depot, version in zip(depots, depot_versions, strict=True)
    ]
    lower_game.append(lower_root[-1] / game)
    overlay(lower_root, work / "upper/root", work / "work/root", runtime)
    overlay(lower_game, work / "upper/game", work / "work/game", runtime / game)

    # The paths the server keeps, in its state, as systemd's dynamic users have it: the user nobody's
    for path in kept_paths:
        (kept / "state" / path).mkdir(parents=True, exist_ok=True)
        (runtime / path).mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["chown", "-R", f"{NOBODY}:{NOBODY}", str(kept / "state")], check=True
    )
    for path in kept_paths:
        mapped(kept / "state" / path, runtime / path, NOBODY, uid)

    # Where the server's watchdog writes how it goes (health.py)
    health.RUN.mkdir(mode=0o755, parents=True, exist_ok=True)
    (health.RUN / name).mkdir(mode=0o755)
    os.chown(health.RUN / name, uid, uid)

    # The versions the server uses, which the update doesn't remove, by their canonical paths
    def canonical(path: Path) -> str:
        return str(layers.canonical(path.resolve()))

    maps = {
        map_name: canonical(version)
        for version in items.values()
        for map_name in maps_of(version)
    }
    core = [*depot_versions, plugins, mods, configs, *installs]
    core += [version for version in items.values() if not maps_of(version)]
    used = {
        "versions": [
            canonical(path)
            for path in [
                *depot_versions,
                *items.values(),
                plugins,
                mods,
                configs,
                *installs,
            ]
        ],
        "core": [canonical(path) for path in core],
        "maps": maps,
    }
    (RUN / "in-use").mkdir(mode=0o755, exist_ok=True)
    (RUN / "in-use" / name).write_text(json.dumps(used, indent=1) + "\n")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) == 2 and args[0] == "--unmount":
            unmount(args[1])
        elif len(args) == 2:
            mount(args[0], args[1])
        else:
            print(
                "Usage: nwi-server mount NAME UNIT | nwi-server unmount NAME",
                file=sys.stderr,
            )
            return 2
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"nwi-server mount: {error}", file=sys.stderr)
        return 1
    return 0


def unmount_main(argv: list[str] | None = None) -> int:
    """nwi-server unmount NAME; as ExecStopPost= of the server's unit (SERVICE_RESULT), it first blames
    a failure on the versions on trial (health.py)."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 1 and "SERVICE_RESULT" in os.environ:
        try:
            health.stopped(args[0], os.environ["SERVICE_RESULT"])
        # Whatever goes wrong, the layers are unmounted
        except Exception as error:  # noqa: BLE001
            print(
                f"nwi-server unmount: the health of {args[0]}: {error!r}",
                file=sys.stderr,
            )
    return main(["--unmount", *args]) if len(args) == 1 else main([])
