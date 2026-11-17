"""The mods (make_mods.py): the parser of the maps' scripts and its repairs of their braces, the
copies of game modes, the playlists' configs and replacements, of a fake game's files and VPKs."""

from pathlib import Path

import pytest

from nwi_server_kit import update
from nwi_server_kit.make_mods import ModError, check_scripts, make, parse_script

from .conftest import build_vpk


def test_a_script_is_parsed_into_pairs() -> None:
    pairs, repairs = parse_script(
        '"cpsetup.txt"\n{\n\t// a comment\n\t"navfile" "maps/x.nav"\n'
        '\t"stronghold"\n\t{\n\t\t"controlpoint" "a"\n\t\t"controlpoint" "b"\n\t}\n}\n',
        "x.txt",
    )
    assert pairs == [
        (
            "cpsetup.txt",
            [
                ("navfile", "maps/x.nav"),
                ("stronghold", [("controlpoint", "a"), ("controlpoint", "b")]),
            ],
        )
    ]
    assert repairs == []


def test_a_game_mode_in_a_game_mode_closes_it() -> None:
    pairs, repairs = parse_script(
        '"cpsetup.txt" { "stronghold" { "controlpoint" "a" '
        '"firefight" { "controlpoint" "b" } } }',
        "x.txt",
    )
    assert pairs == [
        (
            "cpsetup.txt",
            [
                ("stronghold", [("controlpoint", "a")]),
                ("firefight", [("controlpoint", "b")]),
            ],
        )
    ]
    assert repairs == [
        "closed stronghold before firefight",
        "dropped a closing brace after the end",
    ]


def test_any_key_goes_below_a_game_modes_entities() -> None:
    pairs, _ = parse_script(
        '"cpsetup.txt" { "stronghold" { "entities" { "anything" { "key" "value" } } } }',
        "x.txt",
    )
    assert pairs[0][1] == [
        ("stronghold", [("entities", [("anything", [("key", "value")])])])
    ]


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ('"cpsetup.txt" { "bogus" "1" }', "unexpected 'bogus'"),
        ('"cpsetup.txt" { "navfile" }', "has no value"),
        ('"cpsetup.txt" { { } }', "a block without a key"),
    ],
)
def test_broken_scripts_are_errors(text: str, error: str) -> None:
    with pytest.raises(ModError, match=error):
        parse_script(text, "x.txt")


def test_any_key_goes_without_a_level() -> None:
    pairs, _ = parse_script('"theater" { "bogus" "1" }', "x.theater", level=None)
    assert pairs == [("theater", [("bogus", "1")])]


def test_mods_of_unlisted_maps_are_left_out(tmp_path: Path) -> None:
    """The updater leaves out a mod of a workshop map that none of the servers lists (update.py)."""
    (tmp_path / "stock.toml").write_text('[[copy]]\nmaps = ["bastogne"]\n')
    (tmp_path / "listed.toml").write_text("[workshop]\nkursk = 5\n")
    (tmp_path / "unlisted.toml").write_text("[workshop]\nkursk = 5\ntobruk = 7\n")
    assert [path.name for path in update.used_mods(tmp_path, [5])] == [
        "listed.toml",
        "stock.toml",
    ]


# A map's script with an offensive block: control points a, b and c, and spawn zones
SCRIPT = """\
"cpsetup.txt"
{
    "navfile"	"maps/%s.nav"
    "offensive"
    {
        "attackingteam"	"allies"
        "controlpoint"	"a"
        "controlpoint"	"b"
        "controlpoint"	"c"
        "spawnzones"
        {
            "1"	"sz_a"
            "2"	"sz_b"
        }
        "entities"
        {
            "logic_relay"	{ "targetname" "x" }
        }
    }
}
"""

PLAYLIST = """\
"playlist"
{
    "allowed_maps"	"bastogne"
    "forced_cvars"
    {
        "doi_bot_difficulty"	"2"
        "doi_bot_quota"	"16"
        "mp_timelimit"	"30"
        "stronghold"
        {
            "doi_bot_count_min"	"8"
        }
        "plugins"
        {
            "doi_ignored"	"1"
        }
    }
    "rulesets"
    {
        "american_campaign"	{ "allowed_maps" "carentan" }
        "elite"	{ "allowed_maps" "flakturm" "forced_cvars" { "doi_x" "1" } }
    }
}
"""


@pytest.fixture
def game(tmp_path: Path) -> Path:
    """A Day of Infamy install: a loose map script, and one and two playlists in a split VPK; and a
    workshop map in its item's VPK, with a game mode that isn't closed, at tmp_path/workshop."""
    install = tmp_path / "game"
    (install / "doi/maps").mkdir(parents=True)
    (install / "doi/gameinfo.txt").touch()
    (install / "doi/maps/loose.txt").write_text(SCRIPT % "loose")
    build_vpk(
        install / "doi/pak01.vpk",
        {
            "maps/packed.txt": (SCRIPT % "packed").encode(),
            "scripts/playlists/nwi/coop.playlist": PLAYLIST.encode(),
            "scripts/playlists/nwi/pvp.playlist": PLAYLIST.encode(),
        },
        split=True,
    )
    item = tmp_path / "workshop/steamapps/workshop/content/462310/823"
    item.mkdir(parents=True)
    # offensive isn't closed before stronghold, and the file's block has a brace too many
    broken = SCRIPT.replace(
        "    }\n}\n", '    "stronghold" { "controlpoint" "a" }\n}\n}\n'
    )
    assert broken != SCRIPT
    build_vpk(item / "tobruk.vpk", {"maps/tobruk.txt": (broken % "tobruk").encode()})
    return install


def write_mods(folder: Path, **mods: str) -> Path:
    folder.mkdir(exist_ok=True)
    for name, text in mods.items():
        (folder / f"{name}.toml").write_text(text)
    return folder


def made(output: Path, path: str) -> list:
    """A made file's pairs, as the game would read it."""
    text = (output / path).read_text()
    return parse_script(text, path, level=None)[0]


def mode(pairs: list, name: str) -> list:
    return dict(pairs[0][1])[name]


def test_copies(game: Path, tmp_path: Path) -> None:
    """Copies of a game mode, each right after the block it's made from, so a later copy comes first:
    with control points removed or replaced, spawn zones set; a workshop map's script from its item,
    repaired."""
    mods = write_mods(
        tmp_path / "mods",
        maps="""\
[workshop]
tobruk = 823

[[copy]]
maps = ["loose", "packed", "tobruk"]
from = "offensive"
to = "invasion"
remove_controlpoints = ["b"]
spawnzones = { 3 = "sz_c", 1 = "sz_first" }

[[copy]]
maps = ["loose"]
from = "offensive"
to = "frontline"
controlpoints = ["c", "a"]
""",
    )
    output = tmp_path / "output"
    make(game, tmp_path / "workshop", output, [mods])
    loose = made(output, "custom/maps/maps/loose.txt")
    assert [key for key, _ in loose[0][1]] == [
        "navfile",
        "offensive",
        "frontline",
        "invasion",
    ]
    invasion = mode(loose, "invasion")
    assert [value for key, value in invasion if key == "controlpoint"] == ["a", "c"]
    assert dict(dict(invasion)["spawnzones"]) == {
        "1": "sz_first",
        "2": "sz_b",
        "3": "sz_c",
    }
    frontline = mode(loose, "frontline")
    assert [value for key, value in frontline if key == "controlpoint"] == ["c", "a"]
    # The rest of the block as it was, in its place
    assert [key for key, _ in frontline][:4] == [
        "attackingteam",
        "controlpoint",
        "controlpoint",
        "spawnzones",
    ]
    assert mode(loose, "offensive") == mode(
        made(output, "custom/maps/maps/packed.txt"), "offensive"
    )
    tobruk = made(output, "custom/maps/maps/tobruk.txt")
    assert [key for key, _ in tobruk[0][1]] == [
        "navfile",
        "offensive",
        "invasion",
        "stronghold",
    ]
    # In the game's format: tabs, no escapes, the copies' keys as the mod names them
    assert (
        '\t"invasion"\n\t{\n\t\t"attackingteam"\t"allies"\n'
        in (output / "custom/maps/maps/loose.txt").read_text()
    )


def test_playlists(game: Path, tmp_path: Path) -> None:
    """A playlist's forced settings that the globs take, as configs, a game mode's with
    nwi_mode_cvar; replacements of the playlists, their rulesets but the campaigns' without maps."""
    mods = write_mods(
        tmp_path / "mods",
        playlists="""\
[[playlist]]
name = "nwi/coop"
include = ["doi_*", "mp_timelimit"]
exclude = ["doi_bot_quota"]

[[replace]]
playlists = ["nwi/*"]
exclude = ["nwi/pvp"]
drop = ["allowed_maps", "forced_cvars"]
set = { forced_cvars = { sv_battleye = 0 } }

[[replace.ruleset]]
rulesets = ["*"]
exclude = ["*_campaign"]
drop = ["allowed_maps", "forced_cvars"]
""",
    )
    output = tmp_path / "output"
    make(game, tmp_path / "workshop", output, [mods])
    folder = output / "cfg/doi-config/playlists"
    config = (folder / "nwi/coop.cfg").read_text().splitlines()
    assert config[3:] == ['doi_bot_difficulty "2"', 'mp_timelimit "30"']
    stronghold = (folder / "nwi/coop-stronghold.cfg").read_text().splitlines()
    assert stronghold[3:] == ['nwi_mode_cvar "doi_bot_count_min" "8"']
    assert not (folder / "nwi/coop-plugins.cfg").exists()
    # The playlists the replacement matches, and only those
    assert sorted(path.name for path in folder.glob("nwi/*.playlist")) == [
        "coop.playlist"
    ]
    replaced = dict(made(output, "cfg/doi-config/playlists/nwi/coop.playlist")[0][1])
    assert "allowed_maps" not in replaced
    assert replaced["forced_cvars"] == [("sv_battleye", "0")]
    rulesets = dict(replaced["rulesets"])
    assert rulesets["american_campaign"] == [("allowed_maps", "carentan")]
    assert rulesets["elite"] == []


@pytest.mark.parametrize(
    ("mod", "error"),
    [
        (
            '[[copy]]\nmaps = ["loose"]\nfrom = "offensive"\nto = "offensive"\n',
            "has offensive already",
        ),
        (
            '[[copy]]\nmaps = ["loose"]\nfrom = "raid"\nto = "invasion"\n',
            "has no raid to copy",
        ),
        (
            (
                '[[copy]]\nmaps = ["loose"]\nfrom = "offensive"\nto = "invasion"\n'
                'remove_controlpoints = ["z"]\n'
            ),
            "has no control points z",
        ),
        (
            '[[copy]]\nmaps = ["loose"]\nfrom = "offensive"\nto = "bogus"\n',
            "bogus isn't a game mode",
        ),
        (
            '[[copy]]\nmaps = ["missing"]\nfrom = "offensive"\nto = "invasion"\n',
            "has no maps/missing.txt",
        ),
        (
            '[workshop]\nmissing = 999\n[fix]\nmaps = ["missing"]\n',
            "999 isn't installed",
        ),
        (
            '[[playlist]]\nname = "nwi/coop"\ninclude = ["sv_nothing*"]\n',
            "no forced settings matching",
        ),
        (
            '[[replace]]\nplaylists = ["nwi/none*"]\ndrop = ["x"]\n',
            "no playlist matches",
        ),
        (
            '[[replace]]\nplaylists = ["nwi/coop"]\n[[replace.ruleset]]\nrulesets = ["none"]\ndrop = ["x"]\n',
            "no ruleset matches none",
        ),
        ("[bogus]\n", "unknown tables bogus"),
    ],
)
def test_errors_keep_the_mods(game: Path, tmp_path: Path, mod: str, error: str) -> None:
    """A mod that can't be made is an error, and the mods made before stay as they were."""
    output = tmp_path / "output"
    (output / "custom").mkdir(parents=True)
    (output / "custom/old").touch()
    mods = write_mods(tmp_path / "mods", broken=mod)
    with pytest.raises(ModError, match=error):
        make(game, tmp_path / "workshop", output, [mods])
    assert [path.name for path in (output / "custom").iterdir()] == ["old"]
    assert not output.with_name("output.new").exists()


def test_check_scripts(
    game: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--check: the scripts that had to be repaired and those that can't be."""
    assert check_scripts(game, tmp_path / "workshop") == 0
    assert "repaired: " in capsys.readouterr().err
    (game / "doi/maps/broken.txt").write_text('"cpsetup.txt" { "offensive" {')
    assert check_scripts(game, tmp_path / "workshop") == 1
    assert "4 map scripts, 1 repaired, 1 that can't be" in capsys.readouterr().err


# An Insurgency map's night script: the day script's keys by #base, entities of every game mode with
# an event's condition, and a game mode with its own navigation mesh
INSURGENCY_SCRIPT = """\
"#base" "ministry.txt"

"cpsetup.txt"
{
    "theaterfile"   "default_checkpoint"
    "entities"
    {
        "?halloween"
        {
            "prop_pumpkin" { "origin" "1 2 3" }
        }
    }
    "checkpoint"
    {
        "navfile"   "ministry_coop"
        "attackingteam" "security"
        "controlpoint"  "a"
        "controlpoint"  "b"
        "spawnzones" { "1" "sz_a" }
        "settings" { "respawn" "1" }
    }
}
"""

INSURGENCY_PLAYLIST = """\
"playlist"
{
    "forced_cvars"
    {
        "ins_bot_count_checkpoint_min"  "4"
        "checkpoint" { "mp_cp_capture_time" "30" }
    }
}
"""


@pytest.fixture
def insurgency(tmp_path: Path) -> Path:
    """An Insurgency install: insurgency/ with its gameinfo.txt, a night map's script and a playlist."""
    install = tmp_path / "insurgency-game"
    (install / "insurgency/maps").mkdir(parents=True)
    (install / "insurgency/scripts/playlists/nwi").mkdir(parents=True)
    (install / "insurgency/gameinfo.txt").touch()
    (install / "insurgency/maps/ministry_night.txt").write_text(INSURGENCY_SCRIPT)
    (install / "insurgency/scripts/playlists/nwi/coop.playlist").write_text(
        INSURGENCY_PLAYLIST
    )
    return install


def test_insurgency_scripts(insurgency: Path, tmp_path: Path) -> None:
    """Insurgency's game modes and keys, and a copy that keeps the script's #base."""
    assert check_scripts(insurgency, tmp_path / "no-workshop") == 0
    mods = write_mods(
        tmp_path / "mods",
        night="""\
[[copy]]
maps = ["ministry_night"]
from = "checkpoint"
to = "push"
remove_controlpoints = ["b"]
""",
    )
    output = tmp_path / "output"
    make(insurgency, tmp_path / "no-workshop", output, [mods])
    text = (output / "custom/night/maps/ministry_night.txt").read_text()
    assert text.startswith('"#base"\t"ministry.txt"\n"cpsetup.txt"\n')
    script = made(output, "custom/night/maps/ministry_night.txt")
    blocks = dict(next(value for _, value in script if not isinstance(value, str)))
    assert [value for key, value in blocks["push"] if key == "controlpoint"] == ["a"]
    assert dict(blocks["push"])["navfile"] == "ministry_coop"


def test_insurgency_game_modes(insurgency: Path, tmp_path: Path) -> None:
    """A game mode of Day of Infamy isn't one of Insurgency's; a playlist's game mode block is."""
    mods = write_mods(
        tmp_path / "mods",
        wrong='[[copy]]\nmaps = ["ministry_night"]\nfrom = "checkpoint"\nto = "invasion"\n',
    )
    with pytest.raises(ModError, match="invasion isn't a game mode of insurgency"):
        make(insurgency, tmp_path / "no-workshop", tmp_path / "output", [mods])
    (mods / "wrong.toml").unlink()
    write_mods(
        mods,
        playlists='[[playlist]]\nname = "nwi/coop"\ninclude = ["ins_bot_count_*", "mp_cp_*"]\n',
    )
    output = tmp_path / "output"
    make(insurgency, tmp_path / "no-workshop", output, [mods])
    folder = output / "cfg/doi-config/playlists/nwi"
    assert (folder / "coop.cfg").read_text().splitlines()[3:] == [
        'ins_bot_count_checkpoint_min "4"'
    ]
    assert (folder / "coop-checkpoint.cfg").read_text().splitlines()[3:] == [
        'nwi_mode_cvar "mp_cp_capture_time" "30"'
    ]
