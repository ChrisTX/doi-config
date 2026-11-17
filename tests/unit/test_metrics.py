"""The servers' metrics (metrics.py, nwi-server metrics), of a fake server's RCON that answers as
Day of Infamy's: stats, status with bots and human players, sv_mincmdrate, the plugin nwi_netstats'
choke, and log lines."""

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from nwi_server_kit import layers, metrics, rcon

from .conftest import PASSWORD, FakeServer

LOG = 'L 11/17/2026 - 19:11:02: rcon from "10.0.2.100:50416": command "stats"\n'
STATS = (
    "CPU   In    Out   Uptime  Users   FPS    Players\n"
    " 31.45  2.50  40.00       3     0  127.98      21\n" + LOG
)
STATUS = (
    "hostname: KIM JONG UN's BOOTCAMP | COOP COMMANDO\n"
    "version : 3.2.1.5/3215 6948 secure  \n"
    "map     : bastogne\n"
    "players : 2 humans, 19 bots (16/0 max) (not hibernating)\n"
    "\n"
    "# userid name uniqueid connected ping loss state rate adr\n"
    '# 2 "KIM JONG UN\'s BOOTCAMP | COOP C" BOT active\n'
    '# 3 "Mike" BOT active\n'
    '#  9 "Player One" STEAM_1:0:123 05:12 40 0 active 196608 1.2.3.4:27005\n'
    '# 10 "Player "Two"" STEAM_1:1:456 1:02:33 120 8 active 80000 5.6.7.8:27005\n' + LOG
)
CVAR = (
    '"sv_mincmdrate" = "64" ( def. "64" ) replicated - This sets the minimum value\n'
    + LOG
)
NETSTATS = (
    "nwi_netstats userid choke_out choke_in\n9 0.0000 0.0125\n10 0.2500 0.0000\n" + LOG
)
NO_PLUGIN = 'Unknown command "nwi_netstats"\n' + LOG


@pytest.fixture
def server() -> Iterator[FakeServer]:
    fake = FakeServer(
        answers={
            "stats": STATS,
            "status": STATUS,
            "sv_mincmdrate": CVAR,
            "nwi_netstats": NETSTATS,
        }
    )
    yield fake
    fake.listener.close()


def target(tmp_path: Path, port: int) -> metrics.Target:
    password = tmp_path / "coop"
    password.write_text(PASSWORD + "\n")
    return metrics.Target("coop", "doi", port, password, 128)


def test_parse() -> None:
    assert metrics.parse_stats(STATS) == {
        "CPU": 31.45,
        "In": 2.5,
        "Out": 40.0,
        "Uptime": 3.0,
        "Users": 0.0,
        "FPS": 127.98,
        "Players": 21.0,
    }
    with pytest.raises(ValueError, match="no stats"):
        metrics.parse_stats("Unknown command\n")
    sample = metrics.Sample(metrics.Target("coop", "doi", 1, Path("x"), 128))
    metrics.parse_status(STATUS, sample)
    assert (sample.map, sample.humans, sample.bots, sample.max_players) == (
        "bastogne",
        2,
        19,
        16,
    )
    assert sample.pings == [0.04, 0.12] and sample.losses == [0.0, 0.08]
    assert metrics.parse_cvar(CVAR) == "64"
    assert metrics.parse_cvar(LOG) is None
    metrics.parse_netstats(NETSTATS, sample)
    assert sample.chokes == {"out": [0.0, 0.25], "in": [0.0125, 0.0]}
    # Without the plugin, or a server that echoes the command: no choke, not none
    for text in (NO_PLUGIN, "nwi_netstats\n"):
        without = metrics.Sample(sample.target)
        metrics.parse_netstats(text, without)
        assert without.chokes is None


def test_collect(server: FakeServer, tmp_path: Path) -> None:
    """A server that answers: its stats, players and its tickrate of sv_mincmdrate."""
    sample = metrics.collect(target(tmp_path, server.port))
    assert sample.stats is not None and sample.stats["FPS"] == 127.98
    assert sample.target.tick_target == 64
    assert sample.humans == 2


def test_collect_down(tmp_path: Path) -> None:
    """A server that doesn't answer, or a password that can't be read: down, not an error."""
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        port = unused.getsockname()[1]
        assert metrics.collect(target(tmp_path, port)).stats is None
    missing = metrics.Target("x", "doi", port, tmp_path / "none", 128)
    assert metrics.collect(missing).stats is None


def test_render(server: FakeServer, tmp_path: Path) -> None:
    up = metrics.collect(target(tmp_path, server.port))
    down = metrics.Sample(metrics.Target("pvp", "doi", 1, Path("x"), 128))
    text = metrics.render([up, down])
    lines = text.splitlines()
    assert 'nwi_server_up{server="coop",game="doi"} 1' in lines
    assert 'nwi_server_up{server="pvp",game="doi"} 0' in lines
    assert 'nwi_server_tick_rate{server="coop",game="doi"} 127.98' in lines
    assert 'nwi_server_tick_rate_target{server="coop",game="doi"} 64' in lines
    assert 'nwi_server_cpu_ratio{server="coop",game="doi"} 0.3145' in lines
    assert (
        'nwi_server_network_out_bytes_per_second{server="coop",game="doi"} 40960'
        in lines
    )
    assert 'nwi_server_players{server="coop",game="doi",kind="bot"} 19' in lines
    assert (
        'nwi_server_player_ping_seconds{server="coop",game="doi",stat="max"} 0.12'
        in lines
    )
    assert (
        'nwi_server_player_loss_ratio{server="coop",game="doi",stat="median"} 0.04'
        in lines
    )
    assert 'nwi_server_players_lossy{server="coop",game="doi"} 1' in lines
    assert 'nwi_server_info{server="coop",game="doi",map="bastogne"} 1' in lines
    assert (
        'nwi_server_player_choke_ratio{server="coop",game="doi",direction="out",stat="max"} 0.25'
        in lines
    )
    assert (
        'nwi_server_player_choke_ratio{server="coop",game="doi",direction="in",stat="median"} 0.00625'
        in lines
    )
    assert 'nwi_server_players_choked{server="coop",game="doi"} 1' in lines
    # Each family once, with its HELP and TYPE first; nothing of the down server but up and target
    assert text.count("# TYPE nwi_server_up gauge") == 1
    assert not any('server="pvp"' in line and "tick_rate{" in line for line in lines)
    # A server without the plugin has no choke metrics, rather than none choked
    up.chokes = None
    assert "choke" not in metrics.render([up])


def test_quote() -> None:
    assert metrics.quote('a"b\\c\nd') == 'a\\"b\\\\c\\nd'


def test_targets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The servers of /etc/nwi-server, with their mounts' game and tickrate, or without a mount, their
    environment files' game when their configs can't be read."""
    servers = tmp_path / "servers"
    servers.mkdir()
    (servers / "coop.env").write_text("SERVER_PORT=27016\nSERVER_CONFIG_NAME=coop\n")
    (servers / "ins.env").write_text("GAME=insurgency\n")
    # A mounted server of a config that the metrics can't read, nor GAME in its environment file
    (servers / "ins-test.env").write_text("SERVER_PORT=27017\n")
    in_use = tmp_path / "in-use"
    in_use.mkdir()
    (in_use / "ins-test").write_text(
        json.dumps({"game": "insurgency", "tickrate": 64, "versions": []})
    )
    # A record of before the game and tickrate: as without one
    (in_use / "ins").write_text(json.dumps({"versions": []}))
    monkeypatch.setenv("NWI_SERVERS_DIR", str(servers))
    monkeypatch.setenv("NWI_CONFIGS_DIR", str(tmp_path / "no-configs"))
    monkeypatch.setattr(rcon, "RCON_DIR", tmp_path / "rcon")
    monkeypatch.setattr(layers, "IN_USE", in_use)
    found = metrics.targets()
    assert [(t.name, t.game, t.port, t.tick_target) for t in found] == [
        ("coop", "doi", 27016, 128),
        ("ins", "insurgency", 27015, 128),
        ("ins-test", "insurgency", 27017, 64),
    ]
    assert found[0].password == tmp_path / "rcon/coop"


def test_serve(
    server: FakeServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/metrics, anew at each scrape; anything else 404."""
    monkeypatch.setattr(metrics, "targets", lambda: [target(tmp_path, server.port)])
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
    threading.Thread(
        target=metrics.serve, args=("127.0.0.1", port), daemon=True
    ).start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"{url}/metrics", timeout=5) as answer:
                body = answer.read().decode()
                assert answer.headers["Content-Type"].startswith(
                    "text/plain; version=0.0.4"
                )
            break
        except urllib.error.URLError:
            time.sleep(0.1)
    assert 'nwi_server_up{server="coop",game="doi"} 1' in body
    with pytest.raises(urllib.error.HTTPError, match="404"):
        urllib.request.urlopen(f"{url}/", timeout=5)
