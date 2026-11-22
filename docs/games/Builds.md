<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# Which build to run

Notes for server admins on the game's builds. Of both games, Day of Infamy and
Insurgency; what differs between them is said where it does.

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

## Memory and loading

The 32-bit server shares the ~3 GB address-space ceiling of any 32-bit process.
A plain server stays well under it, but mods, large maps and workshop content
all add up, and a mod-heavy server can run out of address space long before the
host runs out of RAM — the same ceiling that makes the 32-bit game crash on
large maps (see [the engine hunk overflow](Clients.md#engine-hunk-overflow) of the clients). The 64-bit
server doesn't have that ceiling; it can use as much memory as the host has.

The 64-bit Windows server through Wine has also loaded noticeably faster for
connecting clients in our testing, which matters most on servers that run many
mods. For a mod-heavy server this, together with the memory headroom, is usually
the deciding factor.

## Robustness

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
