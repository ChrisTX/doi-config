#!/usr/bin/env python3
"""Print the compiler flags of an SDK branch's manifest, for sdk_types.sh.

One flag per line: the manifest's include folders and its defines for Linux and the architecture,
without NO_MALLOC_OVERRIDE, which breaks memalloc.h without SourceMod's own allocator.
"""

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "manifest",
        type=Path,
        metavar="MANIFEST",
        help="the branch's manifest of hl2sdk-manifests",
    )
    parser.add_argument(
        "arch", choices=["x86", "x86_64"], metavar="ARCH", help="x86 or x86_64"
    )
    parser.add_argument(
        "sdk", metavar="SDK", help="the branch's folder, e.g. /usr/lib/hl2sdk/doi"
    )
    args = parser.parse_args()
    with args.manifest.open() as f:
        manifest = json.load(f)
    arch, sdk = args.arch, args.sdk
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
