#!/usr/bin/env python3
"""Watch a soak test server, e.g. servers/soak-bots, and log it as TSV.

At each interval it logs the time, the map, the bots, the server's memory (resident set, of srcds in
the container) and the number of sanitiser reports in the container's output, and adds the bots again
when a map change dropped them (doi_bot_add, doi_bot_add_t2). The password comes from RCON_PASSWORD.

Usage: soak_watch.py [--port PORT] [--container NAME] [--hours HOURS] [--interval SECONDS]
                     [--bots PER_TEAM] LOG
"""

import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rcon

# Lines of UBSan's and ASan's reports
REPORT = re.compile(r"runtime error:|ERROR: AddressSanitizer|ERROR: LeakSanitizer")


def command(sock_args: tuple[str, int, str], text: str) -> str:
    """Run a command on the server, over a connection of its own: a map change closes RCON's."""
    sock = rcon.connect(*sock_args)
    try:
        return rcon.run(sock, text)
    finally:
        sock.close()


def container_output(container: str) -> str:
    result = subprocess.run(
        ["podman", "logs", container], capture_output=True, text=True, check=False
    )
    return result.stdout + result.stderr


def resident_mb(container: str) -> str:
    """srcds' resident set in the container, in MB."""
    script = 'pid=$(pgrep -f srcds_linux | head -1) && awk "/VmRSS/ {print int(\\$2 / 1024)}" /proc/$pid/status'
    result = subprocess.run(
        ["podman", "exec", container, "sh", "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or "?"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=27015)
    parser.add_argument(
        "--container", help="the server's container, for its memory and reports"
    )
    parser.add_argument("--hours", type=float, default=3)
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument(
        "--bots",
        type=int,
        default=20,
        help="bots a team, added again below 3/4 of both",
    )
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    password = os.environ.get("RCON_PASSWORD")
    if not password:
        print("RCON_PASSWORD isn't set", file=sys.stderr)
        return 2
    server = (args.host, args.port, password)

    end = time.monotonic() + args.hours * 3600
    with args.log.open("w") as log:
        log.write("time\tmap\tbots\trss_mb\treports\tnote\n")
        while time.monotonic() < end:
            note = "ok"
            try:
                status = command(server, "status")
                map_name = re.search(r"^map\s*:\s*(\S+)", status, re.MULTILINE)
                bots = re.search(r"humans, (\d+) bots", status)
                bot_count = int(bots.group(1)) if bots else 0
                if bot_count < args.bots * 2 * 3 // 4:
                    for team_command in ("doi_bot_add_t2", "doi_bot_add"):
                        for _ in range(args.bots):
                            command(server, team_command)
                    note = "bots added"
            except OSError as error:
                map_name, bot_count, note = None, 0, f"no answer: {error}"
            rss, reports = "-", "-"
            if args.container:
                rss = resident_mb(args.container)
                reports = str(
                    sum(
                        1
                        for line in container_output(args.container).splitlines()
                        if REPORT.search(line)
                    )
                )
            row = (
                datetime.now().strftime("%H:%M:%S"),
                map_name.group(1) if map_name else "?",
                str(bot_count),
                rss,
                reports,
                note,
            )
            log.write("\t".join(row) + "\n")
            log.flush()
            time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
