# Day of Infamy Open Configuration

[![Checks](https://github.com/ChrisTX/doi-config/actions/workflows/check.yml/badge.svg)](https://github.com/ChrisTX/doi-config/actions/workflows/check.yml)

The configuration of the Kim Jong Un Day of Infamy servers: the game and
SourceMod settings of each game mode, the MOTDs, the scripts that install and
update a server, and the systemd units that run and monitor it.

For players, [docs/Clients.md](docs/Clients.md) covers the client settings the
servers need.

## Layout

The repository is laid out like the server's `doi` folder, so its folders can be
placed on top of a server as they are:

- `game` holds what all servers share: the configs in `cfg/doi-config`, the
  configs of the game modes (`cfg/server_<gamemode>.cfg`), the mods in `custom`
  and the SourceMod plugins, their translations and configs in
  `addons/sourcemod`.
- `servers/<config>` holds what one server adds: its `cfg/server.cfg` and its
  `motd.txt`.
- `tools` has the scripts that set up and monitor a server, `deploy` the systemd
  units, `patches` the patch of the server library.

## Usage

`game` belongs into the server's `doi` folder, with `cfg/doi-config` at
`doi/cfg/doi-config`. Source configs can't resolve paths dynamically, so the
configuration only works at that location. `prepare_server.sh` sets this up.

Without one of the servers in `servers`, create a `server.cfg` that sets the
server's name and runs one of the `init-<config>.cfg` files. For the Coop
Commando configuration, for example:

```text
hostname "MY-SERVER-NAME"
rcon_password "MY-PASSWORD"

exec doi-config/init-coop-commando.cfg
```

The workshop ID file of the configuration in `game/cfg/doi-config` has to be
passed to SRCDS on the command line with `sv_workshop_list_file`, as it can't be
changed once the server is running.

### `prepare_server.sh`

`tools/prepare_server.sh` sets up or updates a server before it starts:

```bash
tools/prepare_server.sh <server folder> [<config>]
```

It installs or updates the game with SteamCMD, clones or pulls this repository
into the server folder as `doi-config`, and installs the latest Metamod:Source
and SourceMod together with the plugins the configuration uses (SourceBans++,
Advertisements and their dependencies). It then links the files of `game` into
the server's `doi` folder and compiles the plugins. AFK Manager, which is no
longer maintained upstream, is kept in `game/addons/sourcemod`. A server set up
with the earlier layout, where the repository was cloned into `doi/cfg`, is
moved to the new one.

`<config>` names one of the servers in the `servers` folder, e.g.
`coop-commando`. Its files are copied into the server's `doi` folder, which
makes its `server.cfg` and MOTD the server's. The `SERVER_CONFIG_NAME`
environment variable can name the server instead. Without either, the server
needs a `server.cfg` of its own, as described above.

If the `RCON_PASSWORD` environment variable is set, the script writes it to
`rcon.cfg` and runs that from `server.cfg`.

### Running with systemd

The `deploy/systemd` folder has user units for running the servers, one
instance per config:

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
  `deploy/systemd/check_srcds_monitor@coop-commando.env` for an example.

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
active game mode needs its `server_<gamemode>.cfg` from the `game/cfg`
folder, which `prepare_server.sh` links into the server.

### Server patch

`patches/server_srv.xxd` patches the game's server library,
`doi/bin/server_srv.so`, so it enables stats with custom content and lifts the
playlist restrictions. It changes a few bytes, which `prepare_server.sh` writes
with `xxd -r` (from the `vim` or `tinyxxd` package). The script checks the
library's SHA-256 before and after, so it stops if a game update changes the
library.

### GeoIP2 databases

SourceMod and the SourceBans++ web panel both use MaxMind's GeoIP2 databases.
Both ship MMDB files, but those haven't been updated in years. Instead, install
and configure [geoipupdate](https://github.com/maxmind/geoipupdate), which needs
a free MaxMind account and keeps current databases in `/var/lib/GeoIP`.
`prepare_server.sh` links the databases from there when they exist, and the web
panel of the [sourcebans-pp](https://aur.archlinux.org/packages/sourcebans-pp)
package links its database from there too.

## Licence

The configuration, scripts and units are licensed under the [MIT](LICENSE)
licence. The SourceMod plugins written for these servers, `doi_cvar_unlocker`
and `doi_difficulty_scaler`, are available under the MIT licence or the
GPL-3.0-only with SourceMod's linking exception, at your choice, so they can be
used in other SourceMod projects either way.

AFK Manager, vendored in `game/addons/sourcemod` together with its include,
translations and configuration, is licensed under the GPL-3.0-only with
SourceMod's linking exception, like its earlier versions. The map files in
`game/custom` come from the game and remain New World Interactive's.

`REUSE.toml`, the file headers and the `LICENSES` folder say this in the
[REUSE](https://reuse.software/) format.
