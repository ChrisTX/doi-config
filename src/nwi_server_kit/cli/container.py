"""The command line of container.py: the container image's entrypoint.

Usage:
    nwi-server container [server]   run the server (the default)
    nwi-server container update     update the layers of the state folder /srv/state, like
                                    nwi-update.service (nwi-server update --image): the versions of the
                                    games, the workshop items and the mods of the servers of the
                                    environment files in /etc/nwi-server, and the servers' links to them,
                                    STATE/servers/<server>, which they mount
    nwi-server container check      check the state's games and workshop items for updates (nwi-server
                                    check-updates): exit status 0 if there are, 1 if not, 255 if it
                                    can't tell
"""

import os
import subprocess
import sys

from .. import container, launch
from . import check_updates
from . import update as update_cli


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    command = args[0] if args else "server"
    paths = container.Paths()
    if command == "update" and len(args) == 1:
        return update_cli.main(["--image", str(paths.state)])
    if command == "check" and len(args) == 1:
        return check_updates.main([str(paths.state)])
    if command != "server" or len(args) > 1:
        print(__doc__.split("Usage:")[1].rstrip(), file=sys.stderr)
        return 2
    server = os.environ.get("SERVER_NAME") or None
    try:
        container.assemble(paths, server, os.environ.get("SERVER_CONFIG_NAME") or None)
        launch.prepare(paths.root, server or "")
        return launch.start(paths.root)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"nwi-server container: {error}", file=sys.stderr)
        return 1
