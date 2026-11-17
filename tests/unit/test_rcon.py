"""Source RCON (rcon.py) and nwi-rcon (cli/rcon.py), against a fake server that answers as the
game's does: an empty response before the authentication's answer, long answers in several packets,
and the empty command's answer in two."""

import socket
import struct
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from nwi_server_kit import rcon
from nwi_server_kit.cli import rcon as rcon_cli

PASSWORD = "secret"
# The game sends an answer in packets of at most 4096 bytes
PACKET = 4096


@dataclass
class FakeServer:
    """A server's RCON on a port of 127.0.0.1, which answers a command with ANSWERS' text, or echoes
    it; with CLOSE, it closes each connection at once."""

    answers: dict[str, str] = field(default_factory=dict)
    close: bool = False
    commands: list[str] = field(default_factory=list)
    port: int = 0

    def __post_init__(self) -> None:
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self) -> None:
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            with conn:
                if not self.close:
                    self.session(conn)

    def session(self, conn: socket.socket) -> None:
        try:
            while True:
                request_id, kind, body = rcon.receive(conn)
                if kind == rcon.SERVERDATA_AUTH:
                    rcon.send(conn, request_id, 0, "")
                    accepted = body == PASSWORD
                    rcon.send(
                        conn,
                        request_id if accepted else -1,
                        rcon.SERVERDATA_AUTH_RESPONSE,
                        "",
                    )
                    if not accepted:
                        return
                elif body:
                    self.commands.append(body)
                    answer = self.answers.get(body, f"echo {body}\n")
                    for start in range(0, len(answer), PACKET):
                        rcon.send(conn, request_id, 0, answer[start : start + PACKET])
                else:
                    # The empty command's answer: an empty packet, then one whose body is
                    # 00 00 00 01 00 00 00 00, as Valve's documentation of the protocol has it
                    rcon.send(conn, request_id, 0, "")
                    quirk = b"\0\0\0\1\0\0\0\0"
                    packet = struct.pack("<ii", request_id, 0) + quirk
                    conn.sendall(struct.pack("<i", len(packet)) + packet)
        except ConnectionError:
            return


@pytest.fixture
def server() -> Iterator[FakeServer]:
    fake = FakeServer()
    yield fake
    fake.listener.close()


def test_command(server: FakeServer) -> None:
    with rcon.connect("127.0.0.1", server.port, PASSWORD) as sock:
        assert rcon.run(sock, "status") == "echo status\n"
        # The empty command's second packet doesn't end up in the next answer
        assert rcon.run(sock, "sm plugins list") == "echo sm plugins list\n"
    assert server.commands == ["status", "sm plugins list"]


def test_long_answer(server: FakeServer) -> None:
    """An answer of several packets is joined."""
    server.answers["cvarlist"] = "".join(f'cvar_{n} : 1 : , "sv"\n' for n in range(900))
    assert len(server.answers["cvarlist"]) > 3 * PACKET
    with rcon.connect("127.0.0.1", server.port, PASSWORD) as sock:
        assert rcon.run(sock, "cvarlist") == server.answers["cvarlist"]


def test_wrong_password(server: FakeServer) -> None:
    with pytest.raises(PermissionError, match="password is wrong"):
        rcon.connect("127.0.0.1", server.port, "wrong")


def test_closed(server: FakeServer) -> None:
    """A server that closes the connection, as one that's starting or stopping does."""
    server.close = True
    # Closed, or reset when the password was still unread
    with pytest.raises(ConnectionError):
        rcon.connect("127.0.0.1", server.port, PASSWORD)


def test_cli_password(
    server: FakeServer,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The password of RCON_PASSWORD; the command's words joined by spaces."""
    monkeypatch.delenv("RCON_PASSWORD", raising=False)
    assert rcon_cli.main(["--port", str(server.port), "status"]) == 2
    assert "RCON_PASSWORD isn't set" in capsys.readouterr().err
    monkeypatch.setenv("RCON_PASSWORD", PASSWORD)
    assert rcon_cli.main(["--port", str(server.port), "sm", "version"]) == 0
    assert capsys.readouterr().out == "echo sm version\n"
    monkeypatch.setenv("RCON_PASSWORD", "wrong")
    assert rcon_cli.main(["--port", str(server.port), "status"]) == 1
    assert "password is wrong" in capsys.readouterr().err


def test_cli_server(
    server: FakeServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--server: the password of the server's file, the port of its environment file."""
    monkeypatch.setattr(rcon, "RCON_DIR", tmp_path / "rcon")
    monkeypatch.setenv("NWI_SERVERS_DIR", str(tmp_path / "servers"))
    (tmp_path / "rcon").mkdir()
    (tmp_path / "servers").mkdir()
    (tmp_path / "rcon/coop").write_text(PASSWORD + "\n")
    (tmp_path / "servers/coop.env").write_text(f"SERVER_PORT={server.port}\n")
    assert rcon_cli.main(["--server", "coop", "status"]) == 0
    assert capsys.readouterr().out == "echo status\n"
    assert rcon_cli.main(["--server", "pvp", "status"]) == 1
    assert "nwi-rcon: pvp:" in capsys.readouterr().err


def test_cli_unreachable(
    server: FakeServer,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A server that's down or closes the connection is a message, not a traceback."""
    monkeypatch.setenv("RCON_PASSWORD", PASSWORD)
    server.close = True
    assert rcon_cli.main(["--port", str(server.port), "status"]) == 1
    # Closed, or reset when the password was still unread
    assert f"nwi-rcon: 127.0.0.1:{server.port}: " in capsys.readouterr().err
    # A port nothing listens on: bound, but not listening
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        port = unused.getsockname()[1]
        assert rcon_cli.main(["--port", str(port), "status"]) == 1
    assert f"127.0.0.1:{port}: Connection refused" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("args", "error"),
    [
        (["--server", "../x", "status"], "not a server's name"),
        (["--ssh", "admin@example.org", "status"], "--ssh needs --server"),
    ],
)
def test_cli_refuses(
    args: list[str], error: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        rcon_cli.main(args)
    assert error in capsys.readouterr().err


def test_cli_ssh(monkeypatch: pytest.MonkeyPatch) -> None:
    """--ssh runs nwi-rcon --server on the other machine, the command quoted for its shell."""
    ran: list[list[str]] = []

    def fake_run(command: list[str], check: bool) -> object:
        ran.append(command)
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(rcon_cli.subprocess, "run", fake_run)
    argv = ["--ssh", "admin@host", "--server", "coop", "say", "it's up"]
    assert rcon_cli.main(argv) == 0
    assert ran == [
        ["ssh", "admin@host", "nwi-rcon --server coop -- say 'it'\"'\"'s up'"]
    ]
