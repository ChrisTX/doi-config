"""ClamAV in the scan of workshop items (clamd.py, scan.py), against a fake clamd on a socket of the
test's: it finds a test signature in data with MARKER, and answers as clamd does when a stream
exceeds its limit."""

import socket
import struct
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from nwi_server_kit import clamd, scan

from .conftest import build_vpk

MARKER = b"NWI-TEST-SIGNATURE"
LIMIT = 4096


class FakeClamd:
    """clamd on a socket in a temporary folder: PING, VERSION and INSTREAM."""

    def __init__(self, folder: Path) -> None:
        self.path = str(folder / "clamd.ctl")
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(self.path)
        self.listener.listen()
        self.streams = 0
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self) -> None:
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            with conn:
                self.session(conn)

    def session(self, conn: socket.socket) -> None:
        command = b""
        while not command.endswith(b"\0"):
            command += conn.recv(1)
        if command == b"zPING\0":
            conn.sendall(b"PONG\0")
        elif command == b"zVERSION\0":
            conn.sendall(b"ClamAV fake\0")
        elif command == b"zINSTREAM\0":
            self.streams += 1
            data = b""
            while True:
                (size,) = struct.unpack(">I", self.read(conn, 4))
                if size == 0:
                    break
                data += self.read(conn, size)
                if len(data) > LIMIT:
                    conn.sendall(b"INSTREAM size limit exceeded. ERROR\0")
                    return
            if MARKER in data:
                conn.sendall(b"stream: Test.Signature FOUND\0")
            else:
                conn.sendall(b"stream: OK\0")

    @staticmethod
    def read(conn: socket.socket, size: int) -> bytes:
        data = b""
        while len(data) < size:
            data += conn.recv(size - len(data))
        return data


@pytest.fixture
def fake(tmp_path: Path) -> Iterator[FakeClamd]:
    server = FakeClamd(tmp_path)
    yield server
    server.listener.close()


def test_socket_path(tmp_path: Path) -> None:
    """NWI_CLAMD, off, or clamd's LocalSocket, or its default."""
    config = tmp_path / "clamd.conf"
    config.write_text("# a comment\nLocalSocket /run/clamd.sock\nUser clamav\n")
    assert clamd.socket_path({"NWI_CLAMD": "off"}, config) is None
    assert clamd.socket_path({"NWI_CLAMD": "/x.ctl"}, config) == "/x.ctl"
    assert clamd.socket_path({}, config) == "/run/clamd.sock"
    assert clamd.socket_path({}, tmp_path / "none") == clamd.DEFAULT_SOCKET


def test_scan(fake: FakeClamd) -> None:
    assert clamd.command(fake.path, "VERSION") == "ClamAV fake"
    assert clamd.scan(fake.path, b"abc" + MARKER) == "Test.Signature"
    assert clamd.scan(fake.path, b"clean") is None
    # In chunks
    assert clamd.scan(fake.path, bytes(3000) + MARKER) == "Test.Signature"
    with pytest.raises(clamd.TooLarge):
        clamd.scan(fake.path, bytes(LIMIT * 4))


def test_unreachable(tmp_path: Path) -> None:
    with pytest.raises(clamd.ClamdError, match="can't reach clamd"):
        clamd.scan(str(tmp_path / "none.ctl"), b"x")


def item(folder: Path) -> Path:
    """An item with a clean map, a sound with the marker, and a VPK with the marker in a model."""
    (folder / "maps").mkdir(parents=True)
    (folder / "sound").mkdir()
    (folder / "maps/clean.txt").write_text('"cpsetup.txt" { }\n')
    (folder / "sound/bad.txt").write_bytes(b"text " + MARKER)
    build_vpk(
        folder / "pak.vpk",
        {"materials/a.vmt": b'"LightmappedGeneric" { }', "scripts/x.txt": MARKER},
    )
    return folder


def test_findings(fake: FakeClamd, tmp_path: Path) -> None:
    """Every loose file and every file in a VPK, by its path."""
    findings = scan.scan(item(tmp_path / "item"), fake.path)
    assert findings == [
        "pak.vpk/scripts/x.txt: ClamAV: Test.Signature",
        "sound/bad.txt: ClamAV: Test.Signature",
    ]
    assert fake.streams == 4


def test_too_large(
    fake: FakeClamd, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A file larger than clamd scans is noted, not held."""
    folder = tmp_path / "item"
    (folder / "maps").mkdir(parents=True)
    (folder / "maps/big.txt").write_text("x" * (LIMIT * 2))
    assert scan.scan(folder, fake.path) == []
    assert "larger than clamd scans" in capsys.readouterr().err


def test_without_clamd(tmp_path: Path) -> None:
    """Without clamd the scan fails, once; without ClamAV on purpose it doesn't ask."""
    folder = item(tmp_path / "item")
    findings = scan.scan(folder, str(tmp_path / "none.ctl"))
    assert len(findings) == 1 and "NWI_CLAMD=off" in findings[0]
    assert scan.scan(folder, None) == []
    # The default: the settings, off in the tests
    assert scan.scan(folder) == []
