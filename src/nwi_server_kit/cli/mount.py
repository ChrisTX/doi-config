"""The command line of mount.py."""

import os
import subprocess
import sys

from .. import health
from ..mount import mount, unmount


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) == 2 and args[0] == "--unmount":
            unmount(args[1])
        elif len(args) == 2:
            mount(args[0], args[1])
        else:
            print(
                "Usage: nwi-server mount NAME UNIT | nwi-server unmount NAME",
                file=sys.stderr,
            )
            return 2
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"nwi-server mount: {error}", file=sys.stderr)
        return 1
    return 0


def unmount_main(argv: list[str] | None = None) -> int:
    """nwi-server unmount NAME; as ExecStopPost= of the server's unit (SERVICE_RESULT), it first blames
    a failure on the versions on trial (health.py)."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 1 and "SERVICE_RESULT" in os.environ:
        try:
            health.stopped(args[0], os.environ["SERVICE_RESULT"])
        # Whatever goes wrong, the layers are unmounted
        except Exception as error:  # noqa: BLE001
            print(
                f"nwi-server unmount: the health of {args[0]}: {error!r}",
                file=sys.stderr,
            )
    return main(["--unmount", *args]) if len(args) == 1 else main([])
