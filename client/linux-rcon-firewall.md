<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# Blocking client RCON at the firewall (Linux)

The wrapper ([README.md](README.md)) stops a game invite from turning on the
client's RCON client. If you never use client RCON yourself — you'd wrap it over
SSH or a VPN anyway — you can also block it at the firewall, as an extra layer
that doesn't depend on the wrapper.

Client RCON is an outbound **TCP** connection to a server's RCON port, which is
the server's game port (27015 by default, and usually in the 27015–27030 range).
The game itself is UDP, and Steam's downloads and matchmaking don't use outbound
TCP in that range, so blocking it costs a client nothing. It's port-based,
though: a server on an unusual RCON port would slip past, which is what the
wrapper is for — this is the belt to its braces.

Pick nftables or firewalld, whichever your system uses. Check the rules apply
cleanly, then confirm Steam and the games still connect.

## nftables

A table of its own, so it sits beside whatever else you run. Put it in a file,
check it, then add it:

```text
table inet nwi-client-rcon {
    chain output {
        type filter hook output priority 0; policy accept;
        # Outbound Source RCON: the client never needs it
        tcp dport 27015-27030 reject with tcp reset
    }
}
```

```bash
sudo nft -c -f nwi-client-rcon.nft   # check it parses
sudo nft -f nwi-client-rcon.nft      # apply it now
```

To keep it after a reboot, add the file to what `/etc/nftables.conf` includes
(or drop it in the include directory your distribution uses), the same way as
your other rules.

## firewalld

firewalld filters incoming traffic by zone; for outgoing traffic it takes a
direct rule:

```bash
sudo firewall-cmd --permanent --direct --add-rule ipv4 filter OUTPUT 0 \
    -p tcp --dport 27015:27030 -j REJECT --reject-with tcp-reset
sudo firewall-cmd --permanent --direct --add-rule ipv6 filter OUTPUT 0 \
    -p tcp --dport 27015:27030 -j REJECT --reject-with tcp-reset
sudo firewall-cmd --reload
```

Remove it again with the same two rules and `--remove-rule`, then `--reload`.

## Blocking it whatever the port

To block client RCON regardless of the port, the firewall has to tell the game's
traffic from everything else, which a port can't. nftables can match the game's
control group (`socket cgroupv2`), so a rule could drop outbound TCP from the
Steam game's cgroup while leaving its UDP game traffic alone. That's more fragile
(the cgroup path depends on how Steam launches the game) and no longer simple, so
the wrapper, which removes the RCON commands before the game ever runs, is the
better tool for the general case.
