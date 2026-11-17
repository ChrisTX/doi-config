"""The fixtures of the tests: a fake updater's state of layers and a fake /run, in a temporary folder,
which layers.py, health.py and notify.py use instead of the system's, and the C compiler, which builds
the tests' stand-ins of libraries, and VPKs."""

import hashlib
import json
import shutil
import struct
import subprocess
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from nwi_server_kit import health, layers, notify, vpk


@dataclass
class State:
    """The fake state: the layers, the source the versions are copies of, and the server's files."""

    root: Path
    layers: Path
    source: Path

    def version(self, layer: str, version: str, good: bool = False) -> Path:
        """A version of a layer, on trial, or good."""
        path = layers.snapshot(self.source, layers.folder(self.layers, layer), version)
        return layers.renamed(path, None) if good else path

    def mounted(
        self, name: str, versions: list[Path], core: list[Path], maps: dict[str, Path]
    ) -> None:
        """A server's record of its versions, as mount.py writes it, and its health folder."""
        health.IN_USE.mkdir(parents=True, exist_ok=True)
        (health.RUN / name).mkdir(parents=True, exist_ok=True)

        def canonical(path: Path) -> str:
            return str(layers.canonical(path))

        record = {
            "versions": [canonical(path) for path in versions],
            "core": [canonical(path) for path in core],
            "maps": {map_name: canonical(path) for map_name, path in maps.items()},
        }
        (health.IN_USE / name).write_text(json.dumps(record))

    def status(self, name: str, invocation: str, **values: object) -> None:
        """The status the server's watchdog writes."""
        status = {
            "invocation": invocation,
            "ready": True,
            "map": None,
            "busy_seconds": 0,
            "completed": [],
        }
        (health.RUN / name / "status.json").write_text(json.dumps(status | values))

    def notifications(self) -> list[str]:
        """The subjects of the queued notifications."""
        if not notify.QUEUE.is_dir():
            return []
        return [
            json.loads(path.read_text())["subject"]
            for path in sorted(notify.QUEUE.glob("*.json"))
        ]


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> State:
    root = tmp_path
    (root / "layers").mkdir()
    source = root / "source"
    source.mkdir()
    (source / "file").write_text("content\n")
    monkeypatch.setattr(layers, "IN_USE", root / "run/in-use")
    monkeypatch.setattr(health, "IN_USE", root / "run/in-use")
    monkeypatch.setattr(health, "RUN", root / "run/health")
    monkeypatch.setattr(health, "STATE", root / "state")
    monkeypatch.setattr(health, "LAYERS", root / "layers")
    monkeypatch.setattr(notify, "QUEUE", root / "run/notify")
    monkeypatch.setattr(notify, "UPDATE_QUEUE", root / "run/notify-update")
    monkeypatch.delenv("NWI_NOTIFY_DIR", raising=False)
    for variable in (
        "NWI_TRIES",
        "NWI_KEEP_VERSIONS",
        "NWI_BLESS_PLAYERS",
        "NWI_BLESS_MINUTES",
    ):
        monkeypatch.delenv(variable, raising=False)
    return State(root, root / "layers", source)


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], str]:
    """Set the server's run, systemd's INVOCATION_ID, as ExecStopPost= has it."""

    def start(invocation: str) -> str:
        monkeypatch.setenv("INVOCATION_ID", invocation)
        return invocation

    return start


@pytest.fixture(scope="session")
def build_library() -> Callable[[Path, Path], Path]:
    """Build a shared library of a C source with the C compiler; the test is skipped without one."""
    compiler = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")

    def build(source: Path, library: Path) -> Path:
        if compiler is None:
            pytest.skip("no C compiler")
        command = [compiler, "-shared", "-fPIC", "-Wall", "-Werror", "-o"]
        subprocess.run([*command, str(library), str(source)], check=True)
        return library

    return build


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
