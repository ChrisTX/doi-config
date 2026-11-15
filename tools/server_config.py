#!/usr/bin/env python3
"""A server's settings: moved into the package, nwi_server_kit.server_config (nwi-server server-config), and
kept here for the tools that still call or import it. Run from a checkout, the package is that of its
src/."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nwi_server_kit.server_config import *
from nwi_server_kit.server_config import main

if __name__ == "__main__":
    sys.exit(main())
