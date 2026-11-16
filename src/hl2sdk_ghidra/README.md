# hl2sdk-ghidra

The Source SDK (hl2sdk) in Ghidra, for reverse engineering the servers of Source engine games: the
SDK's types and function signatures for the decompiler, a check of SourceMod's gamedata against a
game's binaries, and helpers for vtable slots and byte signatures. It works for any branch of the SDK
that [hl2sdk-manifests](https://github.com/alliedmodders/hl2sdk-manifests) knows, e.g. `doi` and
`insurgency`. It's a library, `hl2sdk_ghidra`, and its command, `hl2sdk-ghidra`.

What it needs: the SDK's branches (the `hl2sdk` package, in `/usr/lib/hl2sdk`) and hl2sdk-manifests
(the `metamod-source-src` package's, in `/usr/src/metamod-source/hl2sdk-manifests`), GCC with 32-bit
support for x86 servers, and Ghidra (`GHIDRA_INSTALL_DIR`, `/opt/ghidra` by default), which runs in
the command's process through PyGhidra, with JPype. The ELF's DWARF, the disassembler and Windows'
PE files need pyelftools, capstone and pefile. The project's virtual environment has them all (see
[CONTRIBUTING.md](../../CONTRIBUTING.md)): the `ghidra` extra of `pyproject.toml`.

A program is a binary, imported and analysed into a project (`--project`, a `.gpr` file, made if it's
missing; a temporary project without one), or a program's path in the project, e.g.
`/doi/server_srv.so`. A project open in Ghidra's GUI is locked: close it there first. New imports are
analysed without the "Non-Returning Functions - Discovered" analyser, which flags returning functions
like `Plat_FloatTime` as not returning and hides the calls after them (ghidra#9769).

## The SDK's types for the decompiler

`hl2sdk-ghidra types SDK OUTPUT` compiles `sdk_types.cpp` and tier1's KeyValues, convar and bitbuf
against the branch, with full DWARF and the include folders and defines SourceMod builds it with (from
its manifest), into `OUTPUT.o`. Ghidra imports the object, whose DWARF analyser reads the types, and
saves them as `OUTPUT.gdt`: every type, and each function's signature as a function definition under
`/SdkFunctions`, named by its mangled name, so that overloads (and GCC's several names of
constructors and destructors) stay apart. `GHIDRA_HEADLESS_MAXMEM` is Ghidra's memory, 16G unless set.

```bash
hl2sdk-ghidra types doi ~/ghidra/sdk-types-doi
hl2sdk-ghidra types --arch x86_64 tf2 ~/ghidra/sdk-types-tf2
```

`hl2sdk-ghidra apply --project PROJECT GDT PROGRAM` brings the archive's composite types into the
program, replaces the demangler's empty stand-ins of the same name, and applies the signatures by the
exact mangled names of the program's functions, then saves it. `--compare FOLDER --functions
ADDRESS…` decompiles the functions into the folder before and after, to compare.

```bash
hl2sdk-ghidra apply --project ~/ghidra/doi.gpr ~/ghidra/sdk-types-doi.gdt /doi/engine_srv.so
```

## SourceMod's gamedata against a game's binaries

`hl2sdk-ghidra gamedata GAMEDATA GAME ENGINE` prints the offsets and signatures SourceMod loads for a
game, from the same files and blocks SourceMod loads (`master.games.txt`, `#default` and
`#supported`, the game's own blocks), with ENGINE the engine as SourceMod names it, e.g. `doi`, which
loads Insurgency's engine files too. `hl2sdk-ghidra check-gamedata GAMEDATA GAME ENGINE PROGRAM`
checks them against the server or engine library (`--library`, by the program's name by default):
each vtable offset by the method in that slot of every class's vtable (`OK`, `WRONG` with the slots
the method is in, `NOTHERE` if the library doesn't have it), and each `@symbol` signature by whether
the symbol exists (`OK`, `MISSING`). It fails for `WRONG` and `MISSING`; offsets don't name their
library, so those of the other library are `NOTHERE`, e.g. the engine's client methods in
`server_srv.so`.

```bash
hl2sdk-ghidra check-gamedata --project ~/ghidra/doi.gpr \
  /usr/lib/sourcemod/addons/sourcemod/gamedata doi doi /doi/server_srv.so
```

The servers' update reads gamedata the same way (`nwi-server check-gamedata`, with `gamedata.py` and
`elf.py` of this package, which need only srctools).

## Helpers

- `hl2sdk-ghidra vtables OBJECT CLASS…`: the virtual methods of classes with their vtable slots, from
  the DWARF of a `types` object (`--object-only` is enough), e.g. the interfaces Metamod:Source and
  SourceMod hook, as the SDK's headers lay them out.
- `hl2sdk-ghidra signature DLL ADDRESS…`: unique SourceMod-style byte signatures for functions of a
  Windows library, 32-bit or 64-bit: absolute addresses, the targets of relative calls and jumps, and
  displacements relative to RIP are wildcards.
