"""The round test's checks (tests/integration/rounds.py), against a fake server: its RCON, which
records the commands, and SourceMod's logs, which the test fills as the fake game goes on."""

from pathlib import Path

import pytest

from tests.integration import rounds


def line(time: str, text: str, plugin: str = "nwi_test_rounds.smx") -> str:
    return f"L 11/17/2026 - {time}: [{plugin}] nwi_test_rounds: {text}"


def test_events() -> None:
    log = "\n".join(
        [
            "L 11/17/2026 - 14:45:30: [SM] Loaded plugin nwi_test_rounds.smx",
            line("14:45:32", "game_start"),
            line("14:45:42", "round_start", "disabled\\nwi_test_rounds.smx"),
        ]
    )
    assert rounds.events(log) == [
        ("14:45:32", "game_start"),
        ("14:45:42", "round_start"),
    ]


def test_teams() -> None:
    count = rounds.teams(
        "teams 2: 3 bots 0 humans, 3: 5 bots 1 humans, 19 deaths, game state 4"
    )
    assert count == rounds.Teams((3, 5), (0, 1), 19, 4)
    assert rounds.teams("round_start") is None


def test_errors() -> None:
    """Exceptions and the configs' plugins' errors, not the test plugin's or other plugins'."""
    log = """\
L 11/17/2026 - 14:00:00: [SM] Exception reported: Invalid address
L 11/17/2026 - 14:00:01: [nwi_gamedata.smx] No nwi_bot_only_rounds
L 11/17/2026 - 14:00:02: [nwi_test_rounds.smx] nwi_test_rounds: no event x
L 11/17/2026 - 14:00:03: [sourcebans.smx] Database failure
"""
    found = rounds.errors(log)
    assert len(found) == 2
    assert found[0].endswith("Exception reported: Invalid address")
    assert found[1].endswith("No nwi_bot_only_rounds")


def test_coop(tmp_path: Path) -> None:
    toml = tmp_path / "server.toml"
    toml.write_text(
        'playlist = "nwi/coop_commando"\nstartup_map = "bastogne stronghold"\n'
    )
    assert rounds.is_coop(toml)
    # Insurgency's coop, without a playlist
    toml.write_text('startup_map = "ministry_coop checkpoint"\n')
    assert rounds.is_coop(toml)
    toml.write_text('playlist = "nwi/mp_battles"\nstartup_map = "crete invasion"\n')
    assert not rounds.is_coop(toml)
    toml.write_text('startup_map = "crete"\n')
    assert not rounds.is_coop(toml)
    assert "mp_coop_ai_teammates 1" in rounds.setup_commands(True, "bastogne")
    assert rounds.setup_commands(False, "crete")[-1] == "changelevel crete"
    assert rounds.bot_commands(True) == []
    assert rounds.bot_commands(False, "insurgency")[1:3] == [
        "ins_bot_add",
        "ins_bot_add_t2",
    ]


class FakeServer:
    """A server whose game goes on by its script: the log lines that come at each RCON status."""

    def __init__(self, script: list[list[str]], errors: str = "") -> None:
        self.script = script
        self.log = [line("14:00:00", "map bastogne")]
        self.error_log = errors
        self.commands: list[str] = []
        self.now = 0.0

    def rcon(self, text: str) -> str:
        self.commands.append(text)
        if text == "nwi_test_rounds_status" and self.script:
            self.log += self.script.pop(0)
        return ""

    def run(self, coop: bool = True, game: str = "doi") -> rounds.Result:
        return rounds.run(
            self.rcon,
            lambda: "\n".join(self.log),
            lambda: self.error_log,
            coop,
            "bastogne",
            game,
            clock=lambda: self.now,
            sleep=self.sleep,
        )

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def status(deaths: int) -> str:
    return line(
        "14:00:01",
        f"teams 2: 3 bots 0 humans, 3: 5 bots 0 humans, {deaths} deaths, game state 4",
    )


def test_passes() -> None:
    """The events in time and a death: the test stops at once, the earlier map's lines skipped."""
    server = FakeServer(
        [
            [line("14:00:10", "map bastogne"), line("14:00:11", "game_start")],
            [line("14:00:20", "round_start"), status(0)],
            [line("14:01:00", "controlpoint_captured"), status(4)],
        ]
    )
    result = server.run()
    assert result.passed, result.failures
    assert [event for _, event in result.events] == [
        "map bastogne",
        "game_start",
        "round_start",
        "controlpoint_captured",
    ]
    assert result.teams == rounds.Teams((3, 5), (0, 0), 4, 4)
    assert server.commands[:2] == ["sv_hibernate_when_empty 0", "nwi_bot_only_rounds 1"]
    assert "changelevel bastogne" in server.commands


def test_no_round() -> None:
    """A game that never starts fails after the first check's time."""
    server = FakeServer([[line("14:00:10", "map bastogne")]])
    result = server.run()
    assert not result.passed
    assert result.failures[0] == "no game_start within 240 seconds"
    assert 240 < server.now <= 260


def test_no_deaths() -> None:
    """All events, but bots that never die: it fails at the last check's time."""
    server = FakeServer(
        [
            [
                line("14:00:10", "map bastogne"),
                line("14:00:11", "game_start"),
                line("14:00:20", "round_start"),
                line("14:01:00", "controlpoint_captured"),
                status(0),
            ]
        ]
    )
    result = server.run()
    assert result.failures == ["no bot died"]
    assert server.now > 900


def test_errors_fail_at_once() -> None:
    server = FakeServer(
        [[line("14:00:10", "map bastogne")]],
        errors="L 11/17/2026 - 14:00:05: [SM] Exception reported: Invalid address",
    )
    result = server.run()
    assert result.failures == [
        "SourceMod: L 11/17/2026 - 14:00:05: [SM] Exception reported: Invalid address",
        "no bot died",
    ]
    assert server.now < 30


@pytest.mark.parametrize("coop", [True, False])
def test_pvp_bots_after_the_map(coop: bool) -> None:
    """PvP's bots come once the new map is there, coop adds none."""
    server = FakeServer([[], [line("14:00:10", "map crete")]])
    server.run(coop)
    added = [command for command in server.commands if "_bot_add" in command]
    # Without the plugin's count of the teams, the bots count as dropped: added again, a few times
    assert len(added) == (0 if coop else rounds.READD_TRIES * 2 * rounds.PVP_BOTS)
    if not coop:
        first = server.commands.index("doi_bot_add")
        assert server.commands[:first].count("nwi_test_rounds_status") == 2


def test_bots_of_the_games() -> None:
    """PvP raises the game's quota, which a playlist without bots sets to 0; coop gets the games' AI
    teammates, and in Insurgency a bot that starts the game."""
    # After the map change, whose playlist sets its quota again
    assert rounds.bot_commands(False)[0] == "doi_bot_quota 10"
    assert rounds.bot_commands(False, "insurgency")[0] == "ins_bot_quota 10"
    assert "mp_coop_ai_teammates 1" in rounds.setup_commands(
        True, "ministry_coop", "insurgency"
    )
    assert rounds.bot_commands(True, "insurgency") == ["ins_bot_add"]


def test_bots_the_game_dropped_are_added_again() -> None:
    """Bots on the players' team stay; none there, they're added again, a few times at most."""
    kept = FakeServer([[], [line("14:00:10", "map crete"), status(0)]])
    kept.run(coop=False)
    assert kept.commands.count("doi_bot_add") == rounds.PVP_BOTS
    empty = line(
        "14:00:11",
        "teams 2: 0 bots 0 humans, 3: 3 bots 0 humans, 0 deaths, game state 1",
    )
    dropped = FakeServer([[], [line("14:00:10", "map ministry_coop"), empty]])
    dropped.run(coop=True, game="insurgency")
    assert dropped.commands.count("ins_bot_add") == rounds.READD_TRIES


def test_insurgency_coop_without_a_capture() -> None:
    """Insurgency's AI teammates take no objective without a human player: its coop passes with the
    rounds and deaths alone, Day of Infamy's coop and PvP still need the capture."""
    script = [
        [line("14:00:10", "map ministry_coop"), line("14:00:11", "game_start")],
        [line("14:00:20", "round_start"), status(4)],
    ]
    server = FakeServer([list(lines) for lines in script])
    result = server.run(coop=True, game="insurgency")
    assert result.passed, result.failures
    assert server.now < 60
    assert [check.event for check in rounds.checks(True, "insurgency")] == [
        "game_start",
        "round_start",
    ]
    for coop, game in ((True, "doi"), (False, "insurgency")):
        server = FakeServer([list(lines) for lines in script])
        result = server.run(coop=coop, game=game)
        assert result.failures == ["no controlpoint_captured within 900 seconds"]
