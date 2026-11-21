"""The stress test's packets and checks (tests/integration/stress.py), without a network: what it sends,
how it reads the server's stats and the table's counters, and what fails it."""

import json
import random
import socket
import struct

from tests.integration import stress

STATS = (
    "CPU   In    Out   Uptime  Users   FPS    Players\n"
    " 0.00  0.00  0.00       3     0   63.87       0\n"
    'L 11/21/2026 - 02:39:49: rcon from "10.201.0.1:51968": command "stats"\n'
)


def test_packet() -> None:
    data = stress.packet("198.18.0.7", "10.201.0.2", 4321, 27015, stress.INFO)
    version, _, total, _, _, ttl, protocol, _, source, destination = struct.unpack(
        "!BBHHHBBH4s4s", data[:20]
    )
    assert (version, total, protocol) == (0x45, len(data), socket.IPPROTO_UDP)
    assert ttl == 64
    assert socket.inet_ntoa(source) == "198.18.0.7"
    assert socket.inet_ntoa(destination) == "10.201.0.2"
    source_port, port, length, _ = struct.unpack("!HHHH", data[20:28])
    assert (source_port, port, length) == (4321, 27015, 8 + len(stress.INFO))
    assert data[28:] == stress.INFO


def test_info_request() -> None:
    # A2S_INFO's request without its challenge, the length the table lets through (UDP length 33)
    assert len(stress.INFO) == 25
    assert stress.INFO.startswith(stress.PREFIX + b"T")


def test_floods() -> None:
    rng = random.Random(1)
    assert set(stress.FLOODS) == set(stress.EXPECTED)
    single, payload = stress.FLOODS["info-single"]
    assert single and payload(rng) == stress.INFO
    single, payload = stress.FLOODS["handshake-spoofed"]
    challenge = payload(rng)
    assert not single and challenge[:5] == stress.PREFIX + b"q" and len(challenge) == 20
    single, payload = stress.FLOODS["junk"]
    assert not single and all(10 <= len(payload(rng)) <= 400 for _ in range(50))


def test_malformed() -> None:
    rng = random.Random(2)
    packets = {stress.malformed(rng) for _ in range(200)}
    # Each kind turns up: an unknown type, wrong lengths, an oversized connection, a cut prefix
    assert any(data[4:5] == b"X" for data in packets)
    assert stress.INFO + b"\x00\x00" in packets
    assert stress.PREFIX + b"U" + bytes(7) in packets
    assert any(data[4:5] == b"k" and len(data) > 1480 for data in packets)
    assert stress.PREFIX[:3] in packets


def test_spoofed_address() -> None:
    rng = random.Random(3)
    for _ in range(100):
        first, second, _, last = map(int, stress.spoofed_address(rng).split("."))
        assert first == 198 and second in (18, 19) and 1 <= last <= 254


def test_stats_value() -> None:
    assert stress.stats_value(STATS, "FPS") == 63.87
    assert stress.stats_value(STATS, "Uptime") == 3
    assert stress.stats_value(STATS, "Choke") is None
    assert stress.stats_value("", "FPS") is None


def test_dropped() -> None:
    table = {
        "nftables": [
            {"metainfo": {"version": "1.1.7"}},
            {"table": {"family": "ip", "name": "nwi-game-ports"}},
            {"rule": {"chain": "game", "expr": [{"counter": {"packets": 12, "bytes": 600}}, {"drop": None}]}},
            {"rule": {"chain": "game", "expr": [{"accept": None}]}},
            {"rule": {"chain": "query", "expr": [{"counter": {"packets": 30, "bytes": 990}}]}},
        ]
    }  # fmt: skip
    assert stress.dropped(json.dumps(table)) == 42
    assert stress.dropped('{"nftables": []}') == 0


def served(
    answered: int, queries: int, challenged: int, connections: int
) -> stress.Served:
    return stress.Served(queries, answered, connections, challenged)


def passing(kind: str) -> stress.Result:
    return stress.Result(
        kind, True, sent=400_000, seconds=20, served=served(13, 13, 7, 7), tick=127.9
    )


def test_failures_pass() -> None:
    results = [passing(kind) for kind in stress.FLOODS]
    assert stress.failures(results, 128) == []


def test_failures_without_the_table() -> None:
    # Without the table the test only reports
    result = stress.Result(
        "malformed", False, served=served(0, 13, 0, 7), tick=None, tracked=200_000
    )
    assert stress.failures([result], 128) == []


def test_failures() -> None:
    low_tick = passing("info-single")
    low_tick.tick = 100.0
    restarted = passing("malformed")
    restarted.restarted = True
    tracked = passing("junk")
    tracked.tracked = 150_000
    queries = passing("handshake-spoofed")
    queries.served = served(2, 13, 0, 7)
    connections = passing("info-spoofed")
    connections.served = served(0, 13, 1, 7)
    silent = stress.Result("info-single", True, answering=False)
    no_rcon = passing("junk")
    no_rcon.tick = None
    found = stress.failures(
        [low_tick, restarted, tracked, queries, connections, silent, no_rcon], 128
    )
    assert found == [
        "info-single: tick 100.0, below 90% of 128",
        "malformed: the server restarted",
        "junk: 150000 connections tracked",
        "handshake-spoofed: 2 of 13 queries answered, fewer than 80%",
        "info-spoofed: 1 of 7 connections answered, fewer than 50%",
        "info-single: the server didn't answer before the flood",
        "junk: RCON didn't answer during the flood",
    ]


def test_report() -> None:
    rows = stress.report(
        [passing("info-single"), stress.Result("junk", False, answering=False)]
    ).splitlines()
    assert rows[0].startswith("flood")
    assert rows[1].split()[:4] == ["info-single", "with", "20000", "127.9"]
    assert rows[2].split()[:3] == ["junk", "without", "the"]
