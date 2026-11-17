"""The servers' metrics for Prometheus and Netdata (nwi-server metrics): how each server of the machine
runs, for monitoring and for debugging a busy evening.

At each scrape, it asks every server of /etc/nwi-server (games.server_envs) over RCON, with its
password of /run/nwi-server/rcon (rcon.py): stats for the server's frame rate, which is its tick, its
CPU, its traffic and uptime, status for its map and its players, humans and bots, and the humans'
ping and loss, sv_mincmdrate for its tickrate, which server.cfg sets to it (server_config.py), and
nwi_netstats, of the plugin of the same name, for the human players' choke. It serves them in
Prometheus' text format (render()), by server and game:

    nwi_server_up                   1 if the server answered RCON
    nwi_server_info                 1, with the map as a label
    nwi_server_tick_rate            the server's frames per second, its tick when it keeps up
    nwi_server_tick_rate_target     its tickrate (server.toml's, 128 by default)
    nwi_server_cpu_ratio            its CPU use, of one core
    nwi_server_network_*_bytes_per_second   its traffic in and out
    nwi_server_uptime_seconds
    nwi_server_players              by kind, human or bot
    nwi_server_max_players          its slots, as status reports them
    nwi_server_player_ping_seconds  of the human players: the median and the most
    nwi_server_player_loss_ratio    of the human players' packets: the median and the most
    nwi_server_players_lossy        the human players losing more than LOSSY of their packets
    nwi_server_player_choke_ratio   of the human players' packets held back: the median and the most,
                                    of the server's packets to them (out) and theirs (in)
    nwi_server_players_choked       the human players of whose packets the server holds back more
                                    than CHOKED

The players' values are aggregates, not series per player, which a busy server's players would make
by the thousand. The choke isn't in status: without the plugin nwi_netstats, which reads it
(GetClientAvgChoke), the server has no choke metrics.
"""

import itertools
import json
import re
import statistics
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import games, layers, rcon, server_config

# A human player's packets lost, from which on the player counts as lossy
LOSSY = 0.05
# The server's packets to a human player held back, from which on the player counts as choked
CHOKED = 0.05
# A status line of a human player: # userid "name" uniqueid connected ping loss state rate adr
PLAYER = re.compile(
    r'^#\s*\d+\s+"(?P<name>.*)"\s+(?P<id>\S+)\s+(?P<connected>[\d:]+)\s+'
    r"(?P<ping>\d+)\s+(?P<loss>\d+)\s+(?P<state>\S+)\s+(?P<rate>\d+)"
)
COUNTS = re.compile(r"^players\s*:\s*(\d+) humans?, (\d+) bots? \((\d+)/")
MAP = re.compile(r"^map\s*:\s*(\S+)")
# A cvar's answer: "sv_mincmdrate" = "128" ( def. "64" ) …
CVAR = re.compile(r'^"(?P<name>[^"]+)" = "(?P<value>[^"]*)"')


@dataclass
class Target:
    """A server to ask: its name, game, RCON port and password file, and its tick's target."""

    name: str
    game: str
    port: int
    password: Path
    tick_target: int


@dataclass
class Sample:
    """What a server answered, or None for a server that didn't."""

    target: Target
    stats: dict[str, float] | None = None
    map: str = ""
    humans: int = 0
    bots: int = 0
    max_players: int = 0
    pings: list[float] = field(default_factory=list)
    losses: list[float] = field(default_factory=list)
    # The human players' choke of nwi_netstats, by its direction, out and in; None without the plugin
    chokes: dict[str, list[float]] | None = None


def answer_lines(text: str) -> list[str]:
    """An RCON answer's lines, without the log lines the server echoes into it (L <date> - …)."""
    return [
        line
        for line in text.splitlines()
        if not re.match(r"^L \d\d/\d\d/\d{4} - ", line)
    ]


def parse_stats(text: str) -> dict[str, float]:
    """stats' values by its header's names, e.g. CPU, In, Out, Uptime, FPS, Players."""
    lines = [line.split() for line in answer_lines(text) if line.strip()]
    for header, values in itertools.pairwise(lines):
        if "FPS" in header and len(values) == len(header):
            try:
                return {
                    name: float(value)
                    for name, value in zip(header, values, strict=True)
                }
            except ValueError:
                continue
    raise ValueError("no stats in the answer")


def parse_cvar(text: str) -> str | None:
    """A cvar's value of the answer to its name, None without one."""
    for line in answer_lines(text):
        if match := CVAR.match(line):
            return match["value"]
    return None


def parse_status(text: str, sample: Sample) -> None:
    """status' map, players' counts and the human players' ping and loss, into sample."""
    for line in answer_lines(text):
        if match := MAP.match(line):
            sample.map = match[1]
        elif match := COUNTS.match(line):
            sample.humans, sample.bots, sample.max_players = map(int, match.groups())
        elif (match := PLAYER.match(line)) and match["id"] != "BOT":
            sample.pings.append(int(match["ping"]) / 1000)
            sample.losses.append(int(match["loss"]) / 100)


def parse_netstats(text: str, sample: Sample) -> None:
    """nwi_netstats' choke of the human players into sample, by its header's columns; nothing without
    the plugin, whose command the server doesn't know then."""
    columns: list[str] | None = None
    for line in answer_lines(text):
        fields = line.split()
        if fields[:1] == ["nwi_netstats"] and "userid" in fields:
            columns = fields[1:]
            sample.chokes = {"out": [], "in": []}
        elif (
            columns is not None
            and sample.chokes is not None
            and len(fields) == len(columns)
        ):
            try:
                row = {
                    name: float(value)
                    for name, value in zip(columns, fields, strict=True)
                }
            except ValueError:
                continue
            for direction in ("out", "in"):
                if f"choke_{direction}" in row:
                    sample.chokes[direction].append(row[f"choke_{direction}"])


def target(name: str, env: dict[str, str]) -> Target:
    """A server of the machine: its game and tick's target of its mount's record (mount.py), which
    the metrics' user can read, unlike the server's config; without one, as of a server that isn't
    mounted, of its config if it can be read, or else its environment file's game and the default
    tickrate."""
    game = env.get("GAME", games.DEFAULT)
    tick = server_config.TICKRATE
    try:
        record = json.loads((layers.IN_USE / name).read_text())
        return Target(
            name,
            str(record["game"]),
            int(env.get("SERVER_PORT", "27015")),
            rcon.RCON_DIR / name,
            int(record["tickrate"]),
        )
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        server = games.server(name, env)
        game = server.game
        if server.config:
            toml = (
                games.config_folder(server.source)
                / "servers"
                / server.config
                / "server.toml"
            )
            tick = int(server_config.load(toml).get("tickrate", tick))
    except (OSError, ValueError):
        pass
    return Target(
        name, game, int(env.get("SERVER_PORT", "27015")), rcon.RCON_DIR / name, tick
    )


def targets() -> list[Target]:
    """The servers of the machine, see the module's documentation."""
    return [target(name, env) for name, env in sorted(games.server_envs().items())]


def collect(target: Target, host: str = "127.0.0.1") -> Sample:
    """Ask a server over RCON; a sample without stats if it doesn't answer."""
    sample = Sample(target)
    try:
        password = target.password.read_text().strip()
        with rcon.connect(host, target.port, password) as sock:
            stats = parse_stats(rcon.run(sock, "stats"))
            parse_status(rcon.run(sock, "status"), sample)
            tick = parse_cvar(rcon.run(sock, "sv_mincmdrate"))
            parse_netstats(rcon.run(sock, "nwi_netstats"), sample)
    except (OSError, ValueError, PermissionError):
        return Sample(target)
    sample.stats = stats
    if tick and tick.isdigit() and int(tick) > 0:
        sample.target.tick_target = int(tick)
    return sample


def quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render(samples: list[Sample]) -> str:
    """The samples in Prometheus' text format, see the module's documentation."""
    families: dict[str, tuple[str, str, list[str]]] = {}

    def add(
        name: str, kind: str, help_text: str, labels: dict[str, str], value: float
    ) -> None:
        family = families.setdefault(name, (kind, help_text, []))
        text = ",".join(f'{key}="{quote(label)}"' for key, label in labels.items())
        family[2].append(f"{name}{{{text}}} {value:g}")

    for sample in samples:
        labels = {"server": sample.target.name, "game": sample.target.game}
        add(
            "nwi_server_up",
            "gauge",
            "1 if the server answered RCON",
            labels,
            1 if sample.stats else 0,
        )
        add(
            "nwi_server_tick_rate_target",
            "gauge",
            "The server's tickrate",
            labels,
            sample.target.tick_target,
        )
        if sample.stats is None:
            continue
        stats = sample.stats
        add(
            "nwi_server_info",
            "gauge",
            "The server's map",
            labels | {"map": sample.map},
            1,
        )
        add(
            "nwi_server_tick_rate",
            "gauge",
            "The server's frames per second",
            labels,
            stats.get("FPS", 0),
        )
        add(
            "nwi_server_cpu_ratio",
            "gauge",
            "The server's CPU use, of one core",
            labels,
            stats.get("CPU", 0) / 100,
        )
        add(
            "nwi_server_network_in_bytes_per_second",
            "gauge",
            "The server's incoming traffic",
            labels,
            stats.get("In", 0) * 1024,
        )
        add(
            "nwi_server_network_out_bytes_per_second",
            "gauge",
            "The server's outgoing traffic",
            labels,
            stats.get("Out", 0) * 1024,
        )
        add(
            "nwi_server_uptime_seconds",
            "gauge",
            "The server's uptime",
            labels,
            stats.get("Uptime", 0) * 60,
        )
        for kind, count in (("human", sample.humans), ("bot", sample.bots)):
            add(
                "nwi_server_players",
                "gauge",
                "The server's players, by kind",
                labels | {"kind": kind},
                count,
            )
        add(
            "nwi_server_max_players",
            "gauge",
            "The server's slots",
            labels,
            sample.max_players,
        )
        for name, values, help_text in (
            ("nwi_server_player_ping_seconds", sample.pings, "The human players' ping"),
            (
                "nwi_server_player_loss_ratio",
                sample.losses,
                "The human players' packet loss",
            ),
        ):
            if values:
                add(
                    name,
                    "gauge",
                    help_text,
                    labels | {"stat": "median"},
                    statistics.median(values),
                )
                add(name, "gauge", help_text, labels | {"stat": "max"}, max(values))
        add(
            "nwi_server_players_lossy",
            "gauge",
            f"The human players losing more than {LOSSY:.0%} of their packets",
            labels,
            sum(1 for loss in sample.losses if loss > LOSSY),
        )
        if sample.chokes is None:
            continue
        for direction, values in sample.chokes.items():
            if values:
                for stat, value in (
                    ("median", statistics.median(values)),
                    ("max", max(values)),
                ):
                    add(
                        "nwi_server_player_choke_ratio",
                        "gauge",
                        "The human players' packets held back, of the server's (out) and theirs (in)",
                        labels | {"direction": direction, "stat": stat},
                        value,
                    )
        add(
            "nwi_server_players_choked",
            "gauge",
            f"The human players of whose packets the server holds back more than {CHOKED:.0%}",
            labels,
            sum(1 for choke in sample.chokes["out"] if choke > CHOKED),
        )
    lines = []
    for name, (kind, help_text, samples_text) in families.items():
        lines += [f"# HELP {name} {help_text}", f"# TYPE {name} {kind}", *samples_text]
    return "\n".join(lines) + "\n"


def serve(address: str, port: int) -> None:
    """Serve /metrics, collected anew at each scrape, one scrape at a time."""
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/metrics":
                self.send_error(404)
                return
            with lock:
                body = render([collect(target) for target in targets()]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    ThreadingHTTPServer((address, port), Handler).serve_forever()
