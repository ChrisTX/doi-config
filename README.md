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
- `mods/<game>` has the rules of the mods of a game, which are made from its map
  scripts (see [Mods](#mods)).
- `servers/<config>` holds what one server adds: its settings in `server.toml`
  (see [Server settings](#server-settings)), its `motd.txt` and its
  advertisements
  (`addons/sourcemod/configs/advertisements.txt`). A server that shares a file
  with another links to it, like `private-mp` to `mp-battles`; the links are
  resolved when the server is set up, as the server only gets its own folder.
- `tools` has the scripts that set up and monitor a server, `deploy` the systemd
  units and the servers' user.

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

With `ruleset`, a server runs one of its playlist's rulesets, e.g. a campaign
of Coop Commando, `ruleset = "american_campaign"`, which keeps its maps and
teams (see [Playlists](#playlists)).

With `game = "insurgency"`, a server runs Insurgency instead of Day of Infamy,
like the test server `servers/ins-test`. The tools only keep the apps of the
games' dedicated servers (`tools/games.py`) and find the rest: the depots,
the game's folder (`doi` or `insurgency`, the one with `gameinfo.txt`) and the
workshop's app of the items. The configs of `game/cfg/doi-config` are Day of
Infamy's.

At each start, `tools/prepare_server.sh` makes the server's `cfg/server.cfg` of
it with `tools/server_config.py`, which describes the keys: the names of the
server and SourceTV, and the configs it runs (see [Configs](#configs)). It also
copies the server's list of workshop items to `subscribed_file_ids.txt` in the
`doi` folder, the list the game downloads and mounts by default. The launcher,
`tools/start_server.sh`, takes the server's slots, whether it's a LAN server,
the first map, the theater and its own options of the command line from it, and
starts it with the workshop if it has a list. Its passwords and other secrets
are credentials (see [Secrets](#secrets)).

A server without a `server.toml`, of no config of `servers`, needs its own
`cfg/server.cfg`.

### Running with systemd

The servers run as system services, one instance per server, which share one
install of each game. The games, and the workshop items, are those of the
servers: each `/etc/nwi-server/<server>.env` is a server, its game its config's
or `GAME` of its environment file without one (`tools/games.py`). Each server
and the updater run as users of their own (`DynamicUser=`): a server can't
change another's files, nor the layers they share, which the updater makes. Each
server is put together with overlayfs from read-only layers, top first:

- the server's folder in `servers`, if there's one
- this repository's plugins, compiled by `nwi-update.service`
- the mods of `mods/<game>` and the playlists' configs, made by
  `nwi-update.service`
- `game` of this repository
- `/usr/lib/sourcemod` and `/usr/lib/metamod`: SourceMod, Metamod:Source and
  the plugins from their packages (`sourcemod`, `metamod-source`,
  `sourcemod-sourcebans-pp`, `sourcemod-sourcebans-pp-discord-forward`,
  `sourcemod-advertisements`, `sourcemod-multicolors`, `sourcemod-smjansson`,
  `sourcemod-steamworks`)
- the workshop items of the game's servers
- the game

Their writable layer starts empty whenever the layers are mounted, so changes
to the layers always show. What the server writes and keeps, like its logs, is
bind-mounted from the server's state folder, `/var/lib/nwi-server/servers/<server>`,
instead. The layers are mounted while the server runs, in
`/run/nwi-server/<server>`, mapped to the server's user (see
`tools/mount_server.sh`).

The units are in `deploy/systemd`, the group `nwi-rcon` in `deploy/sysusers.d`.
They run the tools installed with them (`make install`, or the package of
`deploy/arch/PKGBUILD`), in `/usr/lib/nwi-server-kit`, which read the configs
from the servers' clone of this repository in
`/var/lib/nwi-server/layers/config`
(`NWI_CONFIG`, see `tools/games.py`). SourceMod and Metamod:Source are those of
`SOURCEMOD_DIR` and `METAMOD_DIR`, `/usr/lib/sourcemod` and `/usr/lib/metamod`
by default.

- `nwi-update.service` updates the layers (`tools/update_layers.sh`), its state
  `/var/lib/nwi-server/layers`: it pulls this repository in `config`, compiles
  its plugins and runs `tools/update_game.sh` for each game of the servers,
  which installs or updates the game in `<game>/game` with SteamCMD, checks it
  against the plugins' gamedata (see [Playlists](#playlists)) and makes the
  game's mods (see [Mods](#mods)) in `<game>/mods`. It runs before the servers
  start. It also downloads the workshop items of the game's servers' lists into
  `<game>/workshop`, once for all of them. SteamCMD gets their current versions,
  which the game itself never does once it has an item, and items no list names
  any more are removed. The layers of a state folder from before Insurgency, in
  the state itself, are moved into `doi` once.
- `nwi-server@<server>.service` mounts the layers at every start
  (`tools/mount_server.sh`), configures the server (`tools/prepare_server.sh`:
  its secrets, the plugins SourceBans++ needs, its website from
  `SOURCEBANS_WEBSITE`) and runs it. SourceBans++ finds the server in the panel
  by its address and port: the address the server reports, or
  `SOURCEBANS_SERVER_IP` if that's a private one, as in a container.
  `SOURCEBANS_SERVER_ID` sets the panel's ID of the server instead. Its ports
  come from `/etc/nwi-server/<server>.env` (`SERVER_PORT`, `TV_PORT`,
  `CLIENT_PORT`), which has no secrets, the rest of its settings from its
  `server.toml`. The server uses the folder of the same name in `servers`, or
  the one `SERVER_CONFIG_NAME` names; without one, `GAME` says its game, `doi`
  by default.
- `tools/srcds_watchdog.py` runs the server and queries it with A2S. The
  service is ready once the server first answers, and systemd's watchdog
  restarts it when it hasn't answered for 90 seconds, at most 6 times an hour.
  The hung server has 30 seconds to dump its core first.
- `nwi-servers.target` starts the enabled servers.
- `nwi-restart.timer` updates and restarts the servers every day at 06:00. The
  layers mustn't change while servers use them, so `nwi-stage.service` updates
  a copy of them in `/var/lib/nwi-server/layers/next` while the servers run. The copy
  is reflinked, on btrfs or XFS: it shares the files' data with the layers, so
  it takes only the space of what the update changes, and the servers' files
  stay as they are. Then the servers are stopped, `nwi-update.service` puts the
  copy in place, keeping the layers it replaced in
  `/var/lib/nwi-server/layers/previous`, and the servers start again: they're only
  down for the restart. Without reflinks, `nwi-update.service` updates in place
  while the servers are stopped.
- `nwi-update-check.timer` checks the games and the workshop items for updates
  every three hours (`tools/check_updates.py`), and on an update restarts the
  servers like `nwi-restart.timer`. The game's depots are compared, not its
  build, as the Steam client library's depot changes on its own, and the
  workshop items must be the versions the players download: theater files that
  differ break the game.

Setting up a server: the package of the tools and units, built from this
checkout's commits, which also installs `steamcmd`, `git`, `python-a2s`,
`python-srctools`, SourceMod and Metamod:Source, and the plugin packages above:

```bash
cd deploy/arch && makepkg -si && cd -
sudo pacman -S --needed --asdeps sourcemod-sourcebans-pp \
  sourcemod-sourcebans-pp-discord-forward sourcemod-advertisements \
  sourcemod-multicolors
```

Then, as root, with the server's settings in `/etc/nwi-server/coop-commando.env`
and its secrets as credentials (see [Secrets](#secrets)), and this repository
cloned once into the updater's state, as its user:

```bash
install -d /var/lib/nwi-server
systemd-run --wait -p DynamicUser=yes -p StateDirectory=nwi-server/layers \
  git clone https://github.com/ChrisTX/doi-config.git /var/lib/nwi-server/layers/config
systemctl enable --now nwi-server@coop-commando.service nwi-servers.target
systemctl enable --now nwi-restart.timer nwi-update-check.timer
```

### Secrets

A server's secrets are systemd credentials, encrypted in
`/etc/credstore.encrypted`, bound to the machine's TPM if it has one, which
systemd only decrypts for the server's unit. `nwi-server.<name>` is for every
server, `nwi-server@<server>.<name>` for one, which takes precedence:

- `sourcemod-databases`: SourceMod's `databases.cfg`, the databases of
  SourceMod and SourceBans++
- `rcon-password`: the RCON password, without which each start makes a new
  random one
- `server-password`: the password to join, if the server has one
- `secret-cvars`: more secret settings, as lines of a config, e.g. the webhooks
  of SourceBans++'s Discord forward (`sbpp_discord_banhook "…"`)

```bash
systemd-creds encrypt --with-key=tpm2 --name=nwi-server.sourcemod-databases \
  databases.cfg /etc/credstore.encrypted/nwi-server.sourcemod-databases
```

`prepare_server.sh` puts them into the server's folder, readable by the server
only; the passwords go into a config, not the command line, which every user
could see. Each server's RCON password is in `/run/nwi-server/rcon/<server>`,
which the members of the group `nwi-rcon` can read. `nwi-rcon` (`tools/rcon.py`)
uses it:

```bash
nwi-rcon --server coop-commando status
nwi-rcon --ssh admin@example.org --server coop-commando sm plugins list
```

With `--ssh`, `nwi-rcon` runs on the server's machine, and the password never
leaves it. RCON is TCP on the game's port, while the game itself is UDP, so a
firewall that only lets UDP in keeps RCON to the machine.

### Running in a container

`deploy/container/Containerfile` builds an image of a server: SourceMod,
Metamod:Source and the plugins from their packages, this repository and its
compiled plugins. The game and the workshop items aren't part
of it, as they may not be passed on: they're in a state folder on the host,
which the image's updater fills with SteamCMD, like `nwi-update.service` for
the systemd units, and which the servers mount. The packages come from a local
pacman repository, like the one of aurutils, verified with its signing key: the
build context `repo` is its folder, `REPO_NAME` its name. With Podman, from the
repository's root, for aurutils' `aur` repository in `/var/lib/aurutils-repo`:

```bash
gpg --homedir /etc/pacman.d/gnupg --export -a <key> >repo-key.asc
podman build --format docker --build-context repo=/var/lib/aurutils-repo \
  --build-arg REPO_NAME=aur --secret id=repo-key,src=repo-key.asc \
  -f deploy/container/Containerfile -t nwi-server .
```

`deploy/container/test-instance.sh build` does the same with the repository
aurutils uses. The image's commands (`deploy/container/entrypoint.sh`) are the
server, `update [--stage]` and `check`: the updater and the check of
`tools/update_layers.sh` and `tools/check_updates.py` on the state folder,
mounted at `/srv/state`, for the servers whose environment files are mounted at
`/etc/nwi-server`.

`deploy/quadlet` has the units for rootless Podman, the containers'
counterparts of `deploy/systemd`, with the state folder
`~/.local/state/nwi-server` and the settings in `~/.config/nwi-server`:

- `nwi-update.container` and `nwi-stage.container` update the state folder in
  place or stage the update in a reflinked copy, as their systemd counterparts.
- `nwi-server@<server>.container` runs a server: its settings in
  `~/.config/nwi-server/<server>.env`, as for `nwi-server@.service`, its secrets
  in `~/.config/nwi-server/secrets` (which may be empty), on the host's
  network. Its game's install and workshop items are mounted with an overlay of
  the container's own (`:O`), its mods read-only, through the links the updater
  keeps in `~/.local/state/nwi-server/servers/<server>`, as a unit can't pick
  the folders by the server's game. It's ready once the image's
  health check, A2S like the systemd units' watchdog, passes, and restarted
  when the server stops answering. What it keeps goes into volumes.
- `nwi-build.service` pulls a clone of this repository and builds the image
  anew; `nwi-restart.service` builds, stages, stops the servers, puts the
  update in place and starts them again, with the new image, every day with
  `nwi-restart.timer`; `nwi-update-check.timer` checks for updates every three
  hours, as for the systemd units.

```bash
cp deploy/quadlet/*.container ~/.config/containers/systemd/
cp deploy/quadlet/*.service deploy/quadlet/*.timer deploy/quadlet/*.target \
  ~/.config/systemd/user/
systemctl --user daemon-reload
# The server's settings in ~/.config/nwi-server/coop-commando.env
systemctl --user start nwi-update.service
systemctl --user enable --now nwi-server@coop-commando.service nwi-servers.target
systemctl --user enable --now nwi-restart.timer nwi-update-check.timer
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
reaches the live servers. `TEST_ADMIN` makes SteamIDs root admin, separated by
spaces, each in any of Steam's forms (`STEAM_0:0:123`, `STEAM_1:0:123`,
`[U:1:246]` or the SteamID64 `76561197960265974`). Your settings, like your own
SteamID, can stay in `~/.config/nwi-server-kit/test-instance.env`, one `VAR=value` a
line, so you don't type them each time; variables of the environment take
precedence:

```bash
mkdir -p ~/.config/nwi-server-kit
echo 'TEST_ADMIN=[U:1:246]' >>~/.config/nwi-server-kit/test-instance.env
deploy/container/test-instance.sh build
# The games and the workshop items of all configs into the state folder: about
# 20 GB for Day of Infamy at first, and 10 GB for Insurgency's test server;
# with configs, e.g. update coop-commando, only theirs
deploy/container/test-instance.sh update
deploy/container/test-instance.sh up coop-commando
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
uses them. `tools/rcon.py` is the RCON client (`nwi-rcon` when installed), with
the password in `RCON_PASSWORD`.

The systemd units can be tested on this machine as well, set up as in [Running
with systemd](#running-with-systemd), with only the test instance's database:
`up --db-only` starts it at `127.0.0.1:3306` (`TEST_DB_PORT` for another port)
and prints the commands that copy the server's environment file to
`/etc/nwi-server` and its database's credential to `/etc/credstore`, unencrypted
for the test. `down` removes the database again.

The admins get into the database and, through the server's environment file,
into SourceMod's `admins_simple.ini` (`tools/prepare_server.sh`). So
`TEST_ADMIN` in the environment file of any server, e.g.
`/etc/nwi-server/<server>.env`, makes test admins on a server without the
database, too. The live servers' environment files don't have it.

```bash
deploy/container/test-instance.sh up --db-only coop-commando
```

### Testing with sanitisers

Test builds of SourceMod, Metamod:Source and their extensions with Clang's
sanitisers find undefined behaviour and memory errors in them:
UndefinedBehaviorSanitizer (`undefined`), AddressSanitizer (`address`) or both
(`address,undefined`). The AUR packages build them on request, into a repository
of their own that the build keeps and names at the end, not into the local one:

```bash
./aur-packages build --sanitize=undefined metamod-source sourcemod \
  sourcemod-smjansson sourcemod-steamworks
```

`deploy/container/sanitiser` builds an image on top of the usual one with these
packages and the sanitisers' 32-bit runtime (`compiler-rt`), from that
repository's folder. With `SANITISER` set to the sanitisers of the build,
`test-instance.sh up` starts the server from that image, and
`tools/start_server.sh` preloads the runtime into srcds. The reports go to the
server's output, with stack traces:

```bash
podman build --format docker --build-context packages=/tmp/aur-build.XXXXXX \
  -f deploy/container/sanitiser/Containerfile \
  -t localhost/nwi-server-sanitiser .
SANITISER=undefined deploy/container/test-instance.sh up soak-bots
podman logs nwi-test-server 2>&1 |
  grep -E 'runtime error:|ERROR: AddressSanitizer'
```

The `soak-bots` server is for long runs without players: 20 bots a team on the
frontline maps at 128 tick, the maps changing as in a game. Meanwhile
`tools/soak_watch.py` logs the map, the bots, srcds' memory and the number of
reports every five minutes as TSV, and adds the bots again when a map change
lost them. AddressSanitizer takes a lot more memory and time than
UndefinedBehaviorSanitizer, so a long run with it is best left overnight:

```bash
env=~/.local/state/nwi-test/server.env
RCON_PASSWORD=$(sed -n 's/^RCON_PASSWORD=//p' "$env") \
  tools/soak_watch.py --container nwi-test-server --hours 8 soak.tsv
```

## Server notes

### Engine hunk overflow

The configuration sets `r_hunkalloclightmaps 0`, which prevents crashes on large
maps like `ardennes`. Community maps of that size contain a lot of lightmap data
and otherwise crash the server with an [Engine Hunk
Overflow](https://developer.valvesoftware.com/wiki/Engine_Hunk_Overflow). In
some cases, like when such a map is the server's startup map, the setting also
has to be passed on the server's command line, as `nwi-server@.service` does.

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
library's patch stops it, so `mods/doi/playlists.toml` says which of them the
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
`nwi-server@.service` and `deploy/container/entrypoint.sh`), where Day of
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

It needs a pre-callback of DHooks (through `nwi_gamedata`), which the
`sourcemod` package's builds before 1.12.0.7260-4 didn't call: a signed
overflow in AMTL's hashes, which LTO miscompiled
([alliedmodders/amtl#142](https://github.com/alliedmodders/amtl/pull/142)).

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
`mods/<game>/<mod>.toml` says which blocks of which maps to copy and how to adjust the
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
and those it can't, the latter with an exit status of 1. `nwi-update.service`
runs it after each update, so its log shows broken scripts of new workshop
maps.

```bash
tools/make_mods.py --game GAME --workshop WORKSHOP OUTPUT mods
tools/make_mods.py --game GAME --workshop WORKSHOP --check
```

`GAME` is the game's install, with `doi` in it, `WORKSHOP` SteamCMD's folder of
the workshop items, and `OUTPUT`, which is replaced, gets the `custom` folder
for the server's `doi` folder.

### Playlists

The `nwi_playlist_unlock` plugin lifts the playlists' restrictions, in Day of
Infamy and Insurgency: the server takes each playlist from a replacement in
`cfg/doi-config/playlists/<playlist>.playlist` where there is one, which
`tools/make_mods.py` makes by the `[[replace]]` tables of `mods/<game>/*.toml`. Ours
(`mods/doi/playlists.toml`) drop `allowed_maps`, the forced settings and the
required slots from every playlist, in its own keys and its rulesets: any map
and game mode may run, the playlists force no settings (their configs, also
from `tools/make_mods.py`, take over those we keep), and any number of slots is
fine. In Day of Infamy, the server also registers for the game's stats with
workshop content.

The replacements are loaded in memory, through `nwi_gamedata`
(`NWI_ReplacePlaylists` of `nwi_gamedata.inc`): the game's files and their
checksums stay as they are. The game reads its playlists before SourceMod is
there, so `nwi_gamedata` has it read them again once the plugins are loaded,
still before the first map's settings. A playlist without a replacement stays
as the game has it.

It replaces the patch of the server library that earlier versions of this
repository applied in memory, with a library preloaded into srcds. Tested
against that patch on a local `coop-commando` server: the playlist's limits,
forced settings and maps were the same with either, and without both, the game
enforced them. Not tested yet: the registration for the stats. Linux only so
far, as the gamedata has no signatures for Windows yet.

After each game update, `tools/update_game.sh --check-gamedata` checks that the
game still has the functions of the plugins' gamedata, by their symbols
(`tools/check_gamedata.py`), so an update that moved them fails there rather
than leaving the servers with the playlists' restrictions.

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
`nwi_physics_timestep`, `nwi_playlist_unlock` and `nwi_server_visibility`, are available under the MIT licence or the GPL-3.0-only with SourceMod's linking
exception, at your choice, so they can be used in other SourceMod projects
either way.

AFK Manager, vendored in `game/addons/sourcemod` together with its include,
translations and configuration, is licensed under the GPL-3.0-only with
SourceMod's linking exception, like its earlier versions. The mods' map scripts
aren't part of this repository: `tools/make_mods.py` makes them from the game's
own when a server is set up, so they remain New World Interactive's.

`REUSE.toml`, the file headers and the `LICENSES` folder say this in the
[REUSE](https://reuse.software/) format.
