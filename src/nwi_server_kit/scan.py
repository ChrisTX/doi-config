"""The scan of a workshop item's version before the servers serve it: only game content, in the
places the game reads it from, and files whose structure holds, so that a malformed or malicious
version, e.g. of a hijacked author's account, never reaches the players, whose clients parse what the
servers have (workshop.py holds a version that fails).

The checks, of the item's files and of the files in its VPKs:

- its paths: relative, without "..", of printable ASCII, in a folder the game reads content from
  (FOLDERS), with a type that folder has (e.g. maps/*.bsp, models/*.mdl), and at the top only VPKs. So
  no configs (cfg/), plugins (addons/), libraries or programs, which the server's search path would
  load as its own;
- the formats the game parses, by their headers: every offset and size within the file, and the
  dimensions and counts within the game's limits: BSP maps and their lumps, nav meshes, the models'
  MDL, VVD, VTX and PHY, VTF textures, WAV and MP3 sounds, binary particles (PCF); text files without
  NUL bytes but UTF-16 with its byte order mark;
- VPKs that can be read, their entries within their archives and matching their CRCs.

It's a defence in depth, not a proof: a file that is malformed in a way the headers don't show
passes. A false alarm is approved per version in workshop/approved.toml (unscanned, workshop.py).
"""

import re
import struct
from collections.abc import Callable
from pathlib import Path

from srctools.vpk import VPK

# The folders of content and the types each has, by their extensions (a model's VTX files are
# <name>.dx90.vtx and the like, so the last extension counts)
FOLDERS = {
    "maps": {"bsp", "nav", "txt", "ain", "lmp", "res"},
    "materials": {"vmt", "vtf", "txt"},
    "models": {"mdl", "vvd", "vtx", "phy", "ani"},
    "sound": {"wav", "mp3", "txt"},
    "scripts": {"txt", "theater", "playlist", "res", "vdf"},
    "resource": {"res", "txt"},
    "particles": {"pcf", "txt"},
}
# The files at an item's top: its VPKs; inside a VPK, nothing at the top
TOP = {"vpk"}
# A path's characters: printable ASCII but quotes, backslashes and the like
PATH = re.compile(r"[A-Za-z0-9 _\-.()\[\]+!&',@#~=]+")
# The most a texture's sides, a map's lumps and the like may be
MAX_TEXTURE = 16384
MAX_TEXT = 64 * 1024 * 1024
BSP_LUMPS = 64

Finding = str


def check_path(path: str, top: set[str]) -> Finding | None:
    """A file's path in an item or a VPK: why it isn't allowed, or None."""
    parts = path.replace("\\", "/").split("/")
    if path.startswith("/") or any(part in ("", ".", "..") for part in parts):
        return "not a plain relative path"
    if not all(PATH.fullmatch(part) for part in parts):
        return "characters outside printable ASCII"
    extension = parts[-1].rsplit(".", 1)[-1].lower() if "." in parts[-1] else ""
    if len(parts) == 1:
        return None if extension in top else "a file at the top that isn't a VPK"
    folder = parts[0].lower()
    if folder not in FOLDERS:
        return f"in {folder}/, which isn't a folder of content"
    if extension not in FOLDERS[folder]:
        return f"a .{extension or '(none)'} file in {folder}/"
    return None


def within(data: bytes, offset: int, length: int, what: str) -> None:
    if offset < 0 or length < 0 or offset + length > len(data):
        raise ValueError(
            f"{what} ({offset}+{length}) outside the file ({len(data)} bytes)"
        )


def ints(data: bytes, offset: int, count: int) -> tuple[int, ...]:
    within(data, offset, 4 * count, "the header")
    return struct.unpack_from(f"<{count}i", data, offset)


def check_bsp(data: bytes) -> None:
    if data[:4] != b"VBSP":
        raise ValueError("not a BSP (VBSP)")
    within(data, 0, 8 + BSP_LUMPS * 16, "the lumps' table")
    for lump in range(BSP_LUMPS):
        offset, length, _version, _code = struct.unpack_from(
            "<iiii", data, 8 + lump * 16
        )
        if length:
            within(data, offset, length, f"lump {lump}")


def check_nav(data: bytes) -> None:
    if len(data) < 8 or struct.unpack_from("<I", data)[0] != 0xFEEDFACE:
        raise ValueError("not a nav mesh (0xFEEDFACE)")


def check_mdl(data: bytes) -> None:
    if data[:4] != b"IDST":
        raise ValueError("not a model (IDST)")
    (version,) = ints(data, 4, 1)
    if not 44 <= version <= 53:
        raise ValueError(f"model version {version}")
    # studiohdr_t: id, version, checksum, name[64], length
    (length,) = ints(data, 76, 1)
    if length != len(data):
        raise ValueError(f"the model's length {length} isn't the file's {len(data)}")
    # The tables of bones, bone controllers, hitboxes, animations, sequences: count and offset each
    for field in range(156, 196, 8):
        count, offset = ints(data, field, 2)
        if count < 0 or (count and not 0 < offset < len(data)):
            raise ValueError(f"a table of the model at {offset} ({count})")


def check_vvd(data: bytes) -> None:
    if data[:4] != b"IDSV":
        raise ValueError("not a model's vertices (IDSV)")
    # The id, version and checksum, the levels of detail, their vertices (8), the fix-ups' count and
    # table, and the starts of the vertices and the tangents
    lods, *_ = ints(data, 12, 1)
    if not 0 < lods <= 8:
        raise ValueError(f"{lods} levels of detail")
    for start in ints(data, 52, 3):
        within(data, start, 0, "a table of the vertices")


def check_vtx(data: bytes) -> None:
    (version,) = ints(data, 0, 1)
    if version != 7:
        raise ValueError(f"not a model's strips (version {version})")
    # version, vertCacheSize, maxBonesPerStrip (2), maxBonesPerTri (2), maxBonesPerVert, checksum,
    # numLODs, materialReplacementListOffset, numBodyParts, bodyPartOffset
    lods, replacements, parts, offset = ints(data, 20, 4)
    if not 0 < lods <= 8 or parts < 0:
        raise ValueError(f"{lods} levels of detail, {parts} body parts")
    within(data, replacements, 0, "the material replacements")
    within(data, offset, 0, "the body parts")


def check_phy(data: bytes) -> None:
    size, _id, solids, _checksum = ints(data, 0, 4)
    if size != 16 or not 0 <= solids <= 1024:
        raise ValueError(f"not a model's physics (header {size}, {solids} solids)")


def check_vtf(data: bytes) -> None:
    if data[:4] != b"VTF\0":
        raise ValueError("not a texture (VTF)")
    major, minor, header = ints(data, 4, 3)
    if major != 7 or not 0 <= minor <= 5:
        raise ValueError(f"texture version {major}.{minor}")
    within(data, 0, header, "the texture's header")
    width, height = struct.unpack_from("<HH", data, 16)
    (frames,) = struct.unpack_from("<H", data, 24)
    mipmaps = data[56] if len(data) > 56 else 0
    if not (0 < width <= MAX_TEXTURE and 0 < height <= MAX_TEXTURE):
        raise ValueError(f"a texture of {width}x{height}")
    if frames == 0 or mipmaps > 16:
        raise ValueError(f"{frames} frames, {mipmaps} mipmaps")


def check_wav(data: bytes) -> None:
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a sound (RIFF WAVE)")
    offset = 12
    while offset + 8 <= len(data):
        size = struct.unpack_from("<I", data, offset + 4)[0]
        within(data, offset + 8, size, f"chunk {data[offset : offset + 4]!r}")
        offset += 8 + size + (size & 1)


def check_mp3(data: bytes) -> None:
    if not (
        data[:3] == b"ID3"
        or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)
    ):
        raise ValueError("not an MP3 (ID3 or a frame)")


def check_pcf(data: bytes) -> None:
    if not data.startswith(b"<!-- dmx encoding"):
        raise ValueError("not particles (DMX)")


def check_text(data: bytes) -> None:
    if len(data) > MAX_TEXT:
        raise ValueError(f"a text file of {len(data)} bytes")
    # UTF-16 with its byte order mark, e.g. the localisations (resource/<game>_<language>.txt), has
    # NUL bytes but UTF-16 with its byte order mark; other text has none
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        if len(data) % 2:
            raise ValueError("UTF-16 text of an odd length")
    elif b"\0" in data:
        raise ValueError("a text file with NUL bytes")


CHECKS: dict[str, Callable[[bytes], None]] = {
    "bsp": check_bsp,
    "nav": check_nav,
    "mdl": check_mdl,
    "vvd": check_vvd,
    "vtx": check_vtx,
    "phy": check_phy,
    "vtf": check_vtf,
    "wav": check_wav,
    "mp3": check_mp3,
    "pcf": check_pcf,
    **{
        text: check_text for text in ("txt", "res", "vmt", "theater", "playlist", "vdf")
    },
}


def check_file(path: str, data: bytes, top: set[str]) -> list[Finding]:
    """The findings of a file of an item or of a VPK."""
    problem = check_path(path, top)
    if problem:
        return [f"{path}: {problem}"]
    extension = path.rsplit(".", 1)[-1].lower()
    check = CHECKS.get(extension)
    if check is None:
        return []
    try:
        check(data)
    except (ValueError, struct.error) as error:
        return [f"{path}: {error}"]
    return []


def numbered_archive(name: str) -> bool:
    """Whether a file is a numbered archive of a VPK (<name>_000.vpk), read through its directory."""
    return re.search(r"_\d{3}\.vpk$", name) is not None


def scan(folder: Path) -> list[Finding]:
    """The findings of an item's version, its folder: empty if it passes."""
    findings = []
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if not path.is_file() or relative.parts[0] == ".DepotDownloader":
            continue
        name = relative.as_posix()
        if path.suffix.lower() == ".vpk":
            problem = check_path(name, TOP)
            if problem:
                findings.append(f"{name}: {problem}")
            elif not numbered_archive(path.name):
                findings += scan_vpk(path, name)
            continue
        findings += check_file(name, path.read_bytes(), TOP)
    return findings


def scan_vpk(path: Path, name: str) -> list[Finding]:
    findings = []
    try:
        archive = VPK(path)
        for entry in archive:
            # The path with its extension
            inner = entry.filename
            if not entry.verify():
                findings.append(f"{name}/{inner}: its CRC doesn't match its contents")
                continue
            findings += [
                f"{name}/{finding}"
                for finding in check_file(inner, entry.read(), set())
            ]
    except (OSError, ValueError, KeyError, struct.error, EOFError) as error:
        findings.append(f"{name}: can't be read as a VPK: {error}")
    return findings
