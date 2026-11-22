<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# Introduction

The configuration of the Kim Jong Un Day of Infamy servers, and the kit that
runs them: the game and SourceMod settings of each game mode, the MOTDs, the
SourceMod plugins, and the tools and units that install, update, run and
monitor a server, of Day of Infamy or Insurgency.

The book has three parts:

- **The games**: what's true of Day of Infamy and Insurgency whatever runs
  them: the clients' settings, cvars that don't do what they seem to, which
  build of the server to run, and the server's libraries.
- **The configuration**: this repository's configs, their servers' settings,
  the plugins, mods and playlists.
- **The server kit**: `nwi-server` and its units, which run the servers with
  systemd or in containers, update them, and gate their workshop items.

A topic of one game says so at its start; the others cover both.

## Layout

The repository is laid out like the server's `doi` folder, so its folders can be
placed on top of a server as they are:

- `game` holds what goes into the servers' game folder (`doi`, `insurgency`):
  `game/common` what servers of both games share, the SourceMod plugins, their
  translations and configs in `addons/sourcemod` and the shared configs in
  `cfg/nwi-config`; `game/<game>` what a game's servers add, Day of Infamy's
  configs in `cfg/doi-config` and Insurgency's in `cfg/nwi-config` (see
  [Configs](configs/Configs.md)). A game's file replaces a common one of the
  same name.
- `mods/<game>` has the rules of the mods of a game, which are made from its map
  scripts (see [Mods](configs/Mods-and-playlists.md#mods)).
- `servers/<config>` holds what one server adds: its settings in `server.toml`
  (see [Server settings](configs/Server-settings.md)), its `motd.txt` and its
  advertisements
  (`addons/sourcemod/configs/advertisements.txt`). A server that shares a file
  with another links to it, like `private-mp` to `mp-battles`; the links are
  resolved when the server is set up, as the server only gets its own folder.
- `workshop` has the approved versions of the servers' workshop items (see
  [Workshop items](kit/Workshop.md)).
- `src/nwi_server_kit` is the Python package of the servers' tools, with the
  command `nwi-server` (`nwi-server` without arguments lists its commands),
  `deploy` the systemd units, the container and the package, `client` the
  players' safe-launch wrapper, `checks` and `tests` what the git hooks, GitHub
  Actions and the tests run, `docs` this book.

`game/common` and `game/<game>` belong into the server's game folder, e.g.
`doi`, with `cfg/doi-config` at `doi/cfg/doi-config`. Source configs can't
resolve paths dynamically, so the configuration only works at that location.
The [systemd units](kit/Systemd.md) and the [containers](kit/Containers.md) set
this up.
