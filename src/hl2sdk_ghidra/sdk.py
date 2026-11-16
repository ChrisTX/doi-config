"""An object of a branch of the Source SDK (hl2sdk, e.g. doi or insurgency) with full DWARF, which the
types of the decompiler come from (gdt.py): sdk_types.cpp, which includes the headers, and tier1's
KeyValues, convar and bitbuf, whose functions bring their signatures, compiled with the include folders
and defines SourceMod builds the branch with, from its manifest of hl2sdk-manifests."""

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

SDK_ROOT = Path("/usr/lib/hl2sdk")
MANIFESTS = Path("/usr/src/metamod-source/hl2sdk-manifests")
SOURCE = Path(__file__).with_name("sdk_types.cpp")
# The defines of SourceMod's Linux builds (hl2sdk-manifests' SdkHelpers.ambuild and SourceMod's
# AMBuildScript). -femit-class-debug-always: classes with vtables in every unit, not only in the one
# with their key function.
FLAGS = [
    "-O0",
    "-g",
    "-femit-class-debug-always",
    "-fno-eliminate-unused-debug-types",
    "-w",
    "-std=gnu++14",
    "-fpermissive",
    "-fno-strict-aliasing",
    "-DCOMPILER_GCC",
    "-D_LINUX",
    "-DLINUX",
    "-DPOSIX",
    "-DGNUC",
    "-DGAME_DLL",
    "-DRAD_TELEMETRY_DISABLED",
    "-D_finite=finite",
    "-Dstricmp=strcasecmp",
    "-D_stricmp=strcasecmp",
    "-D_strnicmp=strncasecmp",
    "-Dstrnicmp=strncasecmp",
    "-D_snprintf=snprintf",
    "-D_vsnprintf=vsnprintf",
    "-D_alloca=alloca",
    "-Dstrcmpi=strcasecmp",
]
ARCHES = {
    "x86": (["-m32"], "elf_i386"),
    "x86_64": (["-m64", "-DX64BITS", "-DPLATFORM_64BITS"], "elf_x86_64"),
}
# The sources of tier1 compiled along, if the branch has them
TIER1 = ("KeyValues", "convar", "bitbuf")


@dataclass(frozen=True)
class Branch:
    """A branch of the SDK: its name, its folder and its manifest."""

    name: str
    folder: Path
    manifest: Path

    @classmethod
    def find(
        cls, name: str, sdk_root: Path = SDK_ROOT, manifests: Path = MANIFESTS
    ) -> "Branch":
        branch = cls(
            name, sdk_root / f"hl2sdk-{name}", manifests / "manifests" / f"{name}.json"
        )
        if not branch.folder.is_dir():
            raise ValueError(f"no SDK at {branch.folder}")
        if not branch.manifest.is_file():
            raise ValueError(f"no manifest at {branch.manifest}")
        return branch

    def flags(self, arch: str) -> list[str]:
        """The manifest's include folders and its defines for Linux and the architecture, without
        NO_MALLOC_OVERRIDE, which breaks memalloc.h without SourceMod's own allocator."""
        manifest = json.loads(self.manifest.read_text())
        flags = [
            f"-I{self.folder}/{path}" for path in manifest.get("include_paths", [])
        ]
        linux = manifest.get("linux", {})
        defines = manifest.get("defines", []) + linux.get("defines", [])
        defines += linux.get(arch, {}).get("defines", [])
        flags += [f"-D{define}" for define in defines if define != "NO_MALLOC_OVERRIDE"]
        return [*flags, f"-I{self.folder}"]


def compile_object(branch: Branch, output: Path, arch: str = "x86") -> Path:
    """Compile sdk_types.cpp and tier1's sources against the branch for the server's architecture into
    one relocatable object, OUTPUT."""
    if arch not in ARCHES:
        raise ValueError(f"unknown architecture {arch}: {' or '.join(ARCHES)}")
    arch_flags, emulation = ARCHES[arch]
    flags = [*FLAGS, *arch_flags, *branch.flags(arch)]
    sources = [SOURCE] + [
        branch.folder / "tier1" / f"{name}.cpp"
        for name in TIER1
        if (branch.folder / "tier1" / f"{name}.cpp").is_file()
    ]
    with tempfile.TemporaryDirectory() as work:
        objects = []
        for source in sources:
            target = Path(work) / f"{source.stem}.o"
            subprocess.run(
                ["g++", *flags, "-c", str(source), "-o", str(target)], check=True
            )
            objects.append(str(target))
        output.parent.mkdir(parents=True, exist_ok=True)
        if len(objects) == 1:
            shutil.copyfile(objects[0], output)
        else:
            subprocess.run(
                ["ld", "-m", emulation, "-r", *objects, "-o", str(output)], check=True
            )
    return output
