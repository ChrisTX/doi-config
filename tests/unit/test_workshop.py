"""VPK signatures (vpk.py), the approval of workshop items' versions and the servers' lists of them
(workshop.py, cli/workshop.py, mount.leave_out, check_updates)."""

import hashlib
import json
import struct
import zlib
from pathlib import Path

import pytest

from nwi_server_kit import check_updates, mount, notify, vpk, workshop
from nwi_server_kit.cli import workshop as workshop_cli

from .conftest import State


def build_vpk(path: Path, files: dict[str, bytes], split: bool = False) -> Path:
    """An unsigned version 2 VPK of the files: their data embedded, or with SPLIT in an archive, as
    <name>_dir.vpk and <name>_000.vpk; returns the directory."""
    tree = b""
    data = b""
    by_extension: dict[str, dict[str, list[tuple[str, bytes]]]] = {}
    for name, content in files.items():
        folder, _, file_name = name.rpartition("/")
        stem, _, extension = file_name.rpartition(".")
        by_extension.setdefault(extension, {}).setdefault(folder or " ", []).append(
            (stem, content)
        )
    for extension, folders in by_extension.items():
        tree += extension.encode() + b"\0"
        for folder, entries in folders.items():
            tree += folder.encode() + b"\0"
            for stem, content in entries:
                tree += stem.encode() + b"\0"
                archive = 0 if split else vpk.EMBEDDED
                tree += struct.pack(
                    "<IHHIIH",
                    zlib.crc32(content),
                    0,
                    archive,
                    len(data),
                    len(content),
                    0xFFFF,
                )
                data += content
            tree += b"\0"
        tree += b"\0"
    tree += b"\0"
    directory = path.with_name(path.stem + "_dir.vpk") if split else path
    chunks = b""
    if split:
        directory.with_name(path.stem + "_000.vpk").write_bytes(data)
        chunks = b"".join(
            vpk.CHUNK.pack(0, 0, offset, len(part), hashlib.md5(part).digest())
            for offset, part in vpk.chunk_parts(data)
        )
        data = b""
    header = vpk.HEADER.pack(vpk.MAGIC, 2, len(tree), len(data), len(chunks), 48, 0)
    unsigned = header + tree + data + chunks
    unsigned += hashlib.md5(tree).digest() + hashlib.md5(chunks).digest()
    unsigned += hashlib.md5(unsigned).digest()
    directory.write_bytes(unsigned)
    return directory


@pytest.fixture(scope="module")
def keys() -> dict[str, tuple[bytes, bytes]]:
    """Two key pairs (private, public PEM): 2048-bit, and 1024-bit like the game's own."""
    return {"community": vpk.keygen(2048), "other": vpk.keygen(1024)}


FILES = {
    "scripts/theaters/mod.theater": b'"theater" {}\n',
    "materials/a.vmt": b"x" * 3000,
}


@pytest.mark.parametrize("split", [False, True])
def test_sign_and_verify(tmp_path: Path, keys: dict, split: bool) -> None:
    directory = build_vpk(tmp_path / "mod.vpk", FILES, split)
    with pytest.raises(vpk.VPKError, match="not signed"):
        vpk.verify(directory)
    private, public = keys["community"]
    signed = vpk.sign(directory, private)
    assert signed == vpk.public_der(public)
    assert vpk.verify(directory) == signed
    assert sorted(entry.path for entry in vpk.parse(directory).entries) == sorted(FILES)
    # Signed again, with another key, it's that key's
    vpk.sign(directory, keys["other"][0])
    assert vpk.verify(directory) == vpk.public_der(keys["other"][1])


def test_srctools_reads_a_signed_vpk(tmp_path: Path, keys: dict) -> None:
    from srctools.vpk import VPK

    path = build_vpk(tmp_path / "mod.vpk", FILES)
    vpk.sign(path, keys["community"][0])
    assert sorted(VPK(path).filenames()) == sorted(FILES)


@pytest.mark.parametrize("where", ["header", "tree", "data", "signature"])
def test_a_changed_byte_is_found(tmp_path: Path, keys: dict, where: str) -> None:
    path = build_vpk(tmp_path / "mod.vpk", FILES)
    vpk.sign(path, keys["community"][0])
    parsed = vpk.parse(path)
    offset = {
        "header": 8,
        "tree": vpk.HEADER.size + 2,
        "data": vpk.HEADER.size + parsed.tree + 10,
        "signature": len(parsed.data) - 5,
    }[where]
    data = bytearray(path.read_bytes())
    data[offset] ^= 1
    path.write_bytes(data)
    with pytest.raises(vpk.VPKError):
        vpk.verify(path)


def test_a_changed_or_missing_archive_is_found(tmp_path: Path, keys: dict) -> None:
    directory = build_vpk(tmp_path / "mod.vpk", FILES, split=True)
    vpk.sign(directory, keys["community"][0])
    archive = vpk.archive_path(directory, 0)
    data = bytearray(archive.read_bytes())
    data[100] ^= 1
    archive.write_bytes(data)
    with pytest.raises(vpk.VPKError, match="chunk of its archive"):
        vpk.verify(directory)
    archive.unlink()
    with pytest.raises(vpk.VPKError, match="is missing"):
        vpk.verify(directory)


def test_pack(tmp_path: Path, keys: dict) -> None:
    """A folder packed as the Workshop takes it, without dot files, signed and read back."""
    folder = tmp_path / "mod"
    for name, content in FILES.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(content)
    (folder / "README").write_bytes(b"no extension")
    (folder / ".git").mkdir()
    (folder / ".git/config").write_bytes(b"left out")
    (folder / ".gitattributes").write_bytes(b"left out")
    output = tmp_path / "mod.vpk"
    assert vpk.pack(folder, output) == 3
    parsed = vpk.parse(output)
    base = vpk.HEADER.size + parsed.tree
    contents = {
        entry.path: parsed.data[
            base + entry.offset : base + entry.offset + entry.length
        ]
        for entry in parsed.entries
    }
    assert contents == {**FILES, "README": b"no extension"}
    vpk.check_md5(output, parsed)
    vpk.sign(output, keys["community"][0])
    assert vpk.verify(output) == vpk.public_der(keys["community"][1])


def test_files_of(tmp_path: Path) -> None:
    build_vpk(tmp_path / "split.vpk", FILES, split=True)
    build_vpk(tmp_path / "single.vpk", FILES)
    assert [path.name for path in vpk.files_of(tmp_path)] == [
        "single.vpk",
        "split_dir.vpk",
    ]


ITEM = 3431236539


@pytest.fixture
def configs(tmp_path: Path, keys: dict) -> Path:
    """Configs with a server listing two items, approvals of one and the community's key."""
    folder = tmp_path / "configs"
    (folder / "workshop/keys").mkdir(parents=True)
    (folder / "workshop/keys/community.pem").write_bytes(keys["community"][1])
    (folder / "workshop/approved.toml").write_text(
        f'[items.{ITEM}]\nmanifests = ["111"]\nkeys = ["community"]\n\n[items.222]\nmanifests = ["5"]\n'
    )
    (folder / "servers/coop").mkdir(parents=True)
    (folder / "servers/coop/server.toml").write_text(
        'hostname = "Coop"\nstartup_map = "custom_map stronghold"\n'
        'mapcycle = "doi-config/mapcycle.txt"\nworkshop = "doi-config/workshop.txt"\n'
    )
    (folder / "game/cfg/doi-config").mkdir(parents=True)
    (folder / "game/cfg/doi-config/workshop.txt").write_text(
        f"{ITEM}\n222 // a map\n333\n"
    )
    (folder / "game/cfg/doi-config/mapcycle.txt").write_text(
        "custom_map stronghold\nbastogne stronghold\ncustom_map raid\n"
    )
    return folder


def item_folder(
    tmp_path: Path, keys: dict, key: str | None, loose: bool = False
) -> Path:
    folder = tmp_path / "download"
    folder.mkdir(exist_ok=True)
    path = build_vpk(folder / "mod.vpk", FILES)
    if key is not None:
        vpk.sign(path, keys[key][0])
    if loose:
        (folder / "maps").mkdir()
        (folder / "maps/custom_map.bsp").write_bytes(b"VBSP")
    return folder


def test_approvals(configs: Path, keys: dict) -> None:
    approvals = workshop.load(configs)
    assert approvals is not None
    assert approvals.manifests == {ITEM: {"111"}, 222: {"5"}}
    assert approvals.keys[ITEM] == [vpk.public_der(keys["community"][1])]
    assert workshop.load(configs / "nothing") is None


@pytest.mark.parametrize(
    ("key", "loose", "reason"),
    [
        ("community", False, None),
        (None, False, "not signed"),
        ("other", False, "signed by another key"),
        ("community", True, "not VPKs only"),
    ],
)
def test_signed_by(
    tmp_path: Path,
    configs: Path,
    keys: dict,
    key: str | None,
    loose: bool,
    reason: str | None,
) -> None:
    approvals = workshop.load(configs)
    assert approvals is not None
    found = workshop.signed_by(
        item_folder(tmp_path, keys, key, loose), approvals.keys[ITEM]
    )
    assert found is None if reason is None else reason in (found or "")


def test_gate(state: State, tmp_path: Path, configs: Path, keys: dict) -> None:
    approvals = workshop.load(configs)
    sources: dict[str, workshop.Approvals | None] = {"default": approvals}
    unsigned = item_folder(tmp_path, keys, None)
    # An approved manifest passes; an unapproved, unsigned one is held, the admins told once
    assert workshop.gate(state.layers, ITEM, "111", unsigned, sources)
    assert not workshop.gate(state.layers, ITEM, "112", unsigned, sources)
    assert not workshop.gate(state.layers, ITEM, "112", unsigned, sources)
    assert state.notifications() == [f"Workshop item {ITEM} held"]
    assert workshop.State(state.layers).held == {"default": {str(ITEM): "112"}}
    # A signed one passes and is recorded; the hold ends
    vpk.sign(unsigned / "mod.vpk", keys["community"][0])
    assert workshop.gate(state.layers, ITEM, "113", unsigned, sources)
    record = workshop.State(state.layers)
    assert record.signed == {"default": {str(ITEM): ["113"]}}
    assert record.held == {"default": {}}
    assert record.approved("default", ITEM, "113", approvals)
    # Another source without approvals passes anything
    assert workshop.gate(
        state.layers, 999, "1", unsigned, {"other": None, "default": approvals}
    )


def test_filters() -> None:
    assert workshop.filter_list("1\n2 // two\n\n3\n", {2}) == "1\n\n3\n"
    assert (
        workshop.filter_mapcycle("a stronghold\nb raid\na raid\n\n", {"a"})
        == "b raid\n\n"
    )


def test_leave_out(tmp_path: Path, configs: Path) -> None:
    """A server's copy of its config without the items whose version isn't the Workshop's."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "server.toml").write_text(
        (configs / "servers/coop/server.toml").read_text()
    )
    item = tmp_path / "item" / f"steamapps/workshop/content/447820/{ITEM}/maps"
    item.mkdir(parents=True)
    (item / "custom_map.bsp").write_bytes(b"VBSP")
    maps = set(mount.dropped_maps(tmp_path, "doi", ITEM, tmp_path / "item"))
    # An item without a version: the maps of its download
    download = tmp_path / "downloads/items/333/maps"
    download.mkdir(parents=True)
    (download / "other_map.bsp").write_bytes(b"VBSP")
    maps |= set(mount.dropped_maps(tmp_path, "doi", 333, None))
    assert maps == {"custom_map", "other_map"}
    mount.leave_out(config, configs, {ITEM, 333}, maps)
    assert (config / "cfg/doi-config/workshop.txt").read_text() == "222 // a map\n"
    assert (
        config / "cfg/doi-config/mapcycle.txt"
    ).read_text() == "bastogne stronghold\n"
    assert 'startup_map = "bastogne stronghold"' in (config / "server.toml").read_text()


def test_held_versions_are_no_updates(
    state: State, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = {"held": {"a": {"1": "50"}, "b": {"1": "50"}}, "signed": {}}
    (state.layers / "workshop.json").write_text(json.dumps(held))
    details = [
        {"publishedfileid": "1", "result": 1, "hcontent_file": "50", "title": "held"},
        {"publishedfileid": "2", "result": 1, "hcontent_file": "60", "title": "new"},
    ]
    monkeypatch.setattr(
        check_updates,
        "item_details",
        lambda items: [d for d in details if int(str(d["publishedfileid"])) in items],
    )
    updates = check_updates.workshop_updates(
        state.layers, "doi", {1: {"a", "b"}, 2: {"a"}}
    )
    assert updates == ["workshop item 2 (new): not installed"]
    # Held for one source only, it's an update for the other
    updates = check_updates.workshop_updates(state.layers, "doi", {1: {"a", "c"}})
    assert updates == ["workshop item 1 (held): not installed"]


def test_freeze_and_approve(configs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workshop,
        "current_manifests",
        lambda items: {item: f"{item}0" for item in items},
    )
    assert workshop_cli.main(["freeze", "--configs", str(configs)]) == 0
    approved = workshop.read_approved(configs)
    assert approved[ITEM] == {
        "manifests": ["111", f"{ITEM}0"],
        "keys": ["community"],
        "unscanned": [],
    }
    assert approved[333] == {"manifests": ["3330"], "keys": [], "unscanned": []}
    assert workshop_cli.main(["approve", "222", "6", "--configs", str(configs)]) == 0
    # freeze approved the current version, 2220, approve the 6
    assert workshop.read_approved(configs)[222]["manifests"] == ["5", "2220", "6"]
    # The file stays readable as the gate reads it
    approvals = workshop.load(configs)
    assert approvals is not None and "6" in approvals.manifests[222]
    # A reviewed false alarm of the scan
    arguments = ["approve", "222", "7", "--unscanned", "--configs", str(configs)]
    assert workshop_cli.main(arguments) == 0
    approvals = workshop.load(configs)
    assert approvals is not None and approvals.unscanned[222] == {"7"}
    assert "7" in approvals.manifests[222]


def test_keygen_sign_verify_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert workshop_cli.main(["keygen", "me", "--dir", str(tmp_path / "keys")]) == 0
    assert (tmp_path / "keys/me.key").stat().st_mode & 0o777 == 0o600
    path = build_vpk(tmp_path / "mod.vpk", FILES)
    assert workshop_cli.main(["verify", str(path)]) == 1
    assert workshop_cli.main(["sign", str(tmp_path / "keys/me.key"), str(path)]) == 0
    assert workshop_cli.main(["verify", str(tmp_path)]) == 0
    assert "valid, key" in capsys.readouterr().out


def test_notifications_go_to_the_own_queue(
    state: State, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NWI_NOTIFY_DIR", str(notify.UPDATE_QUEUE))
    notify.queue("subject", "body")
    assert [path.parent for path in notify.UPDATE_QUEUE.glob("*.json")] == [
        notify.UPDATE_QUEUE
    ]
