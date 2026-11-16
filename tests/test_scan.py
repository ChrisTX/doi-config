"""The scan of workshop items' versions (scan.py), and the gate holding those with findings
(workshop.py), of files made here: well-formed ones of each checked format, and broken ones."""

import struct
from pathlib import Path

import pytest

from nwi_server_kit import scan, vpk, workshop

from .conftest import State


def bsp(lump: tuple[int, int] = (1036, 4)) -> bytes:
    """A map: its header with 64 lumps, the first at LUMP (offset, length), and 4 bytes of data."""
    lumps = struct.pack("<iiii", *lump, 0, 0) + bytes(63 * 16)
    return b"VBSP" + struct.pack("<i", 21) + lumps + struct.pack("<i", 1) + b"data"


def mdl(length: int | None = None) -> bytes:
    """A model's header, studiohdr_t up to its tables, with empty tables."""
    data = bytearray(200)
    data[:4] = b"IDST"
    struct.pack_into("<i", data, 4, 48)
    struct.pack_into("<i", data, 76, len(data) if length is None else length)
    return bytes(data)


def vtf(width: int = 256, height: int = 256) -> bytes:
    data = bytearray(80)
    data[:4] = b"VTF\0"
    struct.pack_into("<iii", data, 4, 7, 2, 80)
    struct.pack_into("<HH", data, 16, width, height)
    struct.pack_into("<H", data, 24, 1)
    data[56] = 9
    return bytes(data)


def wav(chunk: int = 4) -> bytes:
    return (
        b"RIFF"
        + struct.pack("<I", 16)
        + b"WAVE"
        + b"data"
        + struct.pack("<I", chunk)
        + b"abcd"
    )


GOOD = {
    "maps/m.bsp": bsp(),
    "maps/m.nav": struct.pack("<II", 0xFEEDFACE, 16),
    "models/a.mdl": mdl(),
    "materials/a.vtf": vtf(),
    "materials/a.vmt": b'"LightmappedGeneric" {}\n',
    "sound/a.wav": wav(),
    "sound/b.mp3": b"ID3\x04" + bytes(10),
    "resource/doi_english.txt": '﻿"lang" {}'.encode("utf-16-le"),
    "scripts/theaters/mod.theater": b'"theater" {}\n',
}


@pytest.mark.parametrize(
    ("path", "data", "finding"),
    [
        ("cfg/server.cfg", b"rcon_password x\n", "in cfg/"),
        ("addons/sourcemod/plugins/x.smx", b"x", "in addons/"),
        ("maps/x.so", b"\x7fELF", "a .so file in maps/"),
        ("server.dll", b"MZ", "at the top that isn't a VPK"),
        ("maps/m.bsp", bsp((1036, 1 << 20)), "lump 0"),
        ("maps/m.bsp", b"PK\x03\x04", "not a BSP"),
        ("models/a.mdl", mdl(9999), "the model's length"),
        ("materials/a.vtf", vtf(65535, 4), "a texture of 65535x4"),
        ("sound/a.wav", wav(1 << 20), "outside the file"),
        ("materials/a.vmt", b'"a" {\0}', "NUL bytes"),
    ],
)
def test_findings(tmp_path: Path, path: str, data: bytes, finding: str) -> None:
    for name, contents in {**GOOD, path: data}.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(contents)
    found = scan.scan(tmp_path)
    assert len(found) == 1 and found[0].startswith(path)
    assert finding in found[0]


@pytest.mark.parametrize(
    "path", ["maps/../cfg/a.txt", "/maps/a.bsp", "maps//a.bsp", "maps/a\x00.bsp"]
)
def test_paths_of_vpk_entries(path: str) -> None:
    """A VPK's entries are paths of their own, which the file system doesn't resolve."""
    assert scan.check_path(path, set()) is not None


def test_good_files_and_vpks(tmp_path: Path) -> None:
    """Well-formed files pass, loose and in a VPK; a VPK's entry that doesn't match its CRC doesn't."""
    content = tmp_path / "content"
    for name, data in GOOD.items():
        (content / name).parent.mkdir(parents=True, exist_ok=True)
        (content / name).write_bytes(data)
    assert scan.scan(content) == []
    item = tmp_path / "item"
    item.mkdir()
    vpk.pack(content, item / "mod.vpk")
    (item / ".DepotDownloader").mkdir()
    (item / ".DepotDownloader/record.bin").write_bytes(b"\0")
    assert scan.scan(item) == []
    # A byte of the theater's text changed after packing
    packed = bytearray((item / "mod.vpk").read_bytes())
    index = packed.rindex(b'"theater" {}')
    packed[index + 1] ^= 0x20
    (item / "mod.vpk").write_bytes(bytes(packed))
    found = scan.scan(item)
    assert found == [
        "mod.vpk/scripts/theaters/mod.theater: its CRC doesn't match its contents"
    ]


def test_the_gate_holds_findings_even_if_approved(state: State, tmp_path: Path) -> None:
    item = tmp_path / "item"
    (item / "cfg").mkdir(parents=True)
    (item / "cfg/server.cfg").write_text("sv_password x\n")
    approvals = workshop.Approvals(manifests={7: {"70"}})
    sources: dict[str, workshop.Approvals | None] = {"default": approvals}
    # Approved by its manifest, but held for the scan's finding, the admins told once
    assert not workshop.gate(state.layers, 7, "70", item, sources)
    assert not workshop.gate(state.layers, 7, "70", item, sources)
    assert state.notifications() == ["Workshop item 7 held: the scan found problems"]
    # Without approvals too
    assert not workshop.gate(state.layers, 7, "70", item, {"other": None})
    # Approved as unscanned, a reviewed false alarm, it passes
    approvals.unscanned[7] = {"70"}
    assert workshop.gate(state.layers, 7, "70", item, sources)
