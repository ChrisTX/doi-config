# Ghidra tools for the Source SDK

Tools for reverse engineering the servers of Source engine games in Ghidra: the SDK's types and
function signatures for the decompiler, a check of SourceMod's gamedata against a game's binaries, and
helpers for vtable slots and byte signatures. They work for any branch of the SDK that
[hl2sdk-manifests](https://github.com/alliedmodders/hl2sdk-manifests) knows, e.g. `doi` and
`insurgency`.

What they need: the SDK's branches (the `hl2sdk` package, in `/usr/lib/hl2sdk`) and hl2sdk-manifests
(the `metamod-source-src` package's, in `/usr/src/metamod-source/hl2sdk-manifests`), GCC with 32-bit
support for x86 servers, Ghidra (`GHIDRA_INSTALL_DIR`, `/opt/ghidra` by default), and for the Python
scripts pyelftools, pefile, capstone and srctools.

## The SDK's types for the decompiler

1. `sdk_types.sh SDK OUTPUT` compiles `sdk_types.cpp` and tier1's KeyValues, convar and bitbuf against
   the branch, with full DWARF and the include folders and defines SourceMod builds it with (from its
   manifest), into `OUTPUT.o`. Then Ghidra's headless analyser imports the object, whose DWARF
   analyser reads the types, and `ExportGdt.java` saves them as `OUTPUT.gdt`: every type, and each
   function's signature as a function definition under `/SdkFunctions`, named by its mangled name, so
   that overloads (and GCC's several names of constructors and destructors) stay apart.

   ```bash
   tools/ghidra/sdk_types.sh doi ~/ghidra/sdk-types-doi
   tools/ghidra/sdk_types.sh --arch x86_64 tf2 ~/ghidra/sdk-types-tf2
   ```

   The import needs a lot of memory: `GHIDRA_HEADLESS_MAXMEM` is 16G unless set.

2. `symbol_map.sh LIBRARY > LIBRARY.map` lists the library's functions with their mangled names, at
   the addresses Ghidra loads it at.

3. `ApplySdkTypes.java GDT MAP [FOLDER ADDRESS,…]`, run on the library in Ghidra, brings in the
   archive's composite types, replaces the demangler's empty stand-ins of the same name, and applies the
   signatures by exact mangled name. Optionally, it decompiles the functions at the addresses into the
   folder before and after, to compare. In the GUI it runs from the Script Manager (the folder in
   Ghidra's script directories), headless as a post script (whose project path mustn't have a folder
   starting with a dot, like `~/.cache`):

   ```bash
   /opt/ghidra/support/analyzeHeadless ~/ghidra/project doi \
     -import engine_srv.so -scriptPath tools/ghidra \
     -postScript ApplySdkTypes.java ~/ghidra/sdk-types-doi.gdt engine_srv.so.map
   ```

## SourceMod's gamedata against a game's binaries

`gamedata_tsv.py GAMEDATA GAME ENGINE` collects the offsets and signatures SourceMod uses for a game,
from the same files and blocks SourceMod loads (`master.games.txt`, `#default` and `#supported`, the
game's own blocks), e.g. `gamedata_tsv.py /usr/lib/sourcemod/addons/sourcemod/gamedata doi insurgency`
(DoI uses Insurgency's engine files). `CheckGamedata.java TSV LIBRARY`, run on the server or engine
library, checks each vtable offset by the method in that slot of every class's vtable (`OK`, `WRONG`
with the slots the method is in, `NOTHERE` if the library doesn't have it), and each `@symbol`
signature by whether the symbol exists.

## Helpers

- `vtable_slots.py OBJECT CLASS…`: the virtual methods of classes with their vtable slots, from the
  DWARF of an `sdk_types.sh` object (`--no-gdt` is enough), e.g. the interfaces Metamod:Source and
  SourceMod hook, as the SDK's headers lay them out.
- `pe_signature.py DLL ADDRESS…`: unique SourceMod-style byte signatures for functions of a Windows
  library, 32-bit or 64-bit: absolute addresses, the targets of relative calls and jumps, and
  displacements relative to RIP are wildcards.
