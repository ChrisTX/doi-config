<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# Running a hardened server

Notes for server admins on which build to run and how to keep the server
process contained. None of this is required to run a server; it's the
background for making informed choices, especially the choice of build, which
affects memory, loading speed and robustness all at once and isn't obvious from
the outside.

For problems to report, and how, see [SECURITY.md](../SECURITY.md); problems of
the game itself belong upstream.

## Which build to run

Day of Infamy and Insurgency come in a 32-bit and a 64-bit build, and the
dedicated server can be run three ways. They are not equivalent:

| How you run it | Bits | Memory ceiling | Windows mitigation policies |
| --- | --- | --- | --- |
| Native Linux server | 32-bit only | ~3 GB per process | n/a |
| Windows server through Wine/Proton on Linux | 64-bit | the host's RAM | not applied by Wine |
| Windows server on Windows | 64-bit | the host's RAM | applied |

The native Linux dedicated server exists **only** as a 32-bit build, so a Linux
host that runs the server directly is on 32-bit whether it wants to be or not.
To run the server as 64-bit on a Linux host, run the Windows server through Wine
or Proton.

### Memory and loading

The 32-bit server shares the ~3 GB address-space ceiling of any 32-bit process.
A plain server stays well under it, but mods, large maps and workshop content
all add up, and a mod-heavy server can run out of address space long before the
host runs out of RAM — the same ceiling that makes the 32-bit game crash on
large maps (see [Clients.md](Clients.md), the engine hunk overflow). The 64-bit
server doesn't have that ceiling; it can use as much memory as the host has.

The 64-bit Windows server through Wine has also loaded noticeably faster for
connecting clients in our testing, which matters most on servers that run many
mods. For a mod-heavy server this, together with the memory headroom, is usually
the deciding factor.

### Robustness

The 64-bit builds are compiled with the modern memory-safety mitigations —
address space layout randomisation (ASLR), data execution prevention (DEP) and a
high-entropy address space — which make a server more robust if a flaw is ever
found in the engine or a parser. The 32-bit builds predate some of these. This
is a property of how the binaries were built, not of this configuration, and it
can't be changed from the outside; it's simply another reason the 64-bit server
is the better default where you have the choice.

Running the 64-bit Windows server through Wine or Proton keeps those built-in
binary mitigations, as far as the Linux kernel and Wine provide them. Wine does
not apply Windows' own system-level mitigation policies (the Image File
Execution Options / `Set-ProcessMitigation` settings), so a server on Windows
itself has the strongest enforcement. In practice Wine on Linux is a good
middle ground: 64-bit, the memory headroom and loading speed above, and the
binaries' own mitigations.

## Containing the server process

Whichever build you run, it helps to limit what the server process can reach, so
that a problem in the server stays in the server. The two deployment paths this
repository supports both do this, in their own way.

### systemd

The `nwi-server@.service` unit runs each server as a transient user of its own
(`DynamicUser=yes`) in a sandbox that `systemd-analyze security` rates 2.0, "OK"
(7.5 without it). The server can't write outside its own state, see other
users' files or processes, gain privileges, change the kernel, the clock or the
hostname, create namespaces or turn address space randomisation off. It may
only make the system calls of an ordinary service, and nothing it writes while
it runs can be executed: only `/usr` and its own game files are executable,
`/tmp`, `/dev/shm` and its state aren't. Each part was tried on running Day of
Infamy and Insurgency servers, and the unit's comments say why it's there, and
why the few that are left out are.

What depends on your network goes in a drop-in. On a dedicated server, an
address restriction keeps a compromised server off the rest of your local
network (your router, other machines):

```ini
# /etc/systemd/system/nwi-server@.service.d/addresses.conf
[Service]
IPAddressDeny=10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 fc00::/7 fe80::/10
# The machine's own addresses, and a database on another host
IPAddressAllow=192.168.1.10
```

Allow the machine's own addresses: the server's watchdog asks the server over
them, as the game doesn't answer queries from `127.0.0.1`. A database on the
same machine needs nothing, `localhost` isn't denied. This also shuts out
players on your own network, so it suits a dedicated server, not one at home.

A list of the ports the server may bind (`SocketBindAllow=`) doesn't work:
Steam's networking binds its sockets to port 0, any free port, which such a list
refuses, and the server never comes up.

One directive to **leave off the game server**: `MemoryDenyWriteExecute=yes`.
SourceMod's SourcePawn engine compiles plugins to native code at runtime and
needs to make freshly written memory executable, which that directive forbids —
it would stop SourceMod loading. (The `nwi-metrics.service` unit, which is plain
Python with no such compiler, does use it, which is why you'll see it there and
not on the server.)

### Containers

The container path gets the same containment from the runtime: the image runs as
a non-root user, and you can run it with a read-only root filesystem, dropped
capabilities, `no-new-privileges` and a seccomp profile. The effect is the same
as the systemd directives above — the server process can touch only what it
needs — reached through the container runtime rather than the unit file.

## Network

The servers pin the engine's query rate limits in
[basic_settings.cfg](../game/common/cfg/nwi-config/basic_settings.cfg)
(`sv_max_queries_sec` and its companions), so the amount of answering the server
will do to the A2S query port is bounded. Those are the engine's own defaults,
set explicitly so a config reset can't drop them.

### Flood protection with nftables

[deploy/nftables/nwi-game-ports.nft](../deploy/nftables/nwi-game-ports.nft) is a
table of its own, loaded beside your firewall, that protects the game ports from
floods before they reach the server:

- The game ports' packets aren't tracked, so a flood from spoofed addresses
  can't fill the connection table. A full table refuses every new connection to
  the machine, RCON and SSH included.
- Game traffic passes untouched. Connectionless packets, the queries and the
  handshake of a connection, pass only with a type the engine answers and that
  type's length.
- Each address may send 20 of those a second. Each server has a budget for
  queries and one for handshakes, for all addresses together: a flood of
  queries can't keep players from joining, and a flood at one server doesn't
  use up another's. The queries' budget, 40 a second, stays below the engine's
  own limit of 60 (`sv_max_queries_sec_global`): with more let through, the
  engine sometimes turned joins away too.

The engine itself answers a query from an address it hasn't seen with a
challenge smaller than the request, so the servers can't be used to amplify
floods at others; the table protects the servers and the machine.

Set its `game_ports` to your servers' game and SourceTV ports, then load it with
`nft -f nwi-game-ports.nft`, or include it from `/etc/nftables.conf`. It opens
no port: your firewall still has to accept the game ports, and for untracked
packets, which these are. A rule like `udp dport 27015-27030 accept` does; one
limited to `ct state new` doesn't. With firewalld, check that its rule for the
ports includes `untracked` (`nft list ruleset`). `nft list table ip
nwi-game-ports` shows what it dropped.

Measured with `tests/integration/instance.py stress` on the test servers of Day
of Infamy (128 tick) and Insurgency (64 tick): floods of 20,000 packets a second
for 20 seconds, while a client queried the server every 1.5 seconds and started
a connection every 3. With the table, both kept their tick in every case, and at
most 26 connections were tracked:

| Flood | With the table | Without |
| --- | --- | --- |
| Queries from spoofed addresses | all joins answered | 1 of 6 joins, ~198,000 tracked |
| Queries from one address | everything answered | nearly everything answered |
| Malformed packets | everything answered | 1 of 6 joins, up to 262,144 tracked |
| Handshakes from spoofed addresses | all queries, 2 to 4 of 7 joins | 1 of 6 joins, up to 262,144 tracked |
| Junk shaped like game traffic | answers unchanged | answers unchanged, ~200,000 tracked |

262,144 was the test machine's limit: a full table drops every new connection to
the machine.

Without the table, a full connection table also drops the server's own
watchdog's queries, and the watchdog then takes the server for hung and aborts
it: under a long enough flood, a server can restart again and again.

Three things it can't do. During a flood of spoofed queries the server drops out
of the server browser: no rule can tell a spoofed query from a real one, only the
engine's challenge can, and it comes after the first packet; joining still
works. During a flood of spoofed handshakes, players who join compete with it
for the server's budget for handshakes and may need a few tries, for the same
reason. And packets shaped like game traffic can't be filtered without the
connection state the table deliberately doesn't keep; the engine drops those
from addresses that never connected cheaply.

Windows Firewall can't look inside packets or limit each address: open only the
game ports (UDP), keep RCON closed, and rely on the query limits above and your
host's protection against floods.

### RCON

RCON is unencrypted: the password, and every command after it, cross the
network in the clear. Treat encrypted RCON as a rule of its own, and never
expose the RCON port to the internet directly. Administer it over an encrypted
channel instead -- an SSH tunnel, a VPN such as WireGuard, or IPsec -- or bind
it to `localhost` and forward a port to it. Otherwise anyone who can read the
traffic learns the password and can then run any command on the server, and
anyone who can tamper with it can alter what passes; encrypting the channel
closes both, with no exploit involved.

As a second layer, restrict the RCON port at the firewall to the address or VPN
you administer from, and set the engine's own brute-force limits
(`sv_rcon_maxfailures`, `sv_rcon_minfailures`, `sv_rcon_banpenalty`, which
defaults to no ban) so repeated wrong passwords are slowed and banned.

## Keeping current

The most useful thing of all is to keep the server up to date: `nwi-server
update` pulls the current game, SourceMod and Metamod:Source, which is where
fixes arrive. Report problems of this configuration as in
[SECURITY.md](../SECURITY.md); problems of the game, SourceMod,
Metamod:Source or the plugins belong to their own projects.
