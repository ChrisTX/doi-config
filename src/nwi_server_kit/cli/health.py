"""The command line of health.py.

Usage:
    nwi-server health [status]          the versions on trial and how far they got
    nwi-server health bless             bless the versions that proved themselves (nwi-bless.service)
    nwi-server health approve VERSION…  bless versions by hand
    nwi-server health retry VERSION…    give versions their tries again, e.g. after a fix elsewhere
"""

import sys

from .. import health, layers
from ..health import bless, bless_all, status_report, version_folder


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    command = args[0] if args else "status"
    try:
        if command == "status" and len(args) <= 1:
            status_report()
        elif command == "bless" and len(args) == 1:
            bless_all()
        elif command in ("approve", "retry") and len(args) > 1:
            with layers.lock(health.LAYERS.resolve()):
                for version in args[1:]:
                    path = version_folder(version)
                    if command == "approve":
                        bless(str(path), "approved by hand")
                    else:
                        layers.renamed(path, layers.tries())
                        print(
                            f"{layers.canonical(path)} is on trial again",
                            file=sys.stderr,
                        )
        else:
            print(__doc__.split("Usage:")[1].split("\n\n")[0].rstrip(), file=sys.stderr)
            return 2
    except (ValueError, OSError) as error:
        print(f"nwi-server health: {error}", file=sys.stderr)
        return 1
    return 0
