#!/usr/bin/env python3
"""Print the compiler flags of an SDK branch's manifest, for sdk_types.sh.

    sdk_flags.py MANIFEST ARCH SDK

MANIFEST is the branch's manifest of hl2sdk-manifests, ARCH x86 or x86_64, SDK the branch's folder.
One flag per line: the manifest's include folders and its defines for Linux and the architecture,
without NO_MALLOC_OVERRIDE, which breaks memalloc.h without SourceMod's own allocator.
"""

import json
import sys


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    with open(sys.argv[1]) as f:
        manifest = json.load(f)
    arch, sdk = sys.argv[2], sys.argv[3]
    for path in manifest.get("include_paths", []):
        print(f"-I{sdk}/{path}")
    linux = manifest.get("linux", {})
    defines = manifest.get("defines", []) + linux.get("defines", [])
    defines += linux.get(arch, {}).get("defines", [])
    for define in defines:
        if define != "NO_MALLOC_OVERRIDE":
            print(f"-D{define}")


if __name__ == "__main__":
    main()
