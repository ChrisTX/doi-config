<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# Staying safe as a player

Day of Infamy and Insurgency are old Source games, and their clients still carry
bugs that newer Source games had fixed. This folder has two small, optional
safeguards for players: a launcher wrapper that blocks the dangerous part of a
known game-invite attack, and a server blocklist for the fake servers that
clutter the browser. Neither changes any game file, so neither affects VAC.

## The game-invite attack

A Steam game invite carries a "connect string", which the game adds to its
command line when you accept it. Source games run `+`-commands from that command
line, so an invite can run commands on your client without asking. The known
abuse ([CVE-2021-30481](https://secret.club/2021/04/20/source-engine-rce-invite.html))
points your client's own RCON client at a server the attacker runs
(`+rcon_address`, `+rcon`), which:

- reveals your IP address to them,
- lets them print text into your game console, and
- on a client with the old bug, lets that server send a malformed archive that
  the client unpacks, which can run code on your machine.

Valve removed the responsible commands from their games in April 2021. Day of
Infamy and Insurgency never got that fix: their RCON client is still there, the
2025 Windows update only removed BattlEye, and the Linux clients weren't updated
at all. So the safe thing is not to let an invite reach those commands.

## The launcher wrapper

`safe-launch.sh` (Linux) and `safe-launch.cmd` (Windows) start the game for you
with the dangerous commands removed and everything else kept, so invites to a
real server (`+connect`) and your own launch options still work. They drop these
`+`-commands, which a client never needs, and their arguments:

| Dropped | Why |
| --- | --- |
| `+rcon`, `+rcon_address`, `+rcon_password`, `+rcon_port` | point your RCON client at a server |
| `+host_writeconfig`, `+host_writeconfig_ss` | write to your config, e.g. a key binding, to make the attack stick |
| `+alias` | defines a command that could stand in for the above |

### Install it (Windows)

1. Save `safe-launch.cmd` somewhere of your own, e.g.
   `C:\Users\You\safe-launch.cmd`.
2. In Steam, right-click the game, **Properties**, **General**, and put this in
   **Launch options**, with the path where you saved it:

   ```text
   "C:\Users\You\safe-launch.cmd" %command%
   ```

### Install it (Linux)

1. Save `safe-launch.sh` somewhere of your own and make it executable:
   `chmod +x ~/safe-launch.sh`.
2. In Steam, right-click the game, **Properties**, **General**, and put this in
   **Launch options**:

   ```text
   /home/you/safe-launch.sh %command%
   ```

The game starts as usual. When the wrapper drops something, it prints a line
saying what; set the environment variable `NWI_SAFE_LAUNCH_LOG` to a file path
(Linux) to keep a record.

### What it doesn't cover

The wrapper sees the command line, which the game uses for an invite you accept
**before** the game starts. An invite you accept while the game is **already
running** takes a different path that a launcher can't reach, so:

- don't accept game invites from people you don't know, and
- the game shows a window listing the start parameters before it launches from
  an invite: read it, and cancel if it has `rcon` or settings you didn't expect.

Making your configs read-only is a good extra step: it stops a server writing a
binding or setting into them that would bring the attack back the next time you
play.

## The server blocklist

Source's server browser has a **Blacklisted Servers** tab, which hides servers
you blocklist, including the fake ones that report made-up player counts to look
busy. It reads `cfg/server_blacklist.txt` in the game's config folder. Hiding
those servers is mostly a convenience, but it also helps here: anyone trying to
use the invite attack would want a server that looks busy so people join it, so
a blocklist of fake-count servers makes that harder.

- **One server you've seen:** find it in the browser, right-click it and choose
  to add it to the blocklist. For a range that keeps changing its address, the
  menu's **Class C** option blocklists its `/24` (the first three parts of the
  address).
- **A known-bad list:** HL2DM.ORG keeps a maintained list of spammy Source
  servers at <https://content.hl2dm.org/spamfilter/>. `RogueIPs.txt` is the
  plain list of addresses; `GameSpamFilter.bat` adds them as Windows Firewall
  rules; `Download_Blacklist.php` serves them as a ready `server_blacklist.txt`
  you can save into your `cfg` folder or **Import** on the Blacklist tab. It's a
  general Source list, so some entries won't be Day of Infamy or Insurgency
  servers, which does no harm.
- **The format**, if you edit the file yourself: `server_blacklist.example.txt`
  here shows it, with placeholder addresses from the documentation range (they
  match no real server). Each `server` block has a `name`, an `addr` (the IP,
  without a port to block the whole address) and a `date` (a Unix time).

This is a nuisance filter, not a security measure: it only hides servers from
your browser.
