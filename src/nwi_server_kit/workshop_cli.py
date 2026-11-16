"""nwi-server workshop: the signatures of VPKs and the approval of workshop items' versions (workshop.py).

Usage:
    nwi-server workshop keygen NAME [--bits BITS] [--dir DIR]
        a key pair to sign VPKs with: DIR/NAME.key, the private key (keep it to yourself, off the machine
        that uploads to the Workshop), and DIR/NAME.pem, the public key for workshop/keys/ of the configs
    nwi-server workshop pack FOLDER VPK
        pack a folder, e.g. a mod's repository, into a VPK as the Workshop takes it (version 2, one
        file); files and folders starting with a dot, e.g. .git, are left out
    nwi-server workshop sign KEY VPK...
        sign VPKs (version 2, e.g. a mod's) in place with a private key
    nwi-server workshop verify VPK|FOLDER...
        verify VPKs' signatures and checksums, and print their keys' fingerprints
    nwi-server workshop freeze [--configs DIR]
        approve the current version of every item of the configs' servers' workshop lists, in
        workshop/approved.toml, which then gates their updates (keeping what it approves already)
    nwi-server workshop approve ITEM [MANIFEST] [--configs DIR]
        approve a version of an item, the Workshop's current one without MANIFEST
    nwi-server workshop status [STATE]
        the versions the update held, per config source
    nwi-server workshop login
        sign in for changing the collections, with a QR code to scan in the Steam app, and print the
        refresh token, e.g. for: systemd-creds encrypt --name=nwi-server.steam-refresh-token -
        /etc/credstore.encrypted/nwi-server.steam-refresh-token
    nwi-server workshop collection ID
        a collection's items
    nwi-server workshop upload VPK...|FOLDER [--item ITEM | --game GAME --title TITLE] [--note NOTE]
            [--description TEXT] [--preview IMAGE] [--visibility VISIBILITY] [--tag TAG]...
        upload VPKs, or a folder as it is, as a new version of ITEM, or as a new item of GAME's Workshop
        (doi by default; private unless --visibility says otherwise), with the Steam client of this
        machine, signed in as the item's owner or a contributor, and the Steamworks SDK (steam_ugc.py)

The configs are the checkout the tools are in (NWI_CONFIG) without --configs.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

from . import games, steam_ugc, steam_web, vpk, workshop
from .server_config import load as load_settings

HEADER = """\
# The approved versions of the workshop items of the servers' lists, by their manifests, and the keys
# (workshop/keys/<name>.pem) an item's versions may be signed with, which approves them too. Any other
# new version is held: the servers keep theirs (see nwi_server_kit/workshop.py).
"""


def listed_items(configs: Path) -> list[int]:
    """The items of the workshop lists the configs' servers name."""
    items: set[int] = set()
    for toml in sorted(configs.glob("servers/*/server.toml")):
        settings = load_settings(toml)
        if "workshop" in settings:
            text = (configs / "game/cfg" / settings["workshop"]).read_text()
            items |= {
                int(line.split()[0])
                for line in text.splitlines()
                if line.split() and line.split()[0].isdigit()
            }
    return sorted(items)


def current_manifests(items: list[int]) -> dict[int, str]:
    """The Workshop's current manifests of the items that are available."""
    return {
        int(detail["publishedfileid"]): str(detail["hcontent_file"])
        for detail in games.item_details(items)
        if detail.get("result") == 1 and detail.get("hcontent_file")
    }


def read_approved(configs: Path) -> dict[int, dict[str, list[str]]]:
    path = configs / workshop.APPROVED
    if not path.is_file():
        return {}
    with path.open("rb") as file:
        settings = tomllib.load(file)
    return {
        int(item): {
            "manifests": [str(manifest) for manifest in entry.get("manifests", [])],
            "keys": [str(key) for key in entry.get("keys", [])],
        }
        for item, entry in settings.get("items", {}).items()
    }


def write_approved(configs: Path, approved: dict[int, dict[str, list[str]]]) -> None:
    lines = [HEADER]
    for item, entry in sorted(approved.items()):
        lines.append(f"[items.{item}]")
        lines.append(
            "manifests = [" + ", ".join(f'"{m}"' for m in entry["manifests"]) + "]"
        )
        if entry["keys"]:
            lines.append("keys = [" + ", ".join(f'"{k}"' for k in entry["keys"]) + "]")
        lines.append("")
    path = configs / workshop.APPROVED
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip("\n") + "\n")


def approve(
    approved: dict[int, dict[str, list[str]]], item: int, manifest: str
) -> bool:
    """Approve a manifest of an item; whether it's new."""
    entry = approved.setdefault(item, {"manifests": [], "keys": []})
    if manifest in entry["manifests"]:
        return False
    entry["manifests"].append(manifest)
    return True


def show_code(url: str) -> None:
    """Show a sign-in's QR code on the terminal (qrencode), and its URL."""
    print(
        "Scan this code in the Steam app (Steam Guard, the QR code button):",
        file=sys.stderr,
    )
    if shutil.which("qrencode"):
        subprocess.run(
            ["qrencode", "-t", "ansiutf8", url], stdout=sys.stderr, check=False
        )
    else:
        print(
            "(install qrencode to see the code here; the URL is the code)",
            file=sys.stderr,
        )
    print(url, file=sys.stderr)


def stage(paths: list[Path], folder: Path) -> Path:
    """The content of an upload: a folder as it is, or VPKs, with their archives, copied into FOLDER."""
    if len(paths) == 1 and paths[0].is_dir():
        return paths[0]
    for path in paths:
        if path.is_dir() or path.suffix != ".vpk":
            raise ValueError(f"{path}: upload VPKs, or one folder")
        files = [path]
        if path.name.endswith("_dir.vpk"):
            stem = path.name.removesuffix("_dir.vpk")
            files += sorted(path.parent.glob(f"{stem}_[0-9][0-9][0-9].vpk"))
        for file in files:
            if (folder / file.name).exists():
                raise ValueError(f"{file.name}: given twice")
            shutil.copy2(file, folder / file.name)
    return folder


def show_progress(status: str, done: int, total: int) -> None:
    share = f" {done * 100 // total}%" if total else ""
    print(f"\r{status}{share}\033[K", end="", file=sys.stderr, flush=True)


def upload(args: argparse.Namespace) -> int:
    if args.item is None and args.title is None:
        raise ValueError("a new item needs --title")
    if args.item is not None:
        details = games.item_details([args.item])
        if not details or details[0].get("result") != 1:
            raise ValueError(f"item {args.item} isn't available on the Workshop")
        app = int(details[0]["consumer_app_id"])
    else:
        app = steam_ugc.CONSUMER_APPS[args.game]
    with tempfile.TemporaryDirectory(prefix="nwi-upload-") as temporary:
        content = stage(args.paths, Path(temporary))
        update = steam_ugc.Update(
            content=content,
            title=args.title,
            description=args.description,
            preview=args.preview,
            visibility=args.visibility or ("private" if args.item is None else None),
            tags=args.tag,
            note=args.note,
            progress=show_progress,
        )
        with steam_ugc.Steamworks(app) as steam:
            item = args.item
            agreement = False
            if item is None:
                item, agreement = steam.create_item()
                print(
                    f"Item {item} created; if the upload fails, give it --item {item}",
                    file=sys.stderr,
                )
            agreement |= steam.update_item(item, update)
        print(file=sys.stderr)
    print(f"https://steamcommunity.com/sharedfiles/filedetails/?id={item}")
    if agreement:
        print(
            "The item stays hidden until the account accepts the Workshop's legal agreement: "
            + steam_ugc.LEGAL_AGREEMENT,
            file=sys.stderr,
        )
    print(
        "Unless its VPKs are signed with a key of the configs, approve the new version in them: "
        f"nwi-server workshop approve {item}",
        file=sys.stderr,
    )
    return 0


def configs_folder(argument: Path | None) -> Path:
    if argument is not None:
        return argument
    single = games.single_config()
    if single is None:
        raise ValueError(
            "no configs: run it in a checkout of the configs, or give --configs"
        )
    return single


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nwi-server workshop",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    command = commands.add_parser("keygen", help="a key pair to sign VPKs with")
    command.add_argument("name", metavar="NAME")
    command.add_argument(
        "--bits", type=int, default=2048, help="the RSA key's size (%(default)s)"
    )
    command.add_argument(
        "--dir", type=Path, default=Path("."), help="where to write the keys"
    )
    command = commands.add_parser("pack", help="pack a folder into a VPK")
    command.add_argument("folder", type=Path, metavar="FOLDER")
    command.add_argument("output", type=Path, metavar="VPK")
    command = commands.add_parser("sign", help="sign VPKs with a private key")
    command.add_argument("key", type=Path, metavar="KEY")
    command.add_argument("vpks", type=Path, nargs="+", metavar="VPK")
    command = commands.add_parser("verify", help="verify VPKs' signatures")
    command.add_argument("paths", type=Path, nargs="+", metavar="VPK|FOLDER")
    for name, help_text in (
        ("freeze", "approve the current versions of all listed items"),
        ("approve", "approve a version of an item"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--configs", type=Path, help="the configs' checkout")
        if name == "approve":
            command.add_argument("item", type=int, metavar="ITEM")
            command.add_argument("manifest", nargs="?", metavar="MANIFEST")
    commands.add_parser("login", help="sign in for changing the collections")
    command = commands.add_parser("collection", help="a collection's items")
    command.add_argument("collection", type=int, metavar="ID")
    command = commands.add_parser("upload", help="upload to the Workshop")
    command.add_argument("paths", type=Path, nargs="+", metavar="VPK|FOLDER")
    command.add_argument("--item", type=int, help="the item to update")
    command.add_argument(
        "--game",
        choices=sorted(steam_ugc.CONSUMER_APPS),
        default=games.DEFAULT,
        help="the game of a new item (%(default)s)",
    )
    command.add_argument("--title")
    command.add_argument("--description")
    command.add_argument("--preview", type=Path, help="the preview image")
    command.add_argument("--visibility", choices=list(steam_ugc.VISIBILITIES))
    command.add_argument(
        "--tag", action="append", help="a tag, replacing the item's (repeatable)"
    )
    command.add_argument("--note", default="", help="the change note")
    command = commands.add_parser("status", help="the held versions")
    command.add_argument(
        "state",
        type=Path,
        nargs="?",
        default=Path("/var/lib/nwi-server/layers"),
        metavar="STATE",
    )
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (
        ValueError,
        OSError,
        tomllib.TOMLDecodeError,
        steam_web.SteamError,
        steam_ugc.SteamworksError,
    ) as error:
        print(f"nwi-server workshop: {error}", file=sys.stderr)
        return 1


def run(args: argparse.Namespace) -> int:
    if args.command == "keygen":
        private, public = vpk.keygen(args.bits)
        args.dir.mkdir(parents=True, exist_ok=True)
        key = args.dir / f"{args.name}.key"
        key.touch(mode=0o600, exist_ok=False)
        key.write_bytes(private)
        (args.dir / f"{args.name}.pem").write_bytes(public)
        print(
            f"{key}: the private key; {args.dir / args.name}.pem: the public key, "
            f"{vpk.key_name(vpk.public_der(public))}"
        )
        return 0
    if args.command == "pack":
        count = vpk.pack(args.folder, args.output)
        print(f"{args.output}: {count} files")
        return 0
    if args.command == "sign":
        private = args.key.read_bytes()
        for path in args.vpks:
            public = vpk.sign(path, private)
            print(f"{path}: signed, key {vpk.key_name(public)}")
        return 0
    if args.command == "verify":
        status = 0
        for path in args.paths:
            for found in vpk.files_of(path) if path.is_dir() else [path]:
                try:
                    print(f"{found}: valid, key {vpk.key_name(vpk.verify(found))}")
                except vpk.VPKError as error:
                    print(error)
                    status = 1
        return status
    if args.command in ("freeze", "approve"):
        configs = configs_folder(args.configs)
        approved = read_approved(configs)
        if args.command == "freeze":
            items = listed_items(configs)
            found = current_manifests(items)
            added = sum(
                approve(approved, item, manifest) for item, manifest in found.items()
            )
            for item in sorted(set(items) - set(found)):
                print(
                    f"Item {item} isn't available on the Workshop, left out",
                    file=sys.stderr,
                )
            print(f"{added} versions approved, of {len(found)} items")
        else:
            manifest = args.manifest or current_manifests([args.item]).get(args.item)
            if manifest is None:
                raise ValueError(f"item {args.item} isn't available on the Workshop")
            new = approve(approved, args.item, manifest)
            print(
                f"Item {args.item} at {manifest}: {'approved' if new else 'approved already'}"
            )
        write_approved(configs, approved)
        return 0
    if args.command == "login":
        answer = steam_web.sign_in(show_code)
        token = str(answer["refresh_token"])
        expiry = time.strftime("%Y-%m-%d", time.gmtime(steam_web.expires(token)))
        print(
            f"Signed in as {answer.get('account_name')}, until {expiry}",
            file=sys.stderr,
        )
        print(token)
        return 0
    if args.command == "upload":
        return upload(args)
    if args.command == "collection":
        for item in steam_web.collection_items(args.collection):
            print(item)
        return 0
    held = workshop.State(args.state).held
    if not any(held.values()):
        print("No version is held.")
    for source, held_items in sorted(held.items()):
        for held_item, manifest in sorted(held_items.items()):
            print(f"{source}: item {held_item}, version {manifest} held")
    return 0
