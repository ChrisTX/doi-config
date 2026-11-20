<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# Staying safe as a player

Day of Infamy and Insurgency are old Source games, and their clients still carry
bugs that newer Source games had fixed. This folder has an optional safeguard for
players: a small wrapper that the game runs through, which blocks a known
game-invite attack and keeps the server browser's blocklist of fake servers up to
date. It changes no game file, so it doesn't affect VAC.

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

## What the wrapper does

The game runs through the wrapper, which:

- **drops the dangerous `+`-commands** an invite abuses and their arguments, and
  keeps everything else, `+connect` included, so invites to a real server and
  your own launch options still work:

  | Dropped | Why |
  | --- | --- |
  | `+rcon`, `+rcon_address`, `+rcon_password`, `+rcon_port` | point your RCON client at a server |
  | `+host_writeconfig`, `+host_writeconfig_ss` | write to your config to make the attack stick |
  | `+alias` | defines a command that could stand in for the above |

- **refreshes the server blocklist**: it writes the game's
  `cfg/server_blacklist.txt` from [HL2DM.ORG's maintained list](https://content.hl2dm.org/spamfilter/)
  of spammy servers, plus any addresses you put in `blocklist-extra.txt` next to
  the wrapper (one IP per line, `#` for comments). The server browser's
  **Blacklisted Servers** tab then hides them. This is mostly a convenience, but
  it also helps here: an attacker would want a busy-looking server for people to
  join, so hiding the fake-count servers makes that harder. It's best effort — if
  you're offline, the blocklist is left as it is and the game still starts.

The wrapper is `safe-launch.py` on Linux (needs Python 3, which desktop Linux has)
and `safe-launch.cmd` with `safe-launch.ps1` on Windows (Windows PowerShell, which
Windows 10 and 11 have). It's set as the game's Steam launch options, before
`%command%`.

## Installing it

The installer finds Day of Infamy and Insurgency, copies the wrapper to a folder
of its own, sets each game's Steam launch options to run through it, and writes
the blocklist. **Close Steam fully first** (right-click the tray icon, Exit),
because Steam rewrites its settings when it exits. It backs up the file it edits
and changes only these two games' launch options.

1. Put this `client` folder somewhere of your own.
2. Close Steam.
3. Run the installer:
   - **Windows:** double-click `install.cmd`.
   - **Linux:** run `./install.py` in the `client` folder (Python 3).
4. Start Steam and play as usual.

The wrapper does its work each time the game starts. When it drops something, it
prints a line saying what (set `NWI_SAFE_LAUNCH_LOG` to a file path to keep a
record). To add your own bad servers to the blocklist, put their IPs in
`blocklist-extra.txt` next to the wrapper, one per line.

### By hand instead

If you'd rather not run the installer, set the launch options yourself: in Steam,
right-click the game, **Properties**, **General**, and set **Launch options** to
the wrapper's path followed by `%command%` (`"C:\path\safe-launch.cmd" %command%`
on Windows, `/path/safe-launch.py %command%` on Linux, made executable). If the
game already has launch options, put the wrapper and a space right before
`%command%`, keeping the rest.

## What it doesn't cover

The wrapper sees the command line, which the game uses for an invite you accept
**before** the game starts. An invite you accept while the game is **already
running** takes a different path a launcher can't reach, so:

- don't accept game invites from people you don't know, and
- the game shows a window listing the start parameters before it launches from an
  invite: read it, and cancel if it has `rcon` or settings you didn't expect.

Making your configs read-only is a good extra step: it stops a server writing a
binding or setting into them that would bring the attack back the next time you
play.

On Linux, you can also block client RCON at the firewall as an extra layer; see
[linux-rcon-firewall.md](linux-rcon-firewall.md).

`server_blacklist.example.txt` shows the blocklist file's format, if you ever want
to edit it by hand.
