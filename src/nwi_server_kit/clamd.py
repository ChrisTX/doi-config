"""ClamAV's daemon, clamd, as the workshop items' scan uses it (scan.py): each file's bytes are streamed
to it over its socket (INSTREAM), so it needs no access to the files, and VPKs are scanned by their
entries, which ClamAV can't read inside a VPK. It takes the signatures clamd has, e.g. the official
ones and SecuriteInfo's.

The socket is NWI_CLAMD's, or clamd's own (LocalSocket of /etc/clamav/clamd.conf, by default
/run/clamav/clamd.ctl). NWI_CLAMD=off scans without ClamAV, e.g. in the container image, which has no
clamd.
"""

import os
import socket
import struct
from pathlib import Path

CONFIG = Path("/etc/clamav/clamd.conf")
DEFAULT_SOCKET = "/run/clamav/clamd.ctl"
# The bytes a chunk of the stream has; clamd takes up to its StreamMaxLength in all
CHUNK = 1 << 20
TIMEOUT = 120


class ClamdError(Exception):
    """clamd can't be reached, or didn't scan a file, with the reason."""


class TooLarge(ClamdError):
    """A file larger than clamd scans (StreamMaxLength)."""


def socket_path(
    environ: dict[str, str] | None = None, config: Path = CONFIG
) -> str | None:
    """clamd's socket, see the module's documentation; None with NWI_CLAMD=off."""
    environ = dict(os.environ) if environ is None else environ
    setting = environ.get("NWI_CLAMD", "")
    if setting == "off":
        return None
    if setting:
        return setting
    try:
        for line in config.read_text().splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0] == "LocalSocket":
                return parts[1].strip()
    except OSError:
        pass
    return DEFAULT_SOCKET


def command(path: str, text: str) -> str:
    """A command without data, e.g. PING or VERSION, and clamd's answer."""
    with connect(path) as sock:
        sock.sendall(f"z{text}\0".encode())
        return answer(sock)


def scan(path: str, data: bytes) -> str | None:
    """The signature clamd finds in data, or None; a ClamdError if it doesn't scan them."""
    with connect(path) as sock:
        sock.sendall(b"zINSTREAM\0")
        try:
            for start in range(0, len(data), CHUNK):
                chunk = data[start : start + CHUNK]
                sock.sendall(struct.pack(">I", len(chunk)) + chunk)
            sock.sendall(struct.pack(">I", 0))
        except (BrokenPipeError, ConnectionResetError):
            # clamd stops reading once a stream exceeds its limit, and answers why
            pass
        reply = answer(sock)
    if reply.endswith(" FOUND"):
        return reply.removeprefix("stream: ").removesuffix(" FOUND")
    if reply == "stream: OK":
        return None
    if "size limit exceeded" in reply:
        raise TooLarge(reply)
    raise ClamdError(reply)


def connect(path: str) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT)
    try:
        sock.connect(path)
    except OSError as error:
        sock.close()
        raise ClamdError(
            f"can't reach clamd at {path}: {error.strerror or error}"
        ) from error
    return sock


def answer(sock: socket.socket) -> str:
    """clamd's answer, up to its NUL."""
    data = b""
    while not data.endswith(b"\0"):
        try:
            chunk = sock.recv(4096)
        except OSError as error:
            raise ClamdError(f"no answer from clamd: {error}") from error
        if not chunk:
            break
        data += chunk
    return data.rstrip(b"\0").decode(errors="replace").strip()
