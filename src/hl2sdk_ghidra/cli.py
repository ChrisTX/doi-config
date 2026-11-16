"""hl2sdk-ghidra: the Source SDK (hl2sdk) in Ghidra, for reverse engineering the servers of Source
engine games: the SDK's types and function signatures for the decompiler, a check of SourceMod's
gamedata against a game's binaries, and helpers for vtable slots and byte signatures. It works for any
branch of the SDK that hl2sdk-manifests knows, e.g. doi and insurgency.

A PROGRAM is a binary, a file, imported and analysed into the project (--project, a .gpr file, made if it's
missing; a temporary one without), or a program's path in the project, e.g. /doi/server_srv.so. Ghidra
runs in this process through PyGhidra (GHIDRA_INSTALL_DIR, /opt/ghidra by default); a project open in
Ghidra's GUI is locked, close it there first.
"""

import argparse
import sys
from pathlib import Path

from . import gamedata

PLATFORMS = ("linux", "linux64", "windows", "windows64")


def hex_address(text: str) -> int:
    return int(text, 16)


def types_command(args: argparse.Namespace) -> int:
    from . import gdt, sdk

    branch = sdk.Branch.find(args.sdk, args.sdk_root, args.manifests)
    output = args.output.absolute()
    sdk_object = sdk.compile_object(
        branch, output.with_name(output.name + ".o"), args.arch
    )
    print(f"Object: {sdk_object}", file=sys.stderr)
    if not args.object_only:
        types, signatures = gdt.build(
            sdk_object, output.with_name(output.name + ".gdt")
        )
        print(
            f"Archive: {output}.gdt, {types} types, {signatures} signatures by mangled name",
            file=sys.stderr,
        )
    return 0


def apply_command(args: argparse.Namespace) -> int:
    from . import gdt, ghidra

    with ghidra.target(args.project, args.program, save=True) as found:
        if args.compare:
            gdt.decompile(found, args.functions, args.compare, "before")
        result = gdt.apply(found, args.gdt)
        if args.compare:
            gdt.decompile(found, args.functions, args.compare, "after")
    for skipped in result.skipped:
        print(f"Skipped {skipped}", file=sys.stderr)
    print(
        f"Composites added {result.added}, stand-ins replaced {result.replaced}, "
        f"signatures {result.signatures}, ambiguous {result.ambiguous}"
    )
    return 0


def gamedata_command(args: argparse.Namespace) -> int:
    for entry in gamedata.folder_entries(
        args.gamedata, args.game, args.engine, args.platform
    ):
        print(
            f"{entry.kind}\t{entry.name}\t{entry.value}\t{entry.library or '-'}\t{entry.file}"
        )
    return 0


def check_command(args: argparse.Namespace) -> int:
    from . import check, ghidra

    entries = gamedata.folder_entries(
        args.gamedata, args.game, args.engine, args.platform
    )
    library = args.library or (
        "engine" if "engine" in Path(args.program).name else "server"
    )
    with ghidra.target(args.project, args.program) as found:
        results = check.check(found, entries, library)
    for result in results:
        print(result)
    # NOTHERE isn't a failure: offsets don't name their library, e.g. the engine's in a server library
    return 1 if any(result.status in check.FAILED for result in results) else 0


def vtables_command(args: argparse.Namespace) -> int:
    from . import dwarf

    for method in dwarf.vtable_slots(args.object, args.classes):
        print(method.cls, method.slot, method.name, method.mangled)
    return 0


def signature_command(args: argparse.Namespace) -> int:
    from . import pe

    library = pe.Library(args.dll)
    status = 0
    for address in args.addresses:
        pattern = library.signature(address)
        if pattern is None:
            print(f"{address:#x}: not unique")
            status = 1
        else:
            print(f"{address:#x}: {len(pattern)} bytes {pe.format_signature(pattern)}")
    return status


def parser() -> argparse.ArgumentParser:
    main_parser = argparse.ArgumentParser(
        prog="hl2sdk-ghidra",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = main_parser.add_subparsers(
        dest="command", required=True, metavar="COMMAND"
    )

    command = commands.add_parser(
        "types",
        help="the SDK's types and signatures as a data type archive, OUTPUT.gdt",
        description="Compile the SDK's types against a branch with full DWARF into OUTPUT.o, and "
        "save them and its functions' signatures, by mangled name, as OUTPUT.gdt. The import needs "
        "a lot of memory.",
    )
    command.add_argument(
        "--arch",
        choices=["x86", "x86_64"],
        default="x86",
        help="the server's architecture (%(default)s)",
    )
    command.add_argument(
        "--sdk-root",
        type=Path,
        default=Path("/usr/lib/hl2sdk"),
        help="the folder of the hl2sdk-<SDK> branches (%(default)s)",
    )
    command.add_argument(
        "--manifests",
        type=Path,
        default=Path("/usr/src/metamod-source/hl2sdk-manifests"),
        help="hl2sdk-manifests (%(default)s)",
    )
    command.add_argument(
        "--object-only", action="store_true", help="only the object, e.g. for vtables"
    )
    command.add_argument("sdk", metavar="SDK", help="the branch, e.g. doi")
    command.add_argument(
        "output", type=Path, metavar="OUTPUT", help="the output, without .o or .gdt"
    )
    command.set_defaults(run=types_command)

    command = commands.add_parser(
        "apply",
        help="bring an archive's types and signatures into a program",
        description="Bring the archive's composite types into the program, replace the "
        "demangler's empty stand-ins of the same name, and apply the signatures by the exact "
        "mangled names of its functions; the project is saved.",
    )
    command.add_argument("--project", type=Path, help="the project, a .gpr file")
    command.add_argument(
        "--compare",
        type=Path,
        metavar="FOLDER",
        help="decompile --functions into FOLDER before and after",
    )
    command.add_argument(
        "--functions",
        type=hex_address,
        nargs="+",
        default=[],
        metavar="ADDRESS",
        help="the functions' addresses in hex",
    )
    command.add_argument("gdt", type=Path, metavar="GDT", help="the archive of types")
    command.add_argument("program", metavar="PROGRAM", help="the program")
    command.set_defaults(run=apply_command)

    for name, run, help_text in (
        (
            "gamedata",
            gamedata_command,
            "print the gamedata SourceMod loads for a game, as TSV",
        ),
        (
            "check-gamedata",
            check_command,
            "check the gamedata against a server or engine library",
        ),
    ):
        command = commands.add_parser(name, help=help_text, description=help_text + ".")
        command.add_argument(
            "--platform",
            choices=PLATFORMS,
            default="linux",
            help="whose values (%(default)s)",
        )
        command.add_argument(
            "gamedata",
            type=Path,
            metavar="GAMEDATA",
            help="SourceMod's gamedata folder, e.g. "
            "/usr/lib/sourcemod/addons/sourcemod/gamedata",
        )
        command.add_argument("game", metavar="GAME", help="the game's folder, e.g. doi")
        command.add_argument(
            "engine",
            metavar="ENGINE",
            help="the engine as SourceMod names it, e.g. doi or insurgency",
        )
        if name == "check-gamedata":
            command.add_argument(
                "--project", type=Path, help="the project, a .gpr file"
            )
            command.add_argument(
                "--library",
                choices=["server", "engine"],
                help="the program's library (by its name by default)",
            )
            command.add_argument("program", metavar="PROGRAM", help="the program")
        command.set_defaults(run=run)

    command = commands.add_parser(
        "vtables",
        help="the virtual methods of classes with their slots, from an SDK object's DWARF",
        description="Print the virtual methods of the classes with their vtable slots and mangled "
        "names, from the DWARF of an object of types (--object-only is enough).",
    )
    command.add_argument(
        "object", type=Path, metavar="OBJECT", help="an object of types"
    )
    command.add_argument(
        "classes", nargs="+", metavar="CLASS", help="e.g. IVEngineServer"
    )
    command.set_defaults(run=vtables_command)

    command = commands.add_parser(
        "signature",
        help="unique byte signatures of functions of a Windows library",
        description="Print the shortest unique SourceMod-style byte signature of each function.",
    )
    command.add_argument(
        "dll", type=Path, metavar="DLL", help="the library, e.g. server.dll"
    )
    command.add_argument(
        "addresses",
        type=hex_address,
        nargs="+",
        metavar="ADDRESS",
        help="a function's virtual address in hex, with the image base",
    )
    command.set_defaults(run=signature_command)
    return main_parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return int(args.run(args))
    except (ValueError, OSError) as error:
        print(f"hl2sdk-ghidra: {error}", file=sys.stderr)
        return 1
    # PyGhidra, JPype, pyelftools, capstone or pefile, which only some commands need
    except ImportError as error:
        print(
            f"hl2sdk-ghidra: {error.name or error} is missing, see README.md",
            file=sys.stderr,
        )
        return 1
