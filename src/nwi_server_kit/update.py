"""The update of the layers the servers are assembled of (nwi-server update), in the updater's state
STATE (/var/lib/nwi-server/layers), as versions (layers.py) of what it downloads and builds:

    config-<source>.v         the configs of a config source (games.py), of its clone
    plugins-<source>.v        this repository's plugins, compiled of a source's configs
    depot-<depot>.v           a depot of a game's dedicated server, which the games share, e.g. the
                              Steam client library (1006)
    <game>/item-<item>.v      a workshop item of the game's servers' lists, laid out as SteamCMD
                              would: steamapps/workshop/content/<app>/<item>
    <game>/mods-<source>.v    the mods of a source for the game (make_mods.py)
    <game>/depots             the game's depots and their manifests, a line each, the game's own last

The downloads, which the versions are copies of, are in STATE/downloads: DepotDownloader's folders of
the depots and the items, and the clones of the config sources. An update adds versions while the
servers run on others, which it doesn't touch; the servers get the new ones when they start again.
Of each layer, it keeps the newest versions and those a server uses, and removes the layers no server
needs any more, e.g. an item no list names.

With an image (nwi-server update --image), for the container image (deploy/container), the configs are
the image's, of one source, and so are the plugins. The containers mount folders of the state that
Quadlet units can name, so each server gets links in STATE/servers/<server> to the versions of its
game's own depot (game), its workshop items, a folder made of its game's items' versions
(<game>/workshop.v), and its mods, and a list of its game's other depots (depots).
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import downloads, games, layers
from .check_gamedata import main as check_gamedata
from .make_mods import main as make_mods

# The shipped, outdated C++ runtime, which the system's replaces, and libogg and libvorbis, which no
# library of the game loads (the engine has its own Vorbis decoder): the server puts bin/ on
# LD_LIBRARY_PATH, where they could take the place of the system's
OUTDATED = ("libgcc_s.so.1", "libstdc++.so.6", "libogg.so", "libvorbis.so")


def git(clone: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(clone), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def sync_source(state: Path, source: str) -> Path:
    """A config source's clone in STATE/downloads/configs, made of its repository if it's missing,
    brought to its branch or tag (detached, so a tag and a branch, even one forced, are alike), or
    pulled without one; and its version, config-<source>.v, of its commit."""
    clone = state / "downloads/configs" / source
    url, ref = games.source_settings(source)
    if not (clone / ".git").is_dir():
        if not url:
            raise ValueError(
                f"the config source {source} has neither a clone, {clone}, nor a repository (URL)"
            )
        clone.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", url, str(clone)], check=True)
    elif url:
        git(clone, "remote", "set-url", "origin", url)
    if ref:
        git(clone, "fetch", "--quiet", "--tags", "--prune", "origin")
        remote = subprocess.run(
            [
                "git",
                "-C",
                str(clone),
                "rev-parse",
                "--verify",
                "--quiet",
                f"refs/remotes/origin/{ref}",
            ],
            capture_output=True,
            check=False,
        )
        target = f"origin/{ref}" if remote.returncode == 0 else f"refs/tags/{ref}"
        git(clone, "checkout", "--quiet", "--detach", target)
    else:
        git(clone, "pull", "--quiet", "--ff-only")
    commit = git(clone, "rev-parse", "--short=12", "HEAD")
    seconds = float(git(clone, "log", "-1", "--format=%ct"))
    return layers.snapshot(
        clone,
        layers.folder(state, f"config-{source}"),
        f"{layers.stamp(seconds)}.{commit}",
    )


def build_plugins(state: Path, source: str, configs: Path) -> Path:
    """The plugins of a source's configs, compiled with SourceMod's include files and those of the
    installed packages, a version for each version of the configs and of spcomp: spcomp's builds
    differ by their time."""
    first = subprocess.run(
        ["spcomp"], capture_output=True, text=True, errors="replace", check=False
    ).stdout.split("\n", 1)[0]
    compiler = (
        first.rsplit(" ", 1)[-1] if first.startswith("SourcePawn Compiler") else "0"
    )
    layer = layers.folder(state, f"plugins-{source}")
    version = f"{layers.version_of(configs)}.{compiler}"
    name = layer.name.removesuffix(".v")
    existing = layers.current(layer / f"{name}_{version}")
    if existing is not None:
        return existing
    with tempfile.TemporaryDirectory(dir=state) as built:
        compile_plugins(configs, Path(built))
        return layers.snapshot(Path(built), layer, version)


def compile_plugins(configs: Path, output: Path) -> None:
    """Compile the plugins of configs (game/addons/sourcemod/scripting) into
    OUTPUT/addons/sourcemod/plugins, with SourceMod's include files and those of the installed
    packages (nwi-server compile-plugins CONFIGS OUTPUT, for the container image)."""
    scripting = configs / "game/addons/sourcemod/scripting"
    plugins = output / "addons/sourcemod/plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    for plugin in sorted(scripting.glob("*.sp")):
        subprocess.run(
            [
                "spcomp",
                "-i",
                str(scripting / "include"),
                "-o",
                str(plugins / f"{plugin.stem}.smx"),
                str(plugin),
            ],
            check=True,
            stdout=sys.stderr,
        )


def compile_main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("Usage: nwi-server compile-plugins CONFIGS OUTPUT", file=sys.stderr)
        return 2
    try:
        compile_plugins(Path(args[0]), Path(args[1]))
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"nwi-server compile-plugins: {error}", file=sys.stderr)
        return 1
    return 0


def remove_outdated(version: Path) -> None:
    for library in OUTDATED:
        (version / "bin" / library).unlink(missing_ok=True)


def update_depots(state: Path, game: str) -> Path:
    """The game's depots, downloaded and made versions of; returns the version of the game's own, the
    one with its folder's gameinfo.txt. A depot downloaded before without DepotDownloader's record,
    e.g. SteamCMD's install of the game, is checked file by file, so only what differs is downloaded."""
    app = games.SERVER_APPS[game]
    depots = downloads.list_depots(app)
    own = [depot for depot in depots if f"{game}/gameinfo.txt" in depot.files]
    if len(own) != 1:
        raise ValueError(f"not one depot of app {app} has {game}/gameinfo.txt")
    depots = [depot for depot in depots if depot is not own[0]] + own
    # SteamCMD's install, before the depots: the game's own to be, checked file by file
    old = state / game / "game"
    if old.is_dir() and not old.is_symlink():
        shutil.rmtree(old / "steamapps", ignore_errors=True)
        move(old, state / "downloads/depots" / str(own[0].depot))
    versions = {}
    for depot in depots:
        download = state / "downloads/depots" / str(depot.depot)
        validate = download.is_dir() and not (download / ".DepotDownloader").is_dir()
        downloads.download_depot(app, depot, download, validate)
        layer = layers.folder(state, f"depot-{depot.depot}")
        version = f"{depot.made}.{depot.manifest}"
        # The game's own without its outdated libraries, removed from the version, not the download,
        # which DepotDownloader then doesn't download again
        prepare = remove_outdated if depot is own[0] else None
        versions[depot.depot] = layers.snapshot(
            download, layer, version, prepare=prepare
        )
    record = state / game / "depots"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.with_suffix(".new").write_text(
        "".join(f"{depot.depot} {depot.manifest}\n" for depot in depots)
    )
    record.with_suffix(".new").rename(record)
    return versions[own[0].depot]


def update_items(
    state: Path, game: str, found: list[games.Server]
) -> tuple[int | None, list[int]]:
    """The workshop items of the game's servers' lists, downloaded and made versions of, each laid out
    as SteamCMD would (steamapps/workshop/content/<app>/<item>); returns the workshop's app and the
    items. An item that fails to download keeps its versions. One downloaded without
    DepotDownloader's record, e.g. SteamCMD's, is checked file by file."""
    items = games.workshop_items(found, game)
    if not items:
        return None, []
    app = games.workshop_app(items)
    if app is None:
        raise ValueError(f"none of the workshop items of {game} is available")
    updated = {
        int(detail["publishedfileid"]): int(detail.get("time_updated", 0))
        for detail in games.item_details(items)
        if detail.get("result") == 1
    }
    failed = []
    for item in items:
        download = state / "downloads/items" / str(item)
        validate = download.is_dir() and not (download / ".DepotDownloader").is_dir()
        try:
            downloads.download_item(app, item, download, validate)
        except RuntimeError:
            failed.append(item)
            continue
        manifest = downloads.recorded_manifest(download, app)
        if manifest is None:
            failed.append(item)
            continue
        layers.snapshot(
            download,
            layers.folder(state / game, f"item-{item}"),
            f"{layers.stamp(updated.get(item, 0))}.{manifest}",
            shape=f"steamapps/workshop/content/{app}/{item}",
        )
    if failed:
        print(
            f"Warning: workshop items not updated, kept as they were: {' '.join(map(str, failed))}",
            file=sys.stderr,
        )
    return app, items


def workshop_view(state: Path, game: str, app: int | None, items: list[int]) -> Path:
    """One folder of the game's items' newest versions, with their record, as a version: for the
    containers, which can't stack an item's layers."""
    # Moved into the layer or removed by keep_if_new()
    view = Path(tempfile.mkdtemp(dir=state))
    (view / "steamapps/workshop").mkdir(parents=True)
    newest = item_versions(state, game, items)
    for version in newest.values():
        subprocess.run(
            ["cp", "-a", "--reflink=auto", f"{version}/.", str(view)], check=True
        )
    if app is not None:
        write_record(view, app, newest)
    return layers.keep_if_new(view, layers.folder(state / game, "workshop"))


def item_versions(
    state: Path, game: str, items: list[int], pick: bool = False
) -> dict[int, Path]:
    """The newest version of each of the items that has one, or with PICK the one a server mounts."""
    found = {}
    for item in items:
        layer = layers.folder(state / game, f"item-{item}")
        newest = layers.pick(layer) if pick else layers.latest(layer)
        if newest is not None:
            found[item] = newest
    return found


def write_record(root: Path, app: int, items: dict[int, Path]) -> None:
    """The record of the workshop items of a server's root, steamapps/workshop/appworkshop_<app>.acf,
    as SteamCMD writes it, of the items' versions: their time and manifest are their version's
    (<time>.<manifest>). The game downloads the items itself without it."""
    installed, details, total = [], [], 0
    for item, version in sorted(items.items()):
        manifest = layers.version_of(version).split(".", 1)[1]
        updated = layers.seconds(layers.version_of(version))
        content = version / f"steamapps/workshop/content/{app}/{item}"
        size = sum(path.stat().st_size for path in content.rglob("*") if path.is_file())
        total += size
        installed.append((item, size, updated, manifest))
        details.append((item, manifest, updated))
    lines = ['"AppWorkshop"', "{"]
    lines += [
        f'\t"{key}"\t\t"{value}"'
        for key, value in (("appid", app), ("SizeOnDisk", total))
    ]
    for key in (
        "NeedsUpdate",
        "NeedsDownload",
        "TimeLastUpdated",
        "TimeLastFullCheck",
        "TimeLastAppRan",
        "LastBuildID",
    ):
        lines.append(f'\t"{key}"\t\t"0"')
    lines += ['\t"WorkshopItemsInstalled"', "\t{"]
    for item, size, updated, manifest in installed:
        lines += [
            f'\t\t"{item}"',
            "\t\t{",
            f'\t\t\t"size"\t\t"{size}"',
            f'\t\t\t"timeupdated"\t\t"{updated}"',
            f'\t\t\t"manifest"\t\t"{manifest}"',
            "\t\t}",
        ]
    lines += ["\t}", '\t"WorkshopItemDetails"', "\t{"]
    for item, manifest, updated in details:
        lines += [
            f'\t\t"{item}"',
            "\t\t{",
            f'\t\t\t"manifest"\t\t"{manifest}"',
            f'\t\t\t"timeupdated"\t\t"{updated}"',
            f'\t\t\t"latest_timeupdated"\t\t"{updated}"',
            f'\t\t\t"latest_manifest"\t\t"{manifest}"',
            "\t\t}",
        ]
    lines += ["\t}", "}"]
    record = root / f"steamapps/workshop/appworkshop_{app}.acf"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("\n".join(lines) + "\n")


def build_mods(
    state: Path,
    game: str,
    source: str,
    configs: Path,
    own: Path,
    app: int | None,
    items: list[int],
) -> Path:
    """The mods of a source's mods/<game> (make_mods.py), made of the game's own depot and its items'
    newest versions, a version when they differ from the newest; an empty one for a source without."""
    work = Path(tempfile.mkdtemp(dir=state))
    output = work / "mods"
    try:
        mods = configs / "mods" / game
        if mods.is_dir():
            # The items' versions as one folder of workshop items, as make_mods.py reads them
            workshop = work / "workshop"
            for item, version in item_versions(state, game, items).items():
                link = workshop / f"steamapps/workshop/content/{app}/{item}"
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(version / f"steamapps/workshop/content/{app}/{item}")
            workshop.mkdir(exist_ok=True)
            # The map scripts of the game and the items, which the mods are made from: the log lists
            # those whose braces are repaired, or can't be, which a mod's fix table repairs. Broken ones
            # don't fail the update, as the servers run without the maps.
            if (
                make_mods(["--game", str(own), "--workshop", str(workshop), "--check"])
                != 0
            ):
                print(
                    f"Warning: map scripts of {game} that can't be repaired, see above",
                    file=sys.stderr,
                )
            if (
                make_mods(
                    [
                        "--game",
                        str(own),
                        "--workshop",
                        str(workshop),
                        str(output),
                        str(mods),
                    ]
                )
                != 0
            ):
                raise ValueError(f"the mods of {source} for {game} can't be made")
        else:
            output.mkdir()
        return layers.keep_if_new(output, layers.folder(state / game, f"mods-{source}"))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def move(source: Path, target: Path) -> None:
    """Move a folder of an earlier layout, unless the target is there already."""
    if source.exists() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)


def migrate(state: Path) -> None:
    """Move the downloads of earlier layouts to theirs, so they aren't downloaded again, and remove the
    rest, which is made anew: Day of Infamy's layers in STATE itself, before there were other games;
    one clone of the configs (config), or a clone per source (configs/<source>), and the plugins and the
    mods made of them; the depots of DepotDownloader in depots/<depot> and the workshop items in
    <game>/workshop; the staged and the replaced layers of updates, next and previous. An install of
    SteamCMD's, <game>/game, becomes the game's depot (update_depots())."""
    if (state / "game").is_dir() and not (state / "doi").exists():
        for name in ("game", "workshop", "mods"):
            move(state / name, state / "doi" / name)
    move(state / "config", state / "downloads/configs/default")
    for clone in (
        sorted((state / "configs").glob("*")) if (state / "configs").is_dir() else []
    ):
        move(clone, state / "downloads/configs" / clone.name)
    for depot in (
        sorted((state / "depots").glob("*")) if (state / "depots").is_dir() else []
    ):
        move(depot, state / "downloads/depots" / depot.name)
    for game in games.SERVER_APPS:
        for item in sorted(
            (state / game / "workshop").glob("steamapps/workshop/content/*/*")
        ):
            move(item, state / "downloads/items" / item.name)
        for name in ("workshop", "mods"):
            if (state / game / name).is_dir() and not (
                state / game / name
            ).is_symlink():
                shutil.rmtree(state / game / name)
    for name in ("configs", "depots", "plugins", "next", "previous"):
        if (state / name).is_dir():
            shutil.rmtree(state / name)


def link(path: Path, target: Path) -> None:
    """A relative symbolic link at PATH to TARGET, replaced at once."""
    temporary = path.with_name(f".{path.name}.new")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(os.path.relpath(target, path.parent))
    temporary.rename(path)


def link_servers(state: Path, found: list[games.Server]) -> None:
    """The containers' links to their game's layers' versions, STATE/servers/<server>/{game,workshop,
    mods}, and the list of their game's other depots' versions, depots, relative to STATE."""
    for server in found:
        folder = state / "servers" / server.name
        folder.mkdir(parents=True, exist_ok=True)
        depots = (state / server.game / "depots").read_text().split()[0::2]
        newest = [
            layers.newest(layers.folder(state, f"depot-{depot}")) for depot in depots
        ]
        link(folder / "game", newest[-1])
        link(
            folder / "workshop",
            layers.newest(layers.folder(state / server.game, "workshop")),
        )
        link(
            folder / "mods",
            layers.newest(layers.folder(state / server.game, f"mods-{server.source}")),
        )
        # A file of its own, not the link of an earlier layout to the game's record
        (folder / "depots").unlink(missing_ok=True)
        (folder / "depots").write_text(
            "".join(f"{os.path.relpath(version, state)}\n" for version in newest[:-1])
        )


def collect_all(state: Path, needed: set[Path]) -> None:
    """Remove the layers' old versions, and the layers and downloads no server needs any more, those
    not in NEEDED, but no version a server uses."""
    used = layers.in_use()
    keep = layers.keep_versions()
    for layer in sorted([*state.glob("*.v"), *state.glob("*/*.v")]):
        if layer.resolve() not in needed and layers.remove_layer(layer, used):
            print(f"Removed {layer}, which no server needs", file=sys.stderr)
            continue
        for removed in layers.collect(layer, keep, used):
            print(f"Removed {removed}", file=sys.stderr)


def update(state: Path, image: bool = False) -> None:
    """Update the layers, see the module's documentation."""
    state = state.resolve()
    migrate(state)
    needed: set[Path] = set()
    if image:
        sources = [games.DEFAULT_SOURCE]
    else:
        os.environ["NWI_LAYERS"] = str(state)
        sources = games.env_sources()
        for source in sources:
            configs = sync_source(state, source)
            build_plugins(state, source, configs)
            needed |= {
                layers.folder(state, f"config-{source}"),
                layers.folder(state, f"plugins-{source}"),
            }
    found = games.servers()
    downloaded: set[str] = set()
    for game in games.used_games(found):
        own = update_depots(state, game)
        link(state / game / "game", own)
        depots = (state / game / "depots").read_text().split()[0::2]
        needed |= {layers.folder(state, f"depot-{depot}") for depot in depots}
        downloaded |= {f"depots/{depot}" for depot in depots}
        app, items = update_items(state, game, found)
        needed |= {layers.folder(state / game, f"item-{item}") for item in items}
        downloaded |= {f"items/{item}" for item in items}
        game_sources = sorted(
            {server.source for server in found if server.game == game}
        )
        for source in game_sources or [games.DEFAULT_SOURCE]:
            configs = games.config_folder(source)
            gamedata = configs / "game/addons/sourcemod/gamedata/nwi.games.txt"
            if check_gamedata([str(own), "--gamedata", str(gamedata)]) != 0:
                raise ValueError(f"{game} lacks functions of the gamedata of {source}")
            build_mods(state, game, source, configs, own, app, items)
            needed.add(layers.folder(state / game, f"mods-{source}"))
        if image:
            workshop_view(state, game, app, items)
            needed.add(layers.folder(state / game, "workshop"))
    if image:
        link_servers(state, found)
    collect_all(state, {path.resolve() for path in needed})
    for kind in ("depots", "items"):
        for download in sorted((state / "downloads" / kind).glob("*")):
            if f"{kind}/{download.name}" not in downloaded:
                shutil.rmtree(download)
                print(f"Removed {download}, which no server needs", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nwi-server update",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--image", action="store_true", help="for the container image")
    parser.add_argument("state", type=Path, metavar="STATE", help="the updater's state")
    args = parser.parse_args(argv)
    try:
        update(args.state, args.image)
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"nwi-server update: {error}", file=sys.stderr)
        return 1
    return 0
