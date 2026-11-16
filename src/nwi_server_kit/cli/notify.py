"""The command line of notify.py.

Usage:
    nwi-server notify send          send the queued notifications (nwi-notify.service)
    nwi-server notify failed UNIT   queue a notification of a unit that failed
"""

import sys

from ..notify import failed, send


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args == ["send"]:
        return send()
    if len(args) == 2 and args[0] == "failed":
        failed(args[1])
        return 0
    print(__doc__.split("Usage:")[1].split("\n\n")[0].rstrip(), file=sys.stderr)
    return 2
