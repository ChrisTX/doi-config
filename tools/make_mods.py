#!/usr/bin/env python3
"""The mods of mods/<game>/*.toml: moved into the package, nwi_server_kit.make_mods (nwi-server make-mods), and kept here for
the tools that still call it. Run from a checkout, the package is that of its src/."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nwi_server_kit.make_mods import main

if __name__ == "__main__":
    sys.exit(main())
