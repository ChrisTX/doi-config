#!/usr/bin/env python3
"""The check of the plugins' gamedata: moved into the package, nwi_server_kit.check_gamedata (nwi-server check-gamedata), and kept here for
the tools that still call it. Run from a checkout, the package is that of its src/."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nwi_server_kit.check_gamedata import main

if __name__ == "__main__":
    sys.exit(main())
