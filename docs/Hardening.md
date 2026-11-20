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

The `nwi-server@.service` unit already runs each server as a transient user
(`DynamicUser=yes`) with `NoNewPrivileges=yes`, `ProtectSystem=strict`,
`ProtectHome=yes`, `PrivateTmp=yes` and `PrivateDevices=yes`, so the process
can't write outside its own state, can't see other users' files, and can't gain
privileges.

You can tighten it further, in a drop-in, with directives such as
`LockPersonality=yes` (keeps address-space randomisation on),
`RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`, `RestrictNamespaces=yes`,
`ProtectKernelTunables=yes`, `ProtectKernelModules=yes`,
`ProtectControlGroups=yes`, an empty `CapabilityBoundingSet=` and a
`SystemCallFilter=`. Add these one at a time and test: the game engine is old
and a system-call filter in particular can stop it starting, so a filter wants
checking against a real round before you rely on it.

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

Beyond that, a host firewall can rate-limit the server's UDP port as ordinary
denial-of-service hygiene, the same way you would for any public UDP service.
On Linux, [client/linux-rcon-firewall.md](../client/linux-rcon-firewall.md)
shows the nftables and firewalld shapes for a related rule; the same tools
rate-limit a port.

## Keeping current

The most useful thing of all is to keep the server up to date: `nwi-server
update` pulls the current game, SourceMod and Metamod:Source, which is where
fixes arrive. Report problems of this configuration as in
[SECURITY.md](../SECURITY.md); problems of the game, SourceMod,
Metamod:Source or the plugins belong to their own projects.
