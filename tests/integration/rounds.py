"""The round test of a server config (instance.py rounds): bots play its rounds, and the test checks
that they do, from the events that the test plugin (tests/integration/plugins/nwi_test_rounds.sp) logs
to SourceMod's log.

The game waits for human players before a round starts, also with bots on the teams, and the coop
modes lose a round without human players on the players' team. nwi_gamedata's nwi_bot_only_rounds
lets bots play without them. The test turns it on, keeps the empty server from hibernating, and puts
bots on the teams: the coop modes' AI teammates on the players' team, whose enemies the game adds
itself; in PvP, bots on both teams. Then it changes to the config's first map, so that its game
starts anew, and checks, each within its time:

- the game starts (game_start), and a round (round_start),
- the bots take an objective (controlpoint_captured), and die (the plugin's count of deaths),
- and SourceMod reports no exception, and no error of the configs' plugins (nwi_*).

instance.py starts the config's test instance, puts the plugin in, runs the checks with run() and
removes the instance again.
"""

import re
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent / "plugins/nwi_test_rounds.sp"
PREFIX = "nwi_test_rounds: "
# A line of SourceMod's log: "L 11/17/2026 - 14:45:32: [nwi_test_rounds.smx] nwi_test_rounds: round_start"
LOG_LINE = re.compile(
    r"^L \d\d/\d\d/\d{4} - (\d\d):(\d\d):(\d\d): \[[^\]]+\] "
    + re.escape(PREFIX)
    + r"(.*)$"
)
TEAMS = re.compile(
    r"teams 2: (\d+) bots (\d+) humans, 3: (\d+) bots (\d+) humans, (\d+) deaths, game state (-?\d+)"
)
# The coop modes' AI teammates on the players' team
AI_TEAMMATES = 6
# Bots a team in PvP
PVP_BOTS = 10


@dataclass
class Teams:
    """The plugin's count of the players on the two playing teams, and the deaths so far."""

    bots: tuple[int, int]
    humans: tuple[int, int]
    deaths: int
    state: int


@dataclass
class Check:
    """An event the test waits for, and the seconds it may take from the test's start."""

    event: str
    seconds: int


# The checks, in the order they're expected
CHECKS = (
    Check("game_start", 240),
    Check("round_start", 300),
    Check("controlpoint_captured", 900),
)


@dataclass
class Result:
    """What the test saw: the events by the seconds they came after the start, the last count of the
    teams, the errors, and the failed checks."""

    events: list[tuple[int, str]] = field(default_factory=list)
    teams: Teams | None = None
    errors: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def events(log: str) -> list[tuple[str, str]]:
    """The plugin's lines of SourceMod's log: their time (HH:MM:SS) and text."""
    found = []
    for line in log.splitlines():
        match = LOG_LINE.match(line.strip())
        if match:
            found.append((":".join(match.group(1, 2, 3)), match.group(4)))
    return found


def teams(text: str) -> Teams | None:
    """The count of a "teams …" line of the plugin, None for another line."""
    match = TEAMS.search(text)
    if match is None:
        return None
    values = [int(value) for value in match.groups()]
    return Teams((values[0], values[2]), (values[1], values[3]), values[4], values[5])


def errors(log: str) -> list[str]:
    """The lines of SourceMod's error log the test fails on: exceptions, and errors of the configs'
    plugins (nwi_*), but not those of the test's plugin."""
    return [
        line.strip()
        for line in log.splitlines()
        if ("Exception reported" in line or "[nwi_" in line)
        and "[nwi_test_rounds" not in line
    ]


def is_coop(server_toml: Path) -> bool:
    """Whether a config plays coop: its playlist's name, e.g. nwi/coop_commando."""
    with server_toml.open("rb") as file:
        playlist = tomllib.load(file).get("playlist", "")
    return isinstance(playlist, str) and "coop" in playlist


def setup_commands(coop: bool, startup_map: str) -> list[str]:
    """The commands that let the bots play the config's rounds, see the module's documentation."""
    commands = ["sv_hibernate_when_empty 0", "nwi_bot_only_rounds 1"]
    if coop:
        commands += [
            "mp_coop_ai_teammates 1",
            f"mp_coop_ai_teammate_count {AI_TEAMMATES}",
        ]
    commands.append(f"changelevel {startup_map}")
    return commands


def bot_commands(coop: bool, game: str = "doi") -> list[str]:
    """The bots added after the map change: PvP's, whose server adds none without players; the
    commands of the game's folder (doi or insurgency)."""
    if coop:
        return []
    prefix = "doi" if game == "doi" else "ins"
    return [f"{prefix}_bot_add", f"{prefix}_bot_add_t2"] * PVP_BOTS


def run(
    rcon: Callable[[str], str],
    read_log: Callable[[], str],
    read_errors: Callable[[], str],
    coop: bool,
    startup_map: str,
    game: str = "doi",
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    interval: float = 10,
) -> Result:
    """Run the round test on a running server with the plugin loaded: RCON, SourceMod's log and its
    error log, see the module's documentation. The log's lines before the map change are skipped."""
    before = len(events(read_log()))
    for command in setup_commands(coop, startup_map):
        try:
            rcon(command)
        except OSError:
            # The map change closes RCON's connection
            pass
    start = clock()
    # The map change takes a while; the bots come after it
    sleep(interval)
    added = False
    result = Result()
    pending = list(CHECKS)
    while True:
        elapsed = int(clock() - start)
        seen = events(read_log())[before:]
        # PvP's bots once the new map is there, which drops those before it
        if not added and any(text.startswith("map ") for _, text in seen):
            try:
                for command in bot_commands(coop, game):
                    rcon(command)
                added = True
            except OSError:
                pass
        try:
            rcon("nwi_test_rounds_status")
        except OSError:
            pass
        seen = events(read_log())[before:]
        for _, text in seen:
            if (count := teams(text)) is not None:
                result.teams = count
            elif text not in (event for _, event in result.events):
                result.events.append((elapsed, text))
        result.errors = errors(read_errors())
        names = {event for _, event in result.events}
        pending = [check for check in pending if check.event not in names]
        late = [check for check in pending if elapsed > check.seconds]
        died = result.teams is not None and result.teams.deaths > 0
        if (
            result.errors
            or late
            or (not pending and died)
            or elapsed > CHECKS[-1].seconds
        ):
            break
        sleep(interval)
    # SourceMod's errors first, the likely cause of the rest
    result.failures += [f"SourceMod: {error}" for error in result.errors]
    result.failures += [
        f"no {check.event} within {check.seconds} seconds" for check in late
    ]
    if result.teams is None or result.teams.deaths == 0:
        result.failures.append("no bot died")
    return result
