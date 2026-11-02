# Day of Infamy Open Configuration

[![Checks](https://github.com/ChrisTX/doi-config/actions/workflows/check.yml/badge.svg)](https://github.com/ChrisTX/doi-config/actions/workflows/check.yml)

The configuration of the Kim Jong Un Day of Infamy servers: the game and
SourceMod settings of each game mode, the MOTDs, the scripts that install and
update a server, and the systemd units that run and monitor it.

For players, [docs/Clients.md](docs/Clients.md) covers the client settings the
servers need.

## Usage

Clone this repository into the `doi/cfg` folder of the server, as
`doi/cfg/doi-config`. Source configs can't resolve paths dynamically, so the
configuration only works at that location.

Then create a `server.cfg` that sets the server's name and runs one of the
`init-<config>.cfg` files. For the Coop Commando configuration, for example:

```text
hostname "MY-SERVER-NAME"
rcon_password "MY-PASSWORD"

exec doi-config/init-coop-commando.cfg
```

The workshop ID file of the configuration in the `configs` folder has to be
passed to SRCDS on the command line with `sv_workshop_list_file`, as it can't be
changed once the server is running.

### `prepare_server.sh`

`scripts/prepare_server.sh` sets up or updates a server before it starts:

```bash
scripts/prepare_server.sh <server folder> [<config>]
```

It installs or updates the game with SteamCMD, clones or pulls this repository
into `doi/cfg/doi-config`, and installs the latest Metamod:Source and SourceMod
together with the plugins the configuration uses (SourceBans++, Advertisements
and their dependencies). It then links the mods, game mode configs and plugins
of this repository into the server and compiles the plugins. AFK Manager, which
is no longer maintained upstream, is kept in this repository's `sourcemod`
folder.

`<config>` names one of the server configs in the `texts` folder, e.g.
`coop-commando` for `texts/server_coop-commando.cfg`. That config becomes the
server's `server.cfg`, and the matching `texts/motd_<config>.txt` its MOTD. The
`SERVER_CONFIG_NAME` environment variable can name the config instead. Without
either, the server needs a `server.cfg` of its own, as described above.

If the `RCON_PASSWORD` environment variable is set, the script writes it to
`rcon.cfg` and runs that from `server.cfg`.

### Running with systemd

The `systemd` folder has user units for running the servers, one instance per
config:

- `doi-server@<config>.service` runs the server in
  `~/servers/dayofinfamy-<config>`, after running `prepare_server.sh` from this
  repository in `~/doi-config`. Its ports, startup map, workshop ID file, theater
  and password come from `~/.config/systemd/user/doi-server@<config>.env`
  (`SERVER_PORT`, `TV_PORT`, `CLIENT_PORT`, `STARTUP_MAP`, `WORKSHOP_IDS_FILE`,
  `THEATER`, `SERVER_PASSWORD`). The contents of `~/doi-secrets`, like the
  database credentials of SourceMod and SourceBans++, are copied into the
  server's `doi` folder before it starts.
- `doi-server-restart@<config>.timer` restarts the server every day at 06:00,
  which also updates it.
- `check_srcds_monitor@<config>.service` queries the server every 30 seconds and
  restarts it once it stops answering. Its settings come from
  `~/.config/systemd/user/check_srcds_monitor@<config>.env`, see
  `monitor/check_srcds_monitor@coop-commando.env` for an example.

## Server notes

### Engine hunk overflow

The configuration sets `r_hunkalloclightmaps 0`, which prevents crashes on large
maps like `ardennes`. Community maps of that size contain a lot of lightmap data
and otherwise crash the server with an [Engine Hunk
Overflow](https://developer.valvesoftware.com/wiki/Engine_Hunk_Overflow). In
some cases, like when such a map is the server's startup map, the setting also
has to be passed on the server's command line, as `doi-server@.service` does.

### Libraries (Linux)

The game server needs the following 32-bit libraries on Linux:

```text
glibc
libgcc
libstdc++
SDL2
zlib
```

SDL2 can be replaced with `sdl2-compat`, which implements SDL2 on top of SDL3.
`prepare_server.sh` removes the outdated copies of libgcc, libstdc++, libogg and
libvorbis that come with the game, so the system's libraries are used instead.

The Steam client library can load these libraries as well, but only in the game
client, not in a server:

```text
SDL3
libX11
PulseAudio (libpulse)
```

The game server binaries also reference these libraries:

```text
OpenAL
util-linux
freetype2
fontconfig
```

Only the client code paths in `engine.so` load them, so if a server asks for any
of them, something is wrong. This happened when an update removed BattlEye from
the game [in
2025](https://steamdb.info/depot/462311/history/?changeid=M:9106077001589815964),
until [a second
update](https://steamdb.info/depot/462311/history/?changeid=M:1007577009454669389)
fixed it the next day.

### Tickrate

Don't change the tickrate of Day of Infamy. The game can run at 128 tick, but
never supported it properly: throwables like grenades start to bounce
excessively, and the game's physics break down in general, even if everything
else seems fine.

### Difficulty scaler

The `doi_difficulty_scaler` SourceMod plugin adjusts the number of bots to the
number of players, independently of the map's scripting. For this to work, the
active game mode needs its `server_<gamemode>.cfg` from the `configs/gamemodes`
folder, which `prepare_server.sh` links into the server.

### Server patch

`server-patch/server_srv.so` is a modified game server library that enables
stats with custom content and lifts the playlist restrictions.
`prepare_server.sh` copies it into `doi/bin`.

### GeoIP2 databases

SourceMod and the SourceBans++ web panel both use MaxMind's GeoIP2 databases.
Both ship MMDB files, but those haven't been updated in years. Instead, install
and configure [geoipupdate](https://github.com/maxmind/geoipupdate), which needs
a free MaxMind account and keeps current databases in `/var/lib/GeoIP`.
`prepare_server.sh` and `deploy_sourcebans.sh` link the databases from there
when they exist.
