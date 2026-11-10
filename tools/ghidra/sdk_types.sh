#!/bin/bash
# Builds a Ghidra data type archive of a branch of the Source SDK (hl2sdk, e.g. doi or insurgency):
# compiles sdk_types.cpp and tier1's KeyValues, convar and bitbuf with full DWARF into OUTPUT.o, then
# exports their types and the signatures of their functions into OUTPUT.gdt with Ghidra's headless
# analyser (ExportGdt.java). See README.md.
#   sdk_types.sh [--arch x86|x86_64] [--sdk-root DIR] [--manifests DIR] [--no-gdt] SDK OUTPUT
# The include folders and defines are the ones SourceMod and Metamod:Source build the branch with, from
# its manifest of hl2sdk-manifests. --arch: the server's architecture, x86 by default (both DoI and
# Insurgency); --sdk-root: the folder with the hl2sdk-<SDK> branches, /usr/lib/hl2sdk (the hl2sdk
# package) by default; --manifests: hl2sdk-manifests, the one of metamod-source-src by default; --no-gdt:
# only the object, e.g. for vtable_slots.py. GHIDRA_INSTALL_DIR is Ghidra's folder, /opt/ghidra by
# default.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
arch=x86 sdkroot=/usr/lib/hl2sdk manifests=/usr/src/metamod-source/hl2sdk-manifests gdt=true
while (($#)); do
	case "$1" in
		--arch)
			arch=$2
			shift
			;;
		--sdk-root)
			sdkroot=$2
			shift
			;;
		--manifests)
			manifests=$2
			shift
			;;
		--no-gdt) gdt=false ;;
		-*)
			echo "Unknown option: $1" >&2
			exit 1
			;;
		*) break ;;
	esac
	shift
done
if (($# != 2)); then
	echo "Usage: sdk_types.sh [--arch x86|x86_64] [--sdk-root DIR] [--manifests DIR] [--no-gdt] SDK OUTPUT" >&2
	exit 1
fi
sdk=$sdkroot/hl2sdk-$1
manifest=$manifests/manifests/$1.json
output=$(realpath -m "$2")
if [[ ! -d "$sdk" ]]; then
	echo "No SDK at $sdk" >&2
	exit 1
fi
if [[ ! -f "$manifest" ]]; then
	echo "No manifest at $manifest" >&2
	exit 1
fi

# The defines of SourceMod's Linux builds (hl2sdk-manifests' SdkHelpers.ambuild and SourceMod's
# AMBuildScript), with the branch's from its manifest
flags=(-O0 -g -femit-class-debug-always -fno-eliminate-unused-debug-types -w -std=gnu++14 -fpermissive
	-fno-strict-aliasing -DCOMPILER_GCC -D_LINUX -DLINUX -DPOSIX -DGNUC -DGAME_DLL -DRAD_TELEMETRY_DISABLED
	-D_finite=finite -Dstricmp=strcasecmp -D_stricmp=strcasecmp -D_strnicmp=strncasecmp
	-Dstrnicmp=strncasecmp -D_snprintf=snprintf -D_vsnprintf=vsnprintf -D_alloca=alloca
	-Dstrcmpi=strcasecmp)
case "$arch" in
	x86)
		flags+=(-m32)
		emulation=elf_i386
		;;
	x86_64)
		flags+=(-m64 -DX64BITS -DPLATFORM_64BITS)
		emulation=elf_x86_64
		;;
	*)
		echo "Unknown architecture: $arch (x86 or x86_64)" >&2
		exit 1
		;;
esac
# The manifest's include folders and its defines for Linux and the architecture, without
# NO_MALLOC_OVERRIDE, which breaks memalloc.h without SourceMod's own allocator
mapfile -t manifestflags < <(python3 "$here/sdk_flags.py" "$manifest" "$arch" "$sdk")
flags+=("${manifestflags[@]}" "-I$sdk")

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
# -femit-class-debug-always makes GCC emit classes with vtables in every unit, not only in the one with
# their key function
g++ "${flags[@]}" -c "$here/sdk_types.cpp" -o "$work/sdk_types.o"
objects=("$work/sdk_types.o")
for source in KeyValues convar bitbuf; do
	if [[ -f "$sdk/tier1/$source.cpp" ]]; then
		g++ "${flags[@]}" -c "$sdk/tier1/$source.cpp" -o "$work/$source.o"
		objects+=("$work/$source.o")
	fi
done
ld -m "$emulation" -r "${objects[@]}" -o "$output.o"
echo "Object: $output.o" >&2

if [[ "$gdt" == true ]]; then
	# The DWARF analyser of the import reads the types; the script saves them
	ghidra=${GHIDRA_INSTALL_DIR:-/opt/ghidra}
	export GHIDRA_HEADLESS_MAXMEM=${GHIDRA_HEADLESS_MAXMEM:-16G}
	"$ghidra/support/analyzeHeadless" "$work" sdk-types -import "$output.o" -scriptPath "$here" \
		-postScript ExportGdt.java "$output.gdt" -deleteProject
	echo "Archive: $output.gdt" >&2
fi
