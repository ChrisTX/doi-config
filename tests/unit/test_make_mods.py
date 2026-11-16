"""The parser of the maps' scripts and its repairs of their braces (make_mods.py)."""

from pathlib import Path

import pytest

from nwi_server_kit import update
from nwi_server_kit.make_mods import ModError, parse_script


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
