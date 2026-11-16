#!/usr/bin/env python3
"""Run a command on a server over Source RCON and print its answer.

The password comes from RCON_PASSWORD, so it doesn't show up in the process list, or with --server
from the server of nwi-server@.service on this machine: its password from /run/nwi-server/rcon/<server>,
which the members of the group nwi-rcon can read (tools/prepare_server.sh), and its port, SERVER_PORT
of /etc/nwi-server/<server>.env. With --ssh, the command runs on another machine instead, as nwi-rcon
--server there: the password stays on it, and its RCON port needs no opening.

Installed as nwi-rcon, e.g. nwi-rcon --server coop-commando status, or
nwi-rcon --ssh admin@example.org --server coop-commando sm plugins list.
"""

import argparse
import os
import shlex
import socket
import struct
import subprocess
import sys
from pathlib import Path

from games import read_env

SERVERDATA_AUTH = 3
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_EXECCOMMAND = 2


def send(sock: socket.socket, request_id: int, kind: int, body: str) -> None:
    """Send a packet: its size, ID, type and the null-terminated body with an empty string after it."""
    data = struct.pack("<ii", request_id, kind) + body.encode() + b"\0\0"
    sock.sendall(struct.pack("<i", len(data)) + data)


def receive(sock: socket.socket) -> tuple[int, int, str]:
    """Receive a packet's ID, type and body."""

    def read(size: int) -> bytes:
        data = b""
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError("the server closed the connection")
            data += chunk
        return data

    (size,) = struct.unpack("<i", read(4))
    data = read(size)
    request_id, kind = struct.unpack("<ii", data[:8])
    return request_id, kind, data[8:-2].decode(errors="replace")


def connect(host: str, port: int, password: str) -> socket.socket:
    """Connect to a server's RCON and authenticate; a wrong password is a PermissionError."""
    sock = socket.create_connection((host, port), timeout=10)
    send(sock, 1, SERVERDATA_AUTH, password)
    # The server answers the authentication with an empty response value first
    while True:
        request_id, kind, _ = receive(sock)
        if kind == SERVERDATA_AUTH_RESPONSE:
            break
    if request_id == -1:
        sock.close()
        raise PermissionError("The RCON password is wrong")
    return sock


def run(sock: socket.socket, command: str) -> str:
    """Run a command and return its answer."""
    # An answer can take several packets: an empty command after it marks its end, as the server
    # answers commands in order
    send(sock, 2, SERVERDATA_EXECCOMMAND, command)
    send(sock, 3, SERVERDATA_EXECCOMMAND, "")
    answer = []
    while True:
        request_id, _, body = receive(sock)
        if request_id != 2:
            break
        answer.append(body)
    # The answer to the empty command can take a second packet
    sock.settimeout(0.05)
    try:
        while True:
            receive(sock)
    except TimeoutError:
        pass
    finally:
        sock.settimeout(10)
    return "".join(answer)


def main() -> int:
    """Authenticate, run the command and print the answer."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="the server's address (%(default)s)"
    )
    parser.add_argument(
        "--port", type=int, help="the server's port (27015, or SERVER_PORT of --server)"
    )
    parser.add_argument(
        "--server",
        metavar="NAME",
        help="a server of nwi-server@.service: its password and port, see above",
    )
    parser.add_argument(
        "--ssh",
        metavar="HOST",
        help="run it with --server on HOST over SSH, e.g. admin@example.org",
    )
    parser.add_argument(
        "command",
        nargs="+",
        metavar="COMMAND",
        help="the command and its arguments, joined by spaces",
    )
    args = parser.parse_args()
    if args.server is not None and ("/" in args.server or args.server.startswith(".")):
        parser.error(f"not a server's name: {args.server}")
    if args.ssh is not None:
        if args.server is None:
            parser.error("--ssh needs --server")
        remote = ["nwi-rcon", "--server", args.server, "--", *args.command]
        # ssh passes the command to the remote shell as one string
        return subprocess.run(
            ["ssh", args.ssh, shlex.join(remote)], check=False
        ).returncode
    port = args.port
    password: str | None
    if args.server is not None:
        try:
            password = Path(f"/run/nwi-server/rcon/{args.server}").read_text().strip()
            env = Path(f"/etc/nwi-server/{args.server}.env")
            settings = read_env(env) if env.is_file() else {}
        except OSError as error:
            print(f"nwi-rcon: {args.server}: {error}", file=sys.stderr)
            return 1
        if port is None:
            port = int(settings.get("SERVER_PORT", "27015"))
    else:
        password = os.environ.get("RCON_PASSWORD")
        if not password:
            print("RCON_PASSWORD isn't set", file=sys.stderr)
            return 2
    try:
        sock = connect(args.host, port or 27015, password)
    except PermissionError as error:
        print(error, file=sys.stderr)
        return 1
    with sock:
        print(run(sock, " ".join(args.command)), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
