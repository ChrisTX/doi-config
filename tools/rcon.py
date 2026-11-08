#!/usr/bin/env python3
"""Run a command on a server over Source RCON and print its answer.

The password comes from RCON_PASSWORD, so it doesn't show up in the process list.

Usage: rcon.py [--host HOST] [--port PORT] COMMAND...
"""

import argparse
import os
import socket
import struct
import sys

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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=27015)
    parser.add_argument("command", nargs="+")
    args = parser.parse_args()
    password = os.environ.get("RCON_PASSWORD")
    if not password:
        print("RCON_PASSWORD isn't set", file=sys.stderr)
        return 2
    try:
        sock = connect(args.host, args.port, password)
    except PermissionError as error:
        print(error, file=sys.stderr)
        return 1
    with sock:
        print(run(sock, " ".join(args.command)), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
