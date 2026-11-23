"""The round test of a server config (instance.py rounds): bots play its rounds, and the test checks
that they do, from the events that the test plugin (tests/integration/plugins/nwi_test_rounds.sp) logs
to SourceMod's log.

The game waits for human players before a round starts, also with bots on the teams, and the coop
modes lose a round without human players on the players' team. nwi_gamedata's nwi_bot_only_rounds
lets bots play without them. The test turns it on, keeps the empty server from hibernating, and puts
bots on the teams: in coop the games' AI teammates on the players' team, whose enemies the game adds
itself, which Insurgency only adds at a round's start, so a bot of its own starts its game first; in
PvP, bots on both teams, with the game's quota raised for them, which a playlist without bots sets
to 0.
Then it changes to the config's first map, so that its game starts anew, and checks, each within its
time:

- the game starts (game_start), and a round (round_start),
- the bots take an objective (controlpoint_captured), and die (the plugin's count of deaths),
  where Insurgency's coop only has them die: its AI teammates only escort a human player, so without
  one they never take an objective,
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
# How long after adding the bots the test adds them again if the game dropped them, and how often: the
# first bot of a map makes the game load its NavMesh, which restarts the game and drops the bots
READD_SECONDS = 30
READD_TRIES = 3
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


def checks(coop: bool, game: str = "doi") -> list[Check]:
    """The checks of a config: Insurgency's coop without the objective, which its AI teammates only
    take with a human player to escort (CINSBotActionCheckpoint gives them CINSBotEscort)."""
    if coop and game == "insurgency":
        return [check for check in CHECKS if check.event != "controlpoint_captured"]
    return list(CHECKS)


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


# The coop modes of Day of Infamy and Insurgency, as nwi_mode_config.sp has them
COOP_MODES = {
    "stronghold", "entrenchment", "raid", "patrol",
    "checkpoint", "hunt", "outpost", "survival", "conquer",
}  # fmt: skip


def is_coop(server_toml: Path) -> bool:
    """Whether a config plays coop: the game mode of its startup map, e.g. bastogne stronghold."""
    with server_toml.open("rb") as file:
        startup_map = tomllib.load(file).get("startup_map", "")
    words = startup_map.split() if isinstance(startup_map, str) else []
    return len(words) > 1 and words[1] in COOP_MODES


def setup_commands(coop: bool, startup_map: str, game: str = "doi") -> list[str]:
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
    """The bots added after the map change, the commands of the game's folder (doi or insurgency):
    PvP's, whose server adds none without players; in Insurgency's coop one bot, which starts the
    game, as the game adds its AI teammates only at a round's start and nwi_bot_only_rounds waits for
    a bot on a team. At the round's start the game's quota sets the teams' bots, this one's too."""
    if coop:
        return ["ins_bot_add"] if game == "insurgency" else []
    prefix = "doi" if game == "doi" else "ins"
    # A playlist without bots, e.g. NWI's mp_battles, sets the quota to 0 at every map change, and the
    # game kicks the bots above it
    return [f"{prefix}_bot_quota {PVP_BOTS}"] + [
        f"{prefix}_bot_add",
        f"{prefix}_bot_add_t2",
    ] * PVP_BOTS


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
    for command in setup_commands(coop, startup_map, game):
        try:
            rcon(command)
        except OSError:
            # The map change closes RCON's connection
            pass
    start = clock()
    # The map change takes a while; the bots come after it
    sleep(interval)
    added_at: float | None = None
    adds = 0
    result = Result()
    pending = checks(coop, game)
    while True:
        elapsed = int(clock() - start)
        seen = events(read_log())[before:]
        # The bots once the new map is there, which drops those before it, and again if the game
        # dropped them (READD_SECONDS): the players' team, the first, has none
        dropped = result.teams is None or result.teams.bots[0] == 0
        due = added_at is None or (
            dropped and adds < READD_TRIES and clock() - added_at > READD_SECONDS
        )
        commands = bot_commands(coop, game)
        if commands and due and any(text.startswith("map ") for _, text in seen):
            try:
                for command in commands:
                    rcon(command)
                added_at = clock()
                adds += 1
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
