# SPDX-FileCopyrightText: Christian Pfeiffer
# SPDX-License-Identifier: MIT

"""The stress test of a server's network (instance.py stress): floods of packets at its game port, with
and without the game ports' nftables table (deploy/nftables/nwi-game-ports.nft), while a client queries
the server and starts connections the way players do. With the table it checks that the server keeps
its tick and doesn't restart, that the connection table stays small, and that the client is served
where the table protects it; without the table it only reports, for comparison. With the sanitiser
image, the floods without the table also put the engine's parsers to the test: instance.py fails the
test on a sanitiser report in the server's output.

The floods, RATE packets a second each for SECONDS:
    info-spoofed       A2S_INFO from random addresses
    info-single        A2S_INFO from one address
    malformed          connectionless packets of unknown types, wrong lengths, truncated or oversized
    handshake-spoofed  the challenge requests that start a connection, from random addresses
    junk               random bytes without the connectionless prefix, as game traffic looks

It runs as root of rootless Podman's user namespace (podman unshare), which owns the test instance's
network namespace, that of the pod's infra container (PID). It moves into a network namespace of its own
for the clients, joined to the pod's by a veth (10.201.0.1 and 10.201.0.2), and sends from there. The
spoofed addresses are of 198.18.0.0/15, for benchmarks and never routed: the pod sends their answers back
into the clients' namespace, which drops them, so nothing leaves the two namespaces, and the test refuses
to flood unless that route is there. In the pod's namespace a firewall like a machine's (its input's
policy drop, so with connection tracking) stands in for the server's.

Usage:
    stress.py --pod-pid PID [--tickrate TICKRATE] [--seconds SECONDS] [--rate RATE] [--floods FLOOD,...]
            RULESET
        with the server's RCON password in RCON_PASSWORD, all floods by default; exit status 1 if a
        check failed
    stress.py flood KIND RATE SECONDS ADDRESS PORT
        one flood, from the namespace it runs in (the test runs it)
"""

import argparse
import itertools
import json
import os
import random
import signal
import socket
import statistics
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import a2s

from nwi_server_kit import rcon

POD_ADDRESS = "10.201.0.2"
CLIENT_ADDRESS = "10.201.0.1"
POD_LINK = "nwi-stress"
CLIENT_LINK = "nwi-stress-c"
SPOOFED = "198.18.0.0/15"
SINGLE_SOURCE = "198.18.0.7"
PORT = 27015
GAME_PORTS_TABLE = "nwi-game-ports"
FIREWALL_TABLE = "nwi-stress-firewall"
PREFIX = b"\xff\xff\xff\xff"
INFO = PREFIX + b"TSource Engine Query\x00"
CHALLENGE_REQUEST = PREFIX + b"q" + b"\x01\x02\x03\x04" + b"0000000000\x00"

# A machine's firewall, in the pod's namespace: its input's policy drop, connection tracking for what
# it answers, the game ports open, and RCON for the test's client
FIREWALL = f"""table inet {FIREWALL_TABLE} {{
    chain input {{
        type filter hook input priority filter; policy drop;
        ct state established,related accept
        iif lo accept
        udp dport 27015-27030 accept
        tcp dport {PORT} ip saddr {CLIENT_ADDRESS} accept
    }}
}}
"""
# The clients' namespace doesn't track its own packets: the floods would fill its table
CLIENT_RIG = """table ip nwi-stress-rig {
    chain output { type filter hook output priority raw; policy accept; notrack; }
    chain prerouting { type filter hook prerouting priority raw; policy accept; notrack; }
}
"""

# With the table: the share of the client's queries and connections answered at least, by flood
# (None: not expected, e.g. the queries during a flood of spoofed queries, which no rule can tell apart)
EXPECTED: dict[str, tuple[float | None, float | None]] = {
    "info-spoofed": (None, 0.5),
    "info-single": (0.8, 0.8),
    "malformed": (0.8, 0.8),
    "handshake-spoofed": (0.8, None),
    "junk": (None, None),
}
# With the table, the tick at least, as a share of the tickrate, and the connections tracked at most
TICK_SHARE = 0.9
TRACKED_MAX = 5000


def spoofed_address(rng: random.Random) -> str:
    return f"198.{rng.randint(18, 19)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"


def packet(
    source: str, destination: str, source_port: int, port: int, payload: bytes
) -> bytes:
    """An IPv4 packet of UDP, for a raw socket: the kernel fills in the IP header's checksum, and UDP's
    is optional over IPv4."""
    udp = struct.pack("!HHHH", source_port, port, 8 + len(payload), 0) + payload
    header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        20 + len(udp),
        0,
        0,
        64,
        socket.IPPROTO_UDP,
        0,
        socket.inet_aton(source),
        socket.inet_aton(destination),
    )
    return header + udp


def malformed(rng: random.Random) -> bytes:
    return rng.choice(
        [
            PREFIX + b"X" + rng.randbytes(20),  # a type the engine doesn't know
            INFO + b"\x00\x00",  # A2S_INFO of the wrong length
            PREFIX + b"U" + bytes(7),  # A2S_PLAYER of the wrong length
            PREFIX + b"k" + rng.randbytes(1600),  # a connection, oversized
            PREFIX[:3],  # the prefix, truncated
            PREFIX + rng.randbytes(rng.randint(0, 200)),  # random after the prefix
        ]
    )


# By flood: whether it comes from one address, and its packets
FLOODS: dict[str, tuple[bool, Callable[[random.Random], bytes]]] = {
    "info-spoofed": (False, lambda rng: INFO),
    "info-single": (True, lambda rng: INFO),
    "malformed": (False, malformed),
    "handshake-spoofed": (
        False,
        lambda rng: PREFIX + b"q" + rng.randbytes(4) + b"0000000000\x00",
    ),
    "junk": (False, lambda rng: rng.randbytes(rng.randint(10, 400))),
}


def flood(kind: str, rate: int, seconds: float, address: str, port: int) -> int:
    """Send a flood for seconds, rate packets a second (at least 100, in batches every 10 ms), and
    return how many were sent."""
    single, payload = FLOODS[kind]
    rng = random.Random()
    sent = 0
    batch = max(1, rate // 100)
    end = time.monotonic() + seconds
    with socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW) as sock:
        while (start := time.monotonic()) < end:
            for _ in range(batch):
                source = SINGLE_SOURCE if single else spoofed_address(rng)
                data = packet(
                    source, address, rng.randint(1024, 65535), port, payload(rng)
                )
                try:
                    sock.sendto(data, (address, 0))
                    sent += 1
                # A full send buffer: the packet is lost, as on a real network
                except OSError:
                    pass
            time.sleep(max(0.0, 0.01 - (time.monotonic() - start)))
    return sent


@dataclass
class Served:
    """What the client asked and the server answered."""

    queries: int = 0
    answered: int = 0
    connections: int = 0
    challenged: int = 0
    latencies: list[float] = field(default_factory=list)


def challenge(address: str, port: int) -> bool:
    """Whether the server answers the request that starts a connection (q) with its challenge (A)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(1)
        sock.sendto(CHALLENGE_REQUEST, (address, port))
        try:
            return sock.recv(1500)[4:5] == b"A"
        except OSError:
            return False


def client(address: str, port: int, seconds: float, served: Served) -> None:
    """Query the server every 1.5 s and start a connection every 3 s: below the engine's own limit of 3
    queries a second from an address (sv_max_queries_sec), which would refuse the client itself."""
    end = time.monotonic() + seconds
    next_connection = 0.0
    while (start := time.monotonic()) < end:
        served.queries += 1
        try:
            a2s.info((address, port), timeout=1)
            served.answered += 1
            served.latencies.append((time.monotonic() - start) * 1000)
        except (OSError, a2s.BrokenMessageError, a2s.BufferExhaustedError):
            pass
        if start >= next_connection:
            next_connection = start + 3
            served.connections += 1
            served.challenged += challenge(address, port)
        time.sleep(max(0.0, 1.5 - (time.monotonic() - start)))


def stats_value(stats: str, column: str) -> float | None:
    """A column of RCON's stats, by its name in the header line, e.g. FPS, the server's tick."""
    lines = [line.split() for line in stats.splitlines() if line.strip()]
    for header, values in itertools.pairwise(lines):
        if column in header and len(values) == len(header):
            try:
                return float(values[header.index(column)])
            except ValueError:
                return None
    return None


def dropped(table_json: str) -> int:
    """The packets the counters of an nftables table counted (nft -j list table)."""
    total = 0
    for item in json.loads(table_json).get("nftables", []):
        for expression in item.get("rule", {}).get("expr", []):
            counter = expression.get("counter")
            if isinstance(counter, dict):
                total += int(counter.get("packets", 0))
    return total


@dataclass
class Result:
    """A flood's run, with the table or without."""

    kind: str
    table: bool
    answering: bool = True
    sent: int = 0
    seconds: float = 0.0
    served: Served = field(default_factory=Served)
    tick: float | None = None
    tracked: int = 0
    dropped: int = 0
    restarted: bool = False
    waited: float = 0.0


def share(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


def failures(results: list[Result], tickrate: int) -> list[str]:
    """The checks of the floods with the table, see the module's documentation."""
    found = []
    for result in (result for result in results if result.table):
        kind = result.kind
        if not result.answering:
            found.append(f"{kind}: the server didn't answer before the flood")
            continue
        if result.restarted:
            found.append(f"{kind}: the server restarted")
        if result.tick is None:
            found.append(f"{kind}: RCON didn't answer during the flood")
        elif result.tick < TICK_SHARE * tickrate:
            found.append(
                f"{kind}: tick {result.tick:.1f}, below {TICK_SHARE:.0%} of {tickrate}"
            )
        if result.tracked > TRACKED_MAX:
            found.append(f"{kind}: {result.tracked} connections tracked")
        queries, connections = EXPECTED[kind]
        served = result.served
        if queries is not None and share(served.answered, served.queries) < queries:
            found.append(
                f"{kind}: {served.answered} of {served.queries} queries answered, "
                f"fewer than {queries:.0%}"
            )
        if (
            connections is not None
            and share(served.challenged, served.connections) < connections
        ):
            found.append(
                f"{kind}: {served.challenged} of {served.connections} connections answered, "
                f"fewer than {connections:.0%}"
            )
    return found


HEADER = "flood              table  sent/s  tick    tracked  dropped  queries  connections  restarted"


def row(result: Result) -> str:
    table = "with" if result.table else "without"
    if not result.answering:
        return f"{result.kind:<18} {table:<6} the server didn't answer"
    served = result.served
    tick = f"{result.tick:.1f}" if result.tick is not None else "-"
    rate = result.sent / result.seconds if result.seconds else 0
    return (
        f"{result.kind:<18} {table:<6} {rate:>6.0f}  {tick:<6}  {result.tracked:>7}  "
        f"{result.dropped:>7}  {served.answered:>3}/{served.queries:<3}  "
        f"{served.challenged:>5}/{served.connections:<5}  {'yes' if result.restarted else 'no'}"
    )


def report(results: list[Result]) -> str:
    return "\n".join([HEADER, *map(row, results)])


class Pod:
    """The test instance's network namespace, entered with nsenter, and the server in it."""

    def __init__(self, pid: int, password: str) -> None:
        self.pid = pid
        self.password = password

    def run(
        self, *args: str, stdin: str | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["nsenter", "-t", str(self.pid), "-n", *args],
            input=stdin,
            capture_output=True,
            text=True,
            check=check,
        )

    def tracked(self) -> int:
        # Without a table that tracks connections, the namespace's count isn't there
        result = self.run(
            "cat", "/proc/sys/net/netfilter/nf_conntrack_count", check=False
        )
        return int(result.stdout.strip() or 0) if result.returncode == 0 else 0

    def dropped(self) -> int:
        result = self.run(
            "nft", "-j", "list", "table", "ip", GAME_PORTS_TABLE, check=False
        )
        return dropped(result.stdout) if result.returncode == 0 else 0

    def stats(self) -> str | None:
        """RCON's stats, from the clients' namespace, or None if RCON doesn't answer."""
        try:
            with rcon.connect(POD_ADDRESS, PORT, self.password) as sock:
                return rcon.run(sock, "stats")
        except OSError:
            return None


def here(*args: str, stdin: str | None = None) -> None:
    subprocess.run(args, input=stdin, capture_output=True, text=True, check=True)


def set_up(pod: Pod) -> None:
    """Join the clients' namespace, this process's, to the pod's, see the module's documentation."""
    here("ip", "link", "set", "lo", "up")
    # An MTU above the oversized packets', so that they reach the server rather than fail to send
    pod.run(
        "ip", "link", "add", POD_LINK, "mtu", "9000", "type", "veth",
        "peer", "name", CLIENT_LINK, "mtu", "9000", "netns", f"/proc/{os.getpid()}/ns/net",
    )  # fmt: skip
    pod.run("ip", "addr", "add", f"{POD_ADDRESS}/24", "dev", POD_LINK)
    pod.run("ip", "link", "set", POD_LINK, "up")
    here("ip", "addr", "add", f"{CLIENT_ADDRESS}/24", "dev", CLIENT_LINK)
    here("ip", "link", "set", CLIENT_LINK, "up")
    pod.run("ip", "route", "add", SPOOFED, "via", CLIENT_ADDRESS)
    route = pod.run("ip", "route", "get", SINGLE_SOURCE).stdout
    if f"dev {POD_LINK}" not in route:
        raise SystemExit(
            f"The answers to the spoofed addresses wouldn't come back, not flooding: {route}"
        )
    here("nft", "-f", "-", stdin=CLIENT_RIG)
    pod.run("nft", "-f", "-", stdin=FIREWALL)


def tear_down(pod: Pod) -> None:
    # The clients' namespace goes with this process, the veth with it
    pod.run("nft", "delete", "table", "ip", GAME_PORTS_TABLE, check=False)
    pod.run("nft", "delete", "table", "inet", FIREWALL_TABLE, check=False)
    pod.run("ip", "link", "del", POD_LINK, check=False)


def wait_until(condition: Callable[[], bool], seconds: float) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(2)
    return False


def answers() -> bool:
    try:
        a2s.info((POD_ADDRESS, PORT), timeout=2)
        return True
    except (OSError, a2s.BrokenMessageError, a2s.BufferExhaustedError):
        return False


def run_flood(pod: Pod, kind: str, table: bool, rate: int, seconds: float) -> Result:
    result = Result(kind, table, seconds=seconds)
    # What the flood before left behind: its tracked connections expire, the answered ones after 120 s
    # (nf_conntrack_udp_timeout_stream), and a restarted server comes back
    start = time.monotonic()
    wait_until(lambda: pod.tracked() < 1000, 130)
    answering = wait_until(answers, 240)
    result.waited = time.monotonic() - start
    if not answering:
        result.answering = False
        return result
    before = pod.stats()
    flooding = subprocess.Popen(
        [
            sys.executable,
            __file__,
            "flood",
            kind,
            str(rate),
            str(seconds),
            POD_ADDRESS,
            str(PORT),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    asking = threading.Thread(
        target=client, args=(POD_ADDRESS, PORT, seconds, result.served)
    )
    asking.start()
    time.sleep(seconds / 2)
    during = pod.stats()
    result.tick = stats_value(during, "FPS") if during else None
    result.tracked = pod.tracked()
    asking.join()
    output, _ = flooding.communicate()
    result.sent = int(output.strip() or 0)
    result.dropped = pod.dropped()
    after = pod.stats()
    # Its uptime, in minutes, starts anew when it restarts
    up_before = stats_value(before, "Uptime") if before else None
    up_after = stats_value(after, "Uptime") if after else None
    result.restarted = (
        up_before is not None and up_after is not None and up_after < up_before
    )
    return result


def test(
    pod: Pod, ruleset: str, rate: int, seconds: float, floods: list[str]
) -> list[Result]:
    results = []
    # With the table first: the floods without it can leave the server restarting
    for table in (True, False):
        for kind in floods:
            if table:
                # Anew for each flood, for its counters
                pod.run("nft", "-f", ruleset)
            else:
                pod.run("nft", "delete", "table", "ip", GAME_PORTS_TABLE, check=False)
            result = run_flood(pod, kind, table, rate, seconds)
            print(f"{row(result)}  (waited {result.waited:.0f} s)", flush=True)
            results.append(result)
    return results


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["flood"]:
        kind, rate, seconds, address, port = args[1:]
        print(flood(kind, int(rate), float(seconds), address, int(port)))
        return 0
    parser = argparse.ArgumentParser(
        description="The stress test of a server's network."
    )
    parser.add_argument("--pod-pid", type=int, required=True)
    parser.add_argument("--tickrate", type=int, default=128)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--rate", type=int, default=20000)
    parser.add_argument("--floods", default=",".join(FLOODS))
    parser.add_argument("ruleset")
    options = parser.parse_args(args)
    floods = options.floods.split(",")
    if unknown := set(floods) - set(FLOODS):
        parser.error(f"no such flood: {', '.join(sorted(unknown))}")
    pod = Pod(options.pod_pid, os.environ["RCON_PASSWORD"])
    # Stopped, it still takes its veth and tables out of the pod's namespace
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    os.unshare(os.CLONE_NEWNET)
    print(HEADER, flush=True)
    try:
        set_up(pod)
        if not wait_until(answers, 60):
            raise SystemExit("The server doesn't answer: is the test instance up?")
        results = test(pod, options.ruleset, options.rate, options.seconds, floods)
    finally:
        tear_down(pod)
    print(f"\n{report(results)}")
    latencies = [
        ms for result in results if result.table for ms in result.served.latencies
    ]
    if latencies:
        print(f"Median answer with the table: {statistics.median(latencies):.0f} ms")
    found = failures(results, options.tickrate)
    for failure in found:
        print(f"FAILED: {failure}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
