"""nwi-rcon: run a command on a server over Source RCON (rcon.py) and print its answer.

The password comes from RCON_PASSWORD, so it doesn't show up in the process list, or with --server
from the server of nwi-server@.service on this machine: its password from /run/nwi-server/rcon/<server>,
which the members of the group nwi-rcon can read (nwi-server prepare, launch.py), and its port, SERVER_PORT
of /etc/nwi-server/<server>.env (NWI_SERVERS_DIR). With --ssh, the command runs on another machine instead, as nwi-rcon
--server there: the password stays on it, and its RCON port needs no opening.

nwi-rcon, also nwi-server rcon, e.g. nwi-rcon --server coop-commando status, or
nwi-rcon --ssh admin@example.org --server coop-commando sm plugins list.
"""

import argparse
import os
import shlex
import subprocess
import sys

from .. import rcon
from ..games import read_env, servers_dir
from ..rcon import connect, run


def main(argv: list[str] | None = None) -> int:
    """Authenticate, run the command and print the answer."""
    parser = argparse.ArgumentParser(
        prog="nwi-rcon",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="the server's address (%(default)s)"
    )
    parser.add_argument(
        "--port", type=int, help="the server's port (27015, or SERVER_PORT of --server)"
    )
    parser.add_argument(
        "--server",
        metavar="NAME",
        help="a server of nwi-server@.service: its password and port, see above",
    )
    parser.add_argument(
        "--ssh",
        metavar="HOST",
        help="run it with --server on HOST over SSH, e.g. admin@example.org",
    )
    parser.add_argument(
        "command",
        nargs="+",
        metavar="COMMAND",
        help="the command and its arguments, joined by spaces",
    )
    args = parser.parse_args(argv)
    if args.server is not None and ("/" in args.server or args.server.startswith(".")):
        parser.error(f"not a server's name: {args.server}")
    if args.ssh is not None:
        if args.server is None:
            parser.error("--ssh needs --server")
        remote = ["nwi-rcon", "--server", args.server, "--", *args.command]
        # ssh passes the command to the remote shell as one string
        return subprocess.run(
            ["ssh", args.ssh, shlex.join(remote)], check=False
        ).returncode
    port = args.port
    password: str | None
    if args.server is not None:
        try:
            password = (rcon.RCON_DIR / args.server).read_text().strip()
            env = servers_dir() / f"{args.server}.env"
            settings = read_env(env) if env.is_file() else {}
        except OSError as error:
            print(f"nwi-rcon: {args.server}: {error}", file=sys.stderr)
            return 1
        if port is None:
            port = int(settings.get("SERVER_PORT", "27015"))
    else:
        password = os.environ.get("RCON_PASSWORD")
        if not password:
            print("RCON_PASSWORD isn't set", file=sys.stderr)
            return 2
    address = f"{args.host}:{port or 27015}"
    try:
        sock = connect(args.host, port or 27015, password)
        with sock:
            answer = run(sock, " ".join(args.command))
    except PermissionError as error:
        print(error, file=sys.stderr)
        return 1
    # Refused, reset or timed out, e.g. while the server starts or stops
    except OSError as error:
        print(f"nwi-rcon: {address}: {error.strerror or error}", file=sys.stderr)
        return 1
    print(answer, end="")
    return 0
