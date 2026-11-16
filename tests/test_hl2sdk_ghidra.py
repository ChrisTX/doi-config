"""hl2sdk-ghidra's reading of gamedata, ELF symbols, manifests and DWARF, its check of vtable offsets,
and, where Ghidra is installed, its archive of types and their application."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from hl2sdk_ghidra import check, dwarf, elf, gamedata, sdk

GAMEDATA = """\
"Games"
{
    /* A comment */
    "#default"
    {
        "#supported"
        {
            "game"      "doi"
            "engine"    "insurgency"
        }
        "Offsets"
        {
            "Spawn"
            {
                "linux"     "24"
                "windows"   "23"
            }
        }
        "Signatures"
        {
            "Think"
            {
                "library"   "server"
                "linux"     "@_ZN11CBaseEntity5ThinkEv"
                "windows"   "\\x55\\x8B"
            }
        }
    }
    "#default"
    {
        "#supported"
        {
            "game"  "cstrike"
        }
        "Offsets"
        {
            "Other"
            {
                "linux" "1"
            }
        }
    }
    "doi"
    {
        "Offsets"
        {
            "Spawn"
            {
                "linux" "25"
            }
        }
        "Signatures"
        {
            "Engine"
            {
                "library"   "engine"
                "linux"     "@engine_function"
            }
        }
    }
}
"""


@pytest.fixture
def gamedata_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "gamedata"
    (folder / "sdk.games").mkdir(parents=True)
    (folder / "own.txt").write_text(GAMEDATA)
    (folder / "sdk.games/master.games.txt").write_text(
        '"Game Master"\n{\n'
        '"game.doi.txt"\n{\n"game" "doi"\n}\n'
        '"engine.ins.txt"\n{\n"engine" "insurgency"\n"engine" "doi"\n}\n'
        '"game.tf.txt"\n{\n"game" "tf"\n}\n}\n'
    )
    for name in ("game.doi.txt", "engine.ins.txt", "game.tf.txt"):
        (folder / "sdk.games" / name).write_text(
            f'"Games"\n{{\n"#default"\n{{\n"Offsets"\n{{\n"{name}"\n{{\n"linux" "7"\n'
            "}\n}\n}\n}\n"
        )
    return folder


def test_files_follow_master_games(gamedata_folder: Path) -> None:
    names = [
        str(path.relative_to(gamedata_folder))
        for path in gamedata.files(gamedata_folder, "doi", "doi")
    ]
    assert names == ["own.txt", "sdk.games/game.doi.txt", "sdk.games/engine.ins.txt"]


def test_entries_as_sourcemod_reads_them(gamedata_folder: Path) -> None:
    entries = {
        entry.name: entry
        for entry in gamedata.folder_entries(gamedata_folder, "doi", "doi")
    }
    # The game's own block replaces the #default's value; a #default for another game doesn't count
    assert entries["Spawn"].value == "25"
    assert "Other" not in entries
    assert entries["Think"] == gamedata.Entry(
        "Signatures", "Think", "@_ZN11CBaseEntity5ThinkEv", "server", "own.txt"
    )
    assert entries["engine.ins.txt"].file == "sdk.games/engine.ins.txt"
    windows = {
        entry.name: entry.value
        for entry in gamedata.folder_entries(gamedata_folder, "doi", "doi", "windows")
    }
    # Byte signatures keep their backslashes
    assert windows["Think"] == "\\x55\\x8B"


def test_a_supported_engine_counts(gamedata_folder: Path) -> None:
    names = {
        entry.name
        for entry in gamedata.entries(
            [gamedata_folder / "own.txt"], "insurgency", "insurgency"
        )
    }
    assert names == {"Spawn", "Think"}


def test_symbols(gamedata_folder: Path) -> None:
    found = gamedata.symbols(
        gamedata.entries([gamedata_folder / "own.txt"], "doi", "doi")
    )
    assert [(entry.name, entry.value, entry.library) for entry in found] == [
        ("Think", "_ZN11CBaseEntity5ThinkEv", "server"),
        ("Engine", "engine_function", "engine"),
    ]


def test_elf_symbols() -> None:
    names = elf.symbols(Path("/usr/bin/true"))
    assert any(name.startswith("__libc_start_main") for name in names)


def test_elf_refuses_other_files(tmp_path: Path) -> None:
    (tmp_path / "text").write_text("not an ELF file")
    with pytest.raises(ValueError, match="isn't an ELF file"):
        elf.symbols(tmp_path / "text")


def test_manifest_flags(tmp_path: Path) -> None:
    folder = tmp_path / "hl2sdk-doi"
    folder.mkdir()
    manifest = tmp_path / "manifests/manifests/doi.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "code": 21,
                "define": "DOI",
                "include_paths": ["public", "game/shared"],
                "defines": ["SHARED=1"],
                "linux": {
                    "cflags": ["-Wno-deprecated-volatile"],
                    "defines": ["NO_MALLOC_OVERRIDE", "_LINUX"],
                    "x86": {"defines": ["X86=1"]},
                },
            }
        )
    )
    (manifest.parent / "orangebox.json").write_text(
        json.dumps({"code": 3, "define": "ORANGEBOX"})
    )
    branch = sdk.Branch.find("doi", tmp_path, tmp_path / "manifests")
    # The engines' codes of all manifests, SOURCE_ENGINE the branch's
    assert branch.flags("x86") == [
        f"-I{folder}/public",
        f"-I{folder}/game/shared",
        "-DSHARED=1",
        "-D_LINUX",
        "-DX86=1",
        "-Wno-deprecated-volatile",
        "-DSE_DOI=21",
        "-DSE_ORANGEBOX=3",
        "-DSOURCE_ENGINE=21",
        f"-I{folder}",
    ]
    with pytest.raises(ValueError, match="no SDK"):
        sdk.Branch.find("tf2", tmp_path, tmp_path / "manifests")


def entry(name: str, value: str) -> gamedata.Entry:
    return gamedata.Entry("Offsets", name, value, None, "own.txt")


def test_check_offset() -> None:
    slots: dict[str, list[str | None]] = {
        "CBaseEntity": ["~CBaseEntity", "~CBaseEntity", "Spawn", "Think"],
        "CPlayer": ["~CPlayer", "~CPlayer", "Spawn", "Think", "Weapon_Equip"],
    }
    assert check.check_offset(slots, entry("Spawn", "2")).status == "OK"
    wrong = check.check_offset(slots, entry("Think", "2"))
    assert wrong.status == "WRONG"
    assert (
        str(wrong) == "WRONG   offset Think 2, but Think is at: 3 (2, e.g. CBaseEntity)"
    )
    # A gamedata name that differs from the method's
    assert check.check_offset(slots, entry("WeaponEquip", "4")).status == "OK"
    assert check.check_offset(slots, entry("Missing", "1")).status == "NOTHERE"


SOURCE = """\
struct Base { virtual ~Base(); virtual int first(); virtual int second(int); int x; };
Base::~Base() {}
int Base::first() { return x; }
int Base::second(int value) { return x * value; }
int use(Base &base) { return base.second(base.first()); }
"""


@pytest.fixture(scope="module")
def sdk_object(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("g++") is None:
        pytest.skip("no g++")
    folder = tmp_path_factory.mktemp("object")
    (folder / "base.cpp").write_text(SOURCE)
    subprocess.run(
        [
            "g++",
            "-g",
            "-O0",
            "-c",
            str(folder / "base.cpp"),
            "-o",
            str(folder / "base.o"),
        ],
        check=True,
    )
    return folder / "base.o"


def test_vtable_slots(sdk_object: Path) -> None:
    methods = [
        (method.slot, method.name)
        for method in dwarf.vtable_slots(sdk_object, ["Base"])
    ]
    assert (2, "first") in methods
    assert (3, "second") in methods


GHIDRA = Path(os.environ.get("GHIDRA_INSTALL_DIR", "/opt/ghidra"))


@pytest.mark.skipif(not (GHIDRA / "Ghidra").is_dir(), reason="no Ghidra")
def test_archive_and_apply(sdk_object: Path, tmp_path: Path) -> None:
    """The archive of an object's types and signatures, applied to the object in a project."""
    pytest.importorskip("pyghidra")
    from hl2sdk_ghidra import gdt, ghidra

    types, signatures = gdt.build(sdk_object, tmp_path / "base.gdt")
    assert types > 0
    assert signatures >= 3
    with ghidra.target(tmp_path / "project.gpr", str(sdk_object), save=True) as found:
        result = gdt.apply(found, tmp_path / "base.gdt")
        functions = {
            str(function.getName()): str(function.getSignature().getPrototypeString())
            for function in found.getFunctionManager().getFunctions(True)
        }
    assert result.signatures >= 3
    assert functions["second"] == "int second(Base * this, int value)"
