# Day of Infamy Open Configuration

[![Checks](https://github.com/ChrisTX/doi-config/actions/workflows/check.yml/badge.svg)](https://github.com/ChrisTX/doi-config/actions/workflows/check.yml)

The configuration of the Kim Jong Un Day of Infamy servers: the game and
SourceMod settings of each game mode, the MOTDs, the scripts that install and
update a server, and the systemd units that run and monitor it.

For players, [docs/Clients.md](docs/Clients.md) covers the client settings the
servers need. [docs/Cvars.md](docs/Cvars.md) has notes on cvars that don't do
what they seem to, e.g. `sv_visiblemaxplayers`.

## Layout

The repository is laid out like the server's `doi` folder, so its folders can be
placed on top of a server as they are:

- `game` holds what all servers share: the configs in `cfg/doi-config` (see
  [Configs](#configs)) and the SourceMod plugins, their translations and
  configs in `addons/sourcemod`.
- `mods` has the rules of the mods, which are made from the game's map scripts
  (see [Mods](#mods)).
- `servers/<config>` holds what one server adds: its settings in `server.toml`
  (see [Server settings](#server-settings)), its `motd.txt` and its
  advertisements
  (`addons/sourcemod/configs/advertisements.txt`). A server that shares a file
  with another links to it, like `private-mp` to `mp-battles`; the links are
  resolved when the server is set up, as the server only gets its own folder.
- `tools` has the scripts that set up and monitor a server, `deploy` the systemd
  units and the servers' user, `patches` the patch of the server library.

## Usage

`game` belongs into the server's `doi` folder, with `cfg/doi-config` at
`doi/cfg/doi-config`. Source configs can't resolve paths dynamically, so the
configuration only works at that location. The systemd units below set this
up.

### Server settings

A server's settings are its `servers/<config>/server.toml`: what the server is,
the same wherever it runs. What depends on the machine, its ports and
passwords, is in its environment file instead (see below). For example, Coop
Commando's
[`servers/coop-commando/server.toml`](servers/coop-commando/server.toml):

```toml
hostname = "KIM JONG UN's BOOTCAMP | COOP COMMANDO"
playlist = "nwi/coop_commando"
startup_map = "bastogne stronghold"
mapcycle = "doi-config/mapcycle_coop.txt"
workshop = "doi-config/workshop-ids-coop.txt"
launch_options = ["-tickrate", "128"]
configs_after = ["doi-config/basic_coop.cfg"]
```

At each start, `tools/prepare_server.sh` makes the server's `cfg/server.cfg` of
it with `tools/server_config.py`, which describes the keys: the names of the
server and SourceTV, and the configs it runs (see [Configs](#configs)). It also
copies the server's list of workshop items to `subscribed_file_ids.txt` in the
`doi` folder, the list the game downloads and mounts by default. The launcher,
`tools/start_server.sh`, takes the server's slots, whether it's a LAN server,
the first map, the theater and its own options of the command line from it, and
starts it with the workshop if it has a list. Its RCON password is
`RCON_PASSWORD` of its environment file, which `prepare_server.sh` writes to
`cfg/rcon.cfg`.

A server without a `server.toml`, of no config of `servers`, needs its own
`cfg/server.cfg`, e.g. in the secrets.

### Running with systemd

The servers run as system services of the `doi` user, one instance per server,
which share one install of the game. Each server is put together with overlayfs
from read-only layers, top first:

- `/etc/doi-server/secrets`, laid out like the `doi` folder, e.g. the database
  credentials of SourceMod and SourceBans++ in
  `addons/sourcemod/configs/databases.cfg`
- the server's folder in `servers`, if there's one
- this repository's plugins, compiled by `doi-update.service`
- the mods of `mods` and the playlists' configs, made by `doi-update.service`
- `game` of this repository
- `/usr/lib/sourcemod` and `/usr/lib/metamod`: SourceMod, Metamod:Source and
  the plugins from their packages (`sourcemod`, `metamod-source`,
  `sourcemod-sourcebans-pp`, `sourcemod-sourcebans-pp-discord-forward`,
  `sourcemod-advertisements`, `sourcemod-multicolors`, `sourcemod-smjansson`,
  `sourcemod-steamworks`)
- the workshop items of all servers
- the game

Their writable layer starts empty whenever the layers are mounted, so changes
to the layers always show. What the server writes and keeps, like its logs, is
bind-mounted from the server's state folder instead (see
`tools/mount_server.sh`). The layers are mounted while the server runs, in
`/run/doi-server/<server>`.

The units are in `deploy/systemd`, the `doi` user in `deploy/sysusers.d`:

- `doi-update.service` updates the layers (`tools/update_layers.sh`): it pulls
  this repository in `/var/lib/doi-server/doi-config` and runs
  `tools/update_game.sh`, which installs or updates the game in
  `/var/lib/doi-server/game` with SteamCMD, builds the patcher of its server
  library (see [Server patch](#server-patch)), compiles this repository's
  plugins and makes the mods (see [Mods](#mods)) in `/var/lib/doi-server/mods`.
  It runs before the servers start. It also downloads the workshop items of all
  `workshop-ids-*.txt` files into `/var/lib/doi-server/workshop`, once for all
  servers. SteamCMD gets their current versions, which the game itself never
  does once it has an item, and items no list names any more are removed.
- `doi-mount@<server>.service` mounts the layers (`tools/mount_server.sh`)
  after `doi-update.service`, and unmounts them after the server stops. It's
  stopped and restarted with the server, systemd's restarts of the server
  included, and the server only runs with it.
- `doi-server@<server>.service` configures the server
  (`tools/prepare_server.sh`: the plugins SourceBans++ needs, its website from
  `SOURCEBANS_WEBSITE`, `RCON_PASSWORD` in `rcon.cfg`) and runs it. SourceBans++
  finds the server in the panel by its address and port: the address the server
  reports, or `SOURCEBANS_SERVER_IP` if that's a private one, as in a container.
  `SOURCEBANS_SERVER_ID` sets the panel's ID of the server instead. Its ports
  and password come from
  `/etc/doi-server/<server>.env` (`SERVER_PORT`, `TV_PORT`, `CLIENT_PORT`,
  `SERVER_PASSWORD`), the rest of its settings from its `server.toml`. The server
  uses the folder of the same name in `servers`, or the one `SERVER_CONFIG_NAME`
  names; without one, the secrets layer needs a `cfg/server.cfg` as described
  above.
- `tools/srcds_watchdog.py` runs the server and queries it with A2S. The
  service is ready once the server first answers, and systemd's watchdog
  restarts it when it hasn't answered for 90 seconds, at most 6 times an hour.
  The hung server has 30 seconds to dump its core first.
- `doi-servers.target` starts the enabled servers.
- `doi-restart.timer` updates and restarts the servers every day at 06:00. The
  layers mustn't change while servers use them, so `doi-stage.service` updates
  a copy of them in `/var/lib/doi-server/next` while the servers run. The copy
  is reflinked, on btrfs or XFS: it shares the files' data with the layers, so
  it takes only the space of what the update changes, and the servers' files
  stay as they are. Then the servers are stopped, `doi-update.service` puts the
  copy in place, keeping the layers it replaced in
  `/var/lib/doi-server/previous`, and the servers start again: they're only
  down for the restart. Without reflinks, `doi-update.service` updates in place
  while the servers are stopped.
- `doi-update-check.timer` checks the game and the workshop items for updates
  every three hours (`tools/check_updates.py`), and on an update restarts the
  servers like `doi-restart.timer`. The game's depots are compared, not its
  build, as the Steam client library's depot changes on its own, and the
  workshop items must be the versions the players download: theater files that
  differ break the game.

Setting up a server, as root, with the packages above and `steamcmd`, `git`,
`python-a2s`, `gcc` and the 32-bit `lib32-glibc` (for the patcher, see [Server
patch](#server-patch)) installed:

```bash
cp deploy/sysusers.d/doi-server.conf /etc/sysusers.d/
cp deploy/systemd/* /etc/systemd/system/
systemd-sysusers
install -d -o doi -g doi -m 750 /var/lib/doi-server
sudo -u doi git clone https://github.com/ChrisTX/doi-config.git /var/lib/doi-server/doi-config
# The server's settings in /etc/doi-server/coop-commando.env, its secrets in /etc/doi-server/secrets
systemctl enable --now doi-server@coop-commando.service doi-servers.target
systemctl enable --now doi-restart.timer doi-update-check.timer
```

### Running in a container

`deploy/container/Containerfile` builds an image of a server: SourceMod,
Metamod:Source and the plugins from their packages, this repository and its
compiled plugins, and the patcher. The game and the workshop items aren't part
of it, as they may not be passed on: they're in a state folder on the host,
which the image's updater fills with SteamCMD, like `doi-update.service` for
the systemd units, and which the servers mount. The packages come from a local
pacman repository, like the one of aurutils, verified with its signing key: the
build context `repo` is its folder, `REPO_NAME` its name. With Podman, from the
repository's root, for aurutils' `aur` repository in `/var/lib/aurutils-repo`:

```bash
gpg --homedir /etc/pacman.d/gnupg --export -a <key> >repo-key.asc
podman build --format docker --build-context repo=/var/lib/aurutils-repo \
  --build-arg REPO_NAME=aur --secret id=repo-key,src=repo-key.asc \
  -f deploy/container/Containerfile -t doi-server .
```

`deploy/container/test-instance.sh build` does the same with the repository
aurutils uses. The image's commands (`deploy/container/entrypoint.sh`) are the
server, `update [--stage]` and `check`: the updater and the check of
`tools/update_layers.sh` and `tools/check_updates.py` on the state folder,
mounted at `/srv/state`.

`deploy/quadlet` has the units for rootless Podman, the containers'
counterparts of `deploy/systemd`, with the state folder
`~/.local/state/doi-server` and the settings in `~/.config/doi-server`:

- `doi-update.container` and `doi-stage.container` update the state folder in
  place or stage the update in a reflinked copy, as their systemd counterparts.
- `doi-server@<server>.container` runs a server: its settings in
  `~/.config/doi-server/<server>.env`, as for `doi-server@.service`, its secrets
  in `~/.config/doi-server/secrets` (which may be empty), on the host's
  network. The game and the workshop items are mounted with an overlay of the
  container's own (`:O`), the mods read-only. It's ready once the image's
  health check, A2S like the systemd units' watchdog, passes, and restarted
  when the server stops answering. What it keeps goes into volumes.
- `doi-build.service` pulls a clone of this repository and builds the image
  anew; `doi-restart.service` builds, stages, stops the servers, puts the
  update in place and starts them again, with the new image, every day with
  `doi-restart.timer`; `doi-update-check.timer` checks for updates every three
  hours, as for the systemd units.

```bash
cp deploy/quadlet/*.container ~/.config/containers/systemd/
cp deploy/quadlet/*.service deploy/quadlet/*.timer deploy/quadlet/*.target \
  ~/.config/systemd/user/
systemctl --user daemon-reload
# The server's settings in ~/.config/doi-server/coop-commando.env
systemctl --user start doi-update.service
systemctl --user enable --now doi-server@coop-commando.service doi-servers.target
systemctl --user enable --now doi-restart.timer doi-update-check.timer
loginctl enable-linger
```

`SOURCEBANS_SERVER_IP` of the settings is the server's public address, if the
host's is a private one. Images in the OCI format have no health check, hence
`--format docker`.

### Testing locally

`deploy/container/test-instance.sh` runs a server of one of the configs in a
Podman pod, together with a new MariaDB. The database has the tables of
SourceBans++ and SourceMod and the test server registered, the passwords are
generated, and without its config the Discord forward stays silent, so nothing
reaches the live servers. `TEST_ADMIN` makes a SteamID root admin:

```bash
deploy/container/test-instance.sh build
# The game and the workshop items into the state folder: about 20 GB at first
deploy/container/test-instance.sh update
TEST_ADMIN=STEAM_0:0:123 deploy/container/test-instance.sh up coop-commando
deploy/container/test-instance.sh rcon sm plugins list
deploy/container/test-instance.sh down
```

The server is then at this machine's address, port 27015, which `up` prints.
Not at `127.0.0.1`: rootless Podman passes connections from there on from the
pod's own address, and the server drops them. `build` and `up` take the packages
and SourceBans++'s tables from the local pacman repository, which they find like
aurutils: `aur repo --status`, or without aurutils the one repository of
pacman.conf with a `file://` server. `AUR_REPO` and `AUR_DBROOT` name its name
and folder, as for aurutils. `build --testing` builds the image with Arch
Linux's testing repositories, for packages built against them on a machine that
uses them. `tools/rcon.py` is the RCON client, with the password in
`RCON_PASSWORD`.

The systemd units can be tested on this machine as well, set up as in [Running
with systemd](#running-with-systemd), with only the test instance's database:
`up --db-only` starts it at `127.0.0.1:3306` (`TEST_DB_PORT` for another port)
and prints the commands that copy the server's environment file and secrets to
`/etc/doi-server`. `down` removes the database again.

```bash
deploy/container/test-instance.sh up --db-only coop-commando
```

## Server notes

### Engine hunk overflow

The configuration sets `r_hunkalloclightmaps 0`, which prevents crashes on large
maps like `ardennes`. Community maps of that size contain a lot of lightmap data
and otherwise crash the server with an [Engine Hunk
Overflow](https://developer.valvesoftware.com/wiki/Engine_Hunk_Overflow). In
some cases, like when such a map is the server's startup map, the setting also
has to be passed on the server's command line, as `doi-server@.service` does.

### Libraries (Linux)

The game server needs the following 32-bit libraries on Linux, here with the
Arch Linux packages that provide them:

| Library | Arch Linux package |
| --- | --- |
| glibc | `lib32-glibc` |
| libgcc, libstdc++ | `lib32-gcc-libs` |
| SDL3 | `lib32-sdl3` |

The server's binaries only link glibc and libstdc++. The Steam client library
(`steamclient.so`) loads SDL3 while the server runs. SDL2 isn't needed: of the
server's libraries, only `libtier0_srv.so` names it, and servers without it run
and don't try to load it. `update_game.sh` removes the outdated copies of
libgcc, libstdc++, libogg and libvorbis that come with the game, so the system's
libraries are used instead.

SourceMod's MySQL and PostgreSQL extensions need zlib besides, which
`lib32-zlib-ng-compat` or `lib32-zlib` provides; the game itself doesn't use it.

The Steam client library can load these libraries as well, but only in the game
client, not in a server:

| Library | Arch Linux package |
| --- | --- |
| libX11 | `lib32-libx11` |
| PulseAudio (libpulse) | `lib32-libpulse` |

The game server binaries also reference these libraries:

| Library | Arch Linux package |
| --- | --- |
| OpenAL | `lib32-openal` (AUR) |
| util-linux | `lib32-util-linux` |
| freetype2 | `lib32-freetype2` |
| fontconfig | `lib32-fontconfig` |

Only the client code paths in `engine.so` load them, so if a server asks for any
of them, something is wrong. This happened when an update removed BattlEye from
the game [in
2025](https://steamdb.info/depot/462311/history/?changeid=M:9106077001589815964),
until [a second
update](https://steamdb.info/depot/462311/history/?changeid=M:1007577009454669389)
fixed it the next day.

### Configs

A server's configs run once, when it starts, from the `server.cfg` its
`server.toml` makes: its `configs_before`, SourceTV's settings, the settings the
playlist forces, as far as we take them over, then ours, those all servers
share (`basic_settings.cfg`), and its `configs_after`, like those of the coop or
PvP servers (`basic_coop.cfg`, `basic_pvp.cfg`). The game forces a playlist's settings, but the server
library's patch stops it, so `mods/playlists.toml` says which of them the
servers take over; `tools/make_mods.py` makes the playlist's config of them
from the installed game, `cfg/doi-config/playlists/<playlist>.cfg`.

At every map start the game runs its own config of the game mode,
`cfg/default_server_<mode>.cfg`. The `nwi_mode_config` plugin takes the game
mode from it and runs the game mode's configs that exist, each later one
replacing an earlier one's settings:

1. `basic_mode_<coop|pvp>.cfg`: all coop or PvP game modes
2. `basic_mode_<coop|pvp>-<mode>.cfg`: the game mode, in every playlist
3. `playlists/<playlist>-<mode>.cfg`: the settings the playlist forces in the
   game mode, made by `tools/make_mods.py`
4. `mode_<playlist>.cfg`: all game modes of the playlist, e.g.
   `mode_coop_commando.cfg`
5. `mode_<playlist>-<mode>.cfg`: the game mode in the playlist

Whether a game mode is coop or PvP is the game's own distinction (the rules of
the coop modes derive from `CINSRulesCoopBase`), built into the plugin for Day
of Infamy's and Insurgency's game modes; `nwi_mode_category` sets it for a game
mode it doesn't know. Without a playlist (`sv_playlist`), only the first two run.

These configs set their cvars with `nwi_mode_cvar`, which keeps each cvar's
value from before. When the game mode changes, the cvars get those values back,
so a setting of one game mode doesn't stay for the next one. Other plugins get
the game mode from the plugin's include, `nwi_mode_config.inc`: the natives
`NWI_GetGameMode` and `NWI_GetGameModeCategory`, and the forward
`NWI_OnGameModeChanged`.

The `nwi_cvar_unlocker` plugin lifts the game's limits the configs need to
exceed: bounds and flags like cheat of the cvars in
`addons/sourcemod/configs/nwi_cvar_unlocker.cfg`, with a section per game.

`tools/check_configs.py`, a check before each commit, formats the configs (the
cvar bare, its value quoted) and checks them against the game's cvars and
commands in `tools/cvars.json`: unknown names, values out of their bounds, cheat
cvars and the rules above. `tools/dump_cvars.py` makes `tools/cvars.json` from
a running server, after a game update; for the game's own bounds, start it
without the unlocker, e.g. with
`DISABLE_PLUGINS=nwi_cvar_unlocker deploy/container/test-instance.sh up`.

### Tickrate

The servers run at 128 tick (`-tickrate 128` on their command lines, see
`doi-server@.service` and `deploy/container/entrypoint.sh`), where Day of
Infamy's default is 64. `basic_settings.cfg` makes clients send and get 128
updates per second, whatever their own settings, which default to 64.

At 128 tick without a fix, grenades bounce excessively, which once made the
servers go back to 64 tick: at every map start, the game sets the step of its
physics simulation to the tick's interval, so at 128 tick the physics runs at
1/128 s, while the contacts of physics objects like grenades were made for
1/64 s. A grenade that hits the ground hard then rebounds several times and
higher, instead of once.

The `nwi_physics_timestep` plugin keeps the physics step at 1/64 s
(`nwi_physics_timestep 0.015625`, 0 for the game's step): the physics then
simulates on every other tick, and grenades bounce, roll and come to rest as at
64 tick, measured with the same throws on a local server and checked in game.
Everything else, like movement and hit registration, keeps the shorter tick. It
sets the step through `nwi_gamedata`, the plugin that has the game's calls and
hooks for the others (`addons/sourcemod/gamedata/nwi.games.txt`, its include
`nwi_gamedata.inc`), whose gamedata covers Windows as well, found in the game's
server.dll but not tested on a Windows server.

### Server visibility

The game's browser of a playlist's servers hides servers whose players, less
their bots, are outside the playlist's players filter, 0 to 8 in the coop
playlists, so a coop server disappears once it's busy (see
[docs/Cvars.md](docs/Cvars.md)). The `nwi_server_visibility` plugin counts the
players above the playlist's maximum as bots in what the server sends to Steam:
12 players on a coop server are 12 players and 4 bots there, which the browser
counts as 8. The number of players stays true, as do `status` and the server's
own answers. `nwi_visibility_max_humans` sets the maximum: -1 (the default)
takes the playlist's, 0 turns it off.

It doesn't work yet: it needs a pre-callback of DHooks (through
`nwi_gamedata`), which the `sourcemod` package's build doesn't call, unlike
AlliedModders' build of the same version. Until that's fixed, it changes nothing.

### Difficulty scaler

The `nwi_difficulty_scaler` SourceMod plugin adjusts the number of bots to the
number of players, independently of the map's scripting, within the 16 players
of a coop team. It takes the game mode from `nwi_mode_config`, see
[Configs](#configs).

### Mods

The mods add game modes to maps that don't have them, e.g. invasion, the
cooperative offensive, to maps that only have offensive. A map's script
(`maps/<map>.txt`) has a block for each of its game modes, with its control
points, spawn zones and entities. The scripts come from the game's VPKs or from
a map's workshop item, so they aren't part of this repository: each
`mods/<mod>.toml` says which blocks of which maps to copy and how to adjust the
copies, and `tools/make_mods.py` makes the mod folder `custom/<mod>` from the
installed game and workshop items. The mods follow the game's updates, and a
change that a rule no longer fits, e.g. a control point it removes, stops the
update with an error.

```toml
# A workshop map's script comes from its item
[workshop]
tobruk = 823637416

[[copy]]
maps = ["reichswald", "tobruk"]
from = "offensive"
to = "invasion"
# Without these control points, or with these instead of the copied ones
remove_controlpoints = ["regroup_cap"]
# controlpoints = ["occupy_cap", "church_cap", "radiopoint_final"]
# Spawn zones set or added, by their number
# spawnzones = { 3 = "sz_offensive_c" }
```

Braces in the wrong place are repaired where the keys show where a block ends,
e.g. a game mode that starts inside another one, which isn't closed. The tool
says what it repaired. A map whose script only needs that goes into a mod's
`fix` table, e.g. `[fix]` with `maps = ["tobruk"]`: its script is repaired and
formatted, without copies.

With `--check`, the tool makes nothing, but parses every map script of the game
and of the workshop items, as files or in VPKs, and lists those it had to repair
and those it can't, the latter with an exit status of 1. `doi-update.service`
runs it after each update, so its log shows broken scripts of new workshop
maps.

```bash
tools/make_mods.py --game GAME --workshop WORKSHOP OUTPUT mods
tools/make_mods.py --game GAME --workshop WORKSHOP --check
```

`GAME` is the game's install, with `doi` in it, `WORKSHOP` SteamCMD's folder of
the workshop items, and `OUTPUT`, which is replaced, gets the `custom` folder
for the server's `doi` folder.

### Server patch

The game's server library, `doi/bin/server_srv.so`, is patched so it enables
stats with custom content and lifts the playlist restrictions. The patch is
applied in memory, by `tools/doi_patch.c`, so the game's files stay as SteamCMD
installs them, and SteamCMD's updates, which every server needs for the current
Steam client library, don't undo it. srcds loads it with `LD_PRELOAD`: when the
engine has loaded the library, before it initialises it, the patcher writes the
patches of `patches/server_srv.patches` (the list `DOI_PATCH_LIST` names).

Each patch names the function's symbol, the offset in the function and the old
and new bytes. If a function is missing or its bytes aren't the expected ones,
e.g. after a game update, srcds stops with an error instead of running without
all patches. The patcher builds with a 32-bit C compiler, on any Linux
distribution, e.g. for a server of your own:

```bash
gcc -m32 -std=c23 -O2 -shared -fPIC -o doi_patch.so tools/doi_patch.c
LD_PRELOAD=$PWD/doi_patch.so DOI_PATCH_LIST=$PWD/patches/server_srv.patches \
  ./srcds_run -game doi …
```

Built with `DOI_PATCH_FILE` defined, the patcher is a program that applies the
same list to the library's file instead, for a server that can't preload it.
SteamCMD's updates and validation undo that patch, so apply it again after
each. With `--check` it only checks the list against the library and changes
nothing; `doi-update.service` runs this after each update, so a game update
that breaks the patches fails there rather than when the servers start:

```bash
gcc -std=c23 -O2 -DDOI_PATCH_FILE -o doi_patch tools/doi_patch.c
./doi_patch [--check] patches/server_srv.patches …/doi/bin/server_srv.so
```

### GeoIP2 databases

SourceMod and the SourceBans++ web panel both use MaxMind's GeoIP2 databases.
Both ship MMDB files, but those haven't been updated in years. Instead, install
and configure [geoipupdate](https://github.com/maxmind/geoipupdate), which needs
a free MaxMind account and keeps current databases in `/var/lib/GeoIP`.
The `sourcemod` package and the web panel of the
[sourcebans-pp](https://aur.archlinux.org/packages/sourcebans-pp) package link
their databases from there.

## Licence

The configuration, scripts and units are licensed under the [MIT](LICENSE)
licence. The SourceMod plugins written for these servers, `nwi_cvar_unlocker`,
`nwi_difficulty_scaler`, `nwi_gamedata`, `nwi_mode_config`,
`nwi_physics_timestep` and `nwi_server_visibility`, are available under the MIT licence or the GPL-3.0-only with SourceMod's linking
exception, at your choice, so they can be used in other SourceMod projects
either way.

AFK Manager, vendored in `game/addons/sourcemod` together with its include,
translations and configuration, is licensed under the GPL-3.0-only with
SourceMod's linking exception, like its earlier versions. The mods' map scripts
aren't part of this repository: `tools/make_mods.py` makes them from the game's
own when a server is set up, so they remain New World Interactive's.

`REUSE.toml`, the file headers and the `LICENSES` folder say this in the
[REUSE](https://reuse.software/) format.
