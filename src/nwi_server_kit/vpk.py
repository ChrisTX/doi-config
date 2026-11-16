"""The signatures of VPK files (version 2), as the Source engine and Valve's vpk tool make them.

A version 2 directory (<name>_dir.vpk, or a VPK of one file with its data embedded) has, after its
header, the tree of its files and their data: the checksums of its archives' chunks (<name>_NNN.vpk,
MD5 of each 1 MiB), the MD5 of the tree, of the chunks' checksums and of the file up to there, and the
public key and signature: RSA, PKCS#1 v1.5 with SHA-256, of the file up to the signature. So a valid
signature covers every byte of the VPK, its archives through their chunks' checksums. Source 1 reads
the legacy layout only (a key's and a signature's size, then each); its own keys are 1024-bit.
"""

import hashlib
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

MAGIC = 0x55AA1234
HEADER = struct.Struct("<7I")
CHUNK = struct.Struct("<HHII16s")
CHUNK_SIZE = 1024 * 1024
# The archive index of a file whose data is embedded in the directory
EMBEDDED = 0x7FFF
OTHER_MD5_SIZE = 48


class VPKError(ValueError):
    """A VPK that can't be read, or whose signature or checksums don't hold."""


@dataclass(frozen=True)
class Entry:
    """A file of a VPK: its path, its archive (EMBEDDED for the directory's own data), offset and
    length there."""

    path: str
    archive: int
    offset: int
    length: int


@dataclass(frozen=True)
class Directory:
    """A version 2 VPK directory: its bytes, the sizes of its sections and its files."""

    data: bytes
    tree: int
    file_data: int
    archive_md5: int
    other_md5: int
    signature: int
    entries: list[Entry]

    @property
    def archive_md5_start(self) -> int:
        return HEADER.size + self.tree + self.file_data

    @property
    def other_md5_start(self) -> int:
        return self.archive_md5_start + self.archive_md5

    @property
    def signature_start(self) -> int:
        return self.other_md5_start + self.other_md5


def read_string(data: bytes, offset: int) -> tuple[str, int]:
    end = data.index(b"\0", offset)
    return data[offset:end].decode("utf-8", "replace"), end + 1


def parse(path: Path) -> Directory:
    """Read a version 2 VPK directory."""
    data = path.read_bytes()
    if len(data) < HEADER.size:
        raise VPKError(f"{path}: too short for a VPK")
    magic, version, tree, file_data, archive_md5, other_md5, signature = (
        HEADER.unpack_from(data)
    )
    if magic != MAGIC or version != 2:
        raise VPKError(f"{path}: not a version 2 VPK (version {version})")
    if HEADER.size + tree + file_data + archive_md5 + other_md5 + signature != len(
        data
    ):
        raise VPKError(f"{path}: its sections don't add up to its size")
    entries = []
    offset = HEADER.size
    try:
        while True:
            extension, offset = read_string(data, offset)
            if not extension:
                break
            while True:
                folder, offset = read_string(data, offset)
                if not folder:
                    break
                while True:
                    name, offset = read_string(data, offset)
                    if not name:
                        break
                    _, preload, archive, entry_offset, length, terminator = (
                        struct.unpack_from("<IHHIIH", data, offset)
                    )
                    if terminator != 0xFFFF:
                        raise VPKError(f"{path}: a broken entry in its tree")
                    offset += 18 + preload
                    file_path = "/".join(
                        part for part in (folder.strip(), name) if part
                    )
                    # A space is a file without an extension
                    if extension.strip():
                        file_path = f"{file_path}.{extension}"
                    entries.append(Entry(file_path, archive, entry_offset, length))
    except (ValueError, struct.error) as error:
        raise VPKError(f"{path}: its tree can't be read: {error}") from error
    if offset != HEADER.size + tree:
        raise VPKError(f"{path}: its tree isn't its header's size")
    return Directory(data, tree, file_data, archive_md5, other_md5, signature, entries)


def archive_path(directory: Path, index: int) -> Path:
    """The archive of an index of a <name>_dir.vpk."""
    return directory.with_name(directory.name.replace("_dir.vpk", f"_{index:03}.vpk"))


def verify(path: Path) -> bytes:
    """Verify a VPK's signature and checksums, of its archives too, and that its files' data is all
    covered by them; returns the signing key (DER). An error if anything doesn't hold, also for a VPK
    without a signature."""
    vpk = parse(path)
    if vpk.signature == 0:
        raise VPKError(f"{path}: not signed")
    data = vpk.data
    start = vpk.signature_start
    try:
        (key_size,) = struct.unpack_from("<I", data, start)
        if key_size == MAGIC:
            raise VPKError(f"{path}: a signature of Source 2's layout")
        key = data[start + 4 : start + 4 + key_size]
        (signature_size,) = struct.unpack_from("<I", data, start + 4 + key_size)
        signature = data[start + 8 + key_size : start + 8 + key_size + signature_size]
    except struct.error as error:
        raise VPKError(f"{path}: its signature can't be read") from error
    if start + 8 + key_size + signature_size != len(data):
        raise VPKError(f"{path}: its signature isn't its section's size")
    try:
        public_key = serialization.load_der_public_key(key)
        if not isinstance(public_key, rsa.RSAPublicKey):
            raise VPKError(f"{path}: not an RSA key")
        public_key.verify(signature, data[:start], padding.PKCS1v15(), hashes.SHA256())
    except (ValueError, InvalidSignature) as error:
        raise VPKError(f"{path}: the signature isn't valid") from error
    check_md5(path, vpk)
    return key


def check_md5(path: Path, vpk: Directory) -> None:
    """Check the checksums of the tree, of the chunks' checksums, of the file, and of the archives'
    chunks, and that every file's data in an archive is in a checked chunk."""
    data = vpk.data
    other = vpk.other_md5_start
    if vpk.other_md5 != OTHER_MD5_SIZE:
        raise VPKError(f"{path}: no checksums")
    tree_md5, chunks_md5, file_md5 = (
        data[other + i : other + i + 16] for i in (0, 16, 32)
    )
    if hashlib.md5(data[HEADER.size : HEADER.size + vpk.tree]).digest() != tree_md5:
        raise VPKError(f"{path}: its tree's checksum doesn't hold")
    if hashlib.md5(data[vpk.archive_md5_start : other]).digest() != chunks_md5:
        raise VPKError(f"{path}: its chunks' checksums don't hold")
    if hashlib.md5(data[: other + 32]).digest() != file_md5:
        raise VPKError(f"{path}: its checksum doesn't hold")
    if vpk.archive_md5 % CHUNK.size:
        raise VPKError(f"{path}: its chunks' checksums are broken")
    checked: dict[int, list[tuple[int, int]]] = {}
    archives: dict[int, bytes] = {}
    for index in range(vpk.archive_md5 // CHUNK.size):
        archive, kind, offset, count, md5 = CHUNK.unpack_from(
            data, vpk.archive_md5_start + index * CHUNK.size
        )
        if kind != 0:
            raise VPKError(f"{path}: a checksum other than MD5")
        if archive not in archives:
            archive_file = archive_path(path, archive)
            if not archive_file.is_file():
                raise VPKError(f"{path}: its archive {archive_file.name} is missing")
            archives[archive] = archive_file.read_bytes()
        if hashlib.md5(archives[archive][offset : offset + count]).digest() != md5:
            raise VPKError(f"{path}: a chunk of its archive {archive} doesn't hold")
        checked.setdefault(archive, []).append((offset, offset + count))
    for entry in vpk.entries:
        if entry.archive == EMBEDDED:
            if entry.offset + entry.length > vpk.file_data:
                raise VPKError(f"{path}: {entry.path} is beyond its data")
            continue
        end = entry.offset + entry.length
        if not any(
            start <= entry.offset and end <= stop
            for start, stop in checked.get(entry.archive, [])
        ) and not covered(checked.get(entry.archive, []), entry.offset, end):
            raise VPKError(
                f"{path}: {entry.path} isn't in its archive's checked chunks"
            )


def covered(ranges: list[tuple[int, int]], start: int, end: int) -> bool:
    """Whether the ranges, joined, cover start to end."""
    position = start
    for range_start, range_end in sorted(ranges):
        if range_start <= position < range_end:
            position = range_end
        if position >= end:
            return True
    return position >= end


def files_of(folder: Path) -> list[Path]:
    """The VPK directories of a folder: <name>_dir.vpk, and VPKs that aren't another's archive."""
    found = []
    for path in sorted(folder.rglob("*.vpk")):
        stem = path.stem
        is_archive = (
            len(stem) > 4
            and stem[-4] == "_"
            and stem[-3:].isdigit()
            and (path.with_name(f"{stem[:-4]}_dir.vpk")).is_file()
        )
        if not is_archive:
            found.append(path)
    return found


def key_name(key: bytes) -> str:
    """A short fingerprint of a public key (DER): the start of its SHA-256."""
    return hashlib.sha256(key).hexdigest()[:16]


def public_der(pem: bytes) -> bytes:
    """A public key of a PEM file, as DER."""
    key = serialization.load_pem_public_key(pem)
    return key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def keygen(bits: int = 2048) -> tuple[bytes, bytes]:
    """A new RSA key pair: the private key and the public key, as PEM."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private, public


def sign(path: Path, private_pem: bytes, password: bytes | None = None) -> bytes:
    """Sign a version 2 VPK in place with a private key (PEM), replacing a signature it has: its
    checksums are made anew, and its archives' chunks are checksummed if it has archives without;
    returns the public key (DER)."""
    vpk = parse(path)
    key = serialization.load_pem_private_key(private_pem, password)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise VPKError("not an RSA key")
    public = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    data = vpk.data
    body = data[HEADER.size : vpk.archive_md5_start]
    chunks = data[vpk.archive_md5_start : vpk.other_md5_start]
    archived = sorted(
        {entry.archive for entry in vpk.entries if entry.archive != EMBEDDED}
    )
    if archived and not chunks:
        chunks = b"".join(
            CHUNK.pack(index, 0, offset, len(part), hashlib.md5(part).digest())
            for index in archived
            for offset, part in chunk_parts(archive_path(path, index).read_bytes())
        )
    signature_size = 8 + len(public) + key.key_size // 8
    header = HEADER.pack(
        MAGIC, 2, vpk.tree, vpk.file_data, len(chunks), OTHER_MD5_SIZE, signature_size
    )
    unsigned = header + body + chunks
    tree_md5 = hashlib.md5(body[: vpk.tree]).digest()
    chunks_md5 = hashlib.md5(chunks).digest()
    unsigned += tree_md5 + chunks_md5
    unsigned += hashlib.md5(unsigned).digest()
    signature = key.sign(unsigned, padding.PKCS1v15(), hashes.SHA256())
    section = (
        struct.pack("<I", len(public)) + public + struct.pack("<I", len(signature))
    )
    path.write_bytes(unsigned + section + signature)
    return public


def pack(folder: Path, output: Path) -> int:
    """Pack a folder's files, but those starting with a dot, e.g. .git, into an unsigned version 2
    VPK of one file, their data embedded, as a mod's for the Workshop; returns how many files."""
    files = sorted(
        path
        for path in folder.rglob("*")
        if path.is_file()
        and not any(part.startswith(".") for part in path.relative_to(folder).parts)
    )
    # The tree: by extension, then folder, then name
    tree_of: dict[str, dict[str, list[Path]]] = {}
    for path in files:
        relative = path.relative_to(folder)
        extension = relative.suffix.removeprefix(".") or " "
        parent = relative.parent.as_posix()
        tree_of.setdefault(extension, {}).setdefault(
            " " if parent == "." else parent, []
        ).append(path)
    tree = b""
    data = bytearray()
    for extension, folders in sorted(tree_of.items()):
        tree += extension.encode() + b"\0"
        for parent, paths in sorted(folders.items()):
            tree += parent.encode() + b"\0"
            for path in paths:
                content = path.read_bytes()
                stem = path.name[: -len(path.suffix)] if path.suffix else path.name
                tree += stem.encode() + b"\0"
                tree += struct.pack(
                    "<IHHIIH",
                    zlib.crc32(content),
                    0,
                    EMBEDDED,
                    len(data),
                    len(content),
                    0xFFFF,
                )
                data += content
            tree += b"\0"
        tree += b"\0"
    tree += b"\0"
    header = HEADER.pack(MAGIC, 2, len(tree), len(data), 0, OTHER_MD5_SIZE, 0)
    unsigned = header + tree + bytes(data)
    unsigned += hashlib.md5(tree).digest() + hashlib.md5(b"").digest()
    unsigned += hashlib.md5(unsigned).digest()
    output.write_bytes(unsigned)
    return len(files)


def chunk_parts(data: bytes) -> list[tuple[int, bytes]]:
    """An archive's chunks: its offsets and bytes, CHUNK_SIZE each."""
    return [
        (offset, data[offset : offset + CHUNK_SIZE])
        for offset in range(0, len(data), CHUNK_SIZE)
    ]
