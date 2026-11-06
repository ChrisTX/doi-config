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
  units and the servers' user, `patches` the patch of the server library.

## Usage

`game` belongs into the server's `doi` folder, with `cfg/doi-config` at
`doi/cfg/doi-config`. Source configs can't resolve paths dynamically, so the
configuration only works at that location. The systemd units below set this
up.

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

### Running with systemd

The servers run as system services of the `doi` user, one instance per server,
which share one install of the game. Each server is put together with overlayfs
from read-only layers, top first:

- `/etc/doi-server/secrets`, laid out like the `doi` folder, e.g. the database
  credentials of SourceMod and SourceBans++ in
  `addons/sourcemod/configs/databases.cfg`
- the server's folder in `servers`, if there's one
- this repository's plugins, compiled by `doi-update.service`
- `game` of this repository
- `/usr/lib/sourcemod` and `/usr/lib/metamod`: SourceMod, Metamod:Source and
  the plugins from their packages (`sourcemod`, `metamod-source`,
  `sourcemod-sourcebans-pp`, `sourcemod-sourcebans-pp-discord-forward`,
  `sourcemod-advertisements`, `sourcemod-multicolors`, `sourcemod-smjansson`,
  `sourcemod-steamworks`)
- the workshop items of all servers
- the game

Their writable layer starts empty on every start, so changes to the layers
always show. What the server writes and keeps, like its logs, is bind-mounted
from the server's state folder instead (see `tools/mount_server.sh`). The mounts
only exist in the service's mount namespace and disappear when it stops.

The units are in `deploy/systemd`, the `doi` user in `deploy/sysusers.d`:

- `doi-update.service` pulls this repository in
  `/var/lib/doi-server/doi-config` and runs `tools/update_game.sh`, which
  installs or updates the game in `/var/lib/doi-server/game` with SteamCMD,
  patches it (see [Server patch](#server-patch)) and compiles this repository's
  plugins. It runs before the servers start. It also downloads the workshop
  items of all `workshop-ids-*.txt` files into `/var/lib/doi-server/workshop`,
  once for all servers. SteamCMD gets their current versions, which the game
  itself never does once it has an item, and items no list names any more are
  removed.
- `doi-server@<server>.service` mounts the layers (`tools/mount_server.sh`),
  configures the server (`tools/prepare_server.sh`: the plugins SourceBans++
  needs, its website from `SOURCEBANS_WEBSITE`, `RCON_PASSWORD` in `rcon.cfg`)
  and runs it. SourceBans++ finds the server in the panel by its address and
  port: the address the server reports, or `SOURCEBANS_SERVER_IP` if that's a
  private one, as in a container. `SOURCEBANS_SERVER_ID` sets the panel's ID of
  the server instead. Its
  ports, startup map, workshop ID file, theater and password come from
  `/etc/doi-server/<server>.env` (`SERVER_PORT`, `TV_PORT`, `CLIENT_PORT`,
  `STARTUP_MAP`, `WORKSHOP_IDS_FILE`, `THEATER`, `SERVER_PASSWORD`). The
  server uses the folder of the same name in `servers`, or the one
  `SERVER_CONFIG_NAME` names; without one, the secrets layer needs a
  `cfg/server.cfg` as described above.
- `tools/srcds_watchdog.py` runs the server and queries it with A2S. The
  service is ready once the server first answers, and systemd's watchdog
  restarts it when it hasn't answered for 90 seconds, at most 6 times an hour.
  The hung server dumps its core first.
- `doi-servers.target` starts the enabled servers.
- `doi-restart.timer` stops the servers every day at 06:00, runs
  `doi-update.service` and starts them again, as the game install mustn't
  change while servers use it.

Setting up a server, as root, with the packages above and `steamcmd`, `git`,
`python-a2s` and `vim` (for `xxd`) installed:

```bash
cp deploy/sysusers.d/doi-server.conf /etc/sysusers.d/
cp deploy/systemd/* /etc/systemd/system/
systemd-sysusers
install -d -o doi -g doi -m 750 /var/lib/doi-server
sudo -u doi git clone https://github.com/ChrisTX/doi-config.git /var/lib/doi-server/doi-config
# The server's settings in /etc/doi-server/coop-commando.env, its secrets in /etc/doi-server/secrets
systemctl enable --now doi-server@coop-commando.service doi-servers.target doi-restart.timer
```

### Running in a container

`deploy/container/Containerfile` builds an image of a server, with the same
layers as the systemd units: the game, the workshop items of all servers,
SourceMod, Metamod:Source and the plugins from their packages, and this
repository. Containers of the image share its layers, and a container's
writable layer starts anew whenever the container is created. The packages come
from a pacman repository, like the one of aurutils, verified with its signing
key. With Podman, from the repository's root:

```bash
gpg --homedir /etc/pacman.d/gnupg --export -a <key> >aur-key.asc
podman build --build-context aur=/var/lib/aurutils-repo \
  --secret id=aur-key,src=aur-key.asc \
  -f deploy/container/Containerfile -t doi-server .
```

The layer cache keeps the game and the workshop items until the build
arguments `GAME_UPDATE` and `WORKSHOP_UPDATE` change, e.g.
`--build-arg WORKSHOP_UPDATE=$(date +%F)` to update the workshop items.

A container takes the variables of the systemd units' environment file, with
`SOURCEBANS_SERVER_IP` set to the server's public address (the container only
sees its private one), the server's config in `servers` as `SERVER_NAME` and
the secrets, laid out like the
`doi` folder, in `/run/secrets/doi-server`. What the server keeps between
containers goes into volumes. The GeoIP2 databases come from the host's
`/var/lib/GeoIP`, kept current by geoipupdate there (see
[GeoIP2 databases](#geoip2-databases)): it needs the MaxMind account's
credentials, which don't belong into the container.

```bash
podman run -d --name doi-coop-commando \
  --env-file coop-commando.env -e SERVER_NAME=coop-commando \
  -p 27015:27015/udp -p 27015:27015/tcp -p 27020:27020/udp \
  -v /etc/doi-server/secrets:/run/secrets/doi-server:ro \
  -v /var/lib/GeoIP:/var/lib/GeoIP:ro \
  -v doi-coop-commando-dumps:/srv/doi/dumps \
  -v doi-coop-commando-logs:/srv/doi/doi/logs \
  -v doi-coop-commando-sm-logs:/srv/doi/doi/addons/sourcemod/logs \
  -v doi-coop-commando-sm-data:/srv/doi/doi/addons/sourcemod/data \
  --health-cmd \
  'python3 /opt/doi-config/tools/srcds_watchdog.py --check --port 27015' \
  --health-start-period 10m --health-interval 30s --health-retries 3 \
  --health-on-failure restart \
  doi-server
```

The health check queries the server with A2S like the systemd units'
watchdog, and restarts the container when it stops answering.

### Testing locally

`deploy/container/test-instance.sh` runs a server of one of the configs in a
Podman pod, together with a new MariaDB. The database has the tables of
SourceBans++ and SourceMod and the test server registered, the passwords are
generated, and without its config the Discord forward stays silent, so nothing
reaches the live servers. `TEST_ADMIN` makes a SteamID root admin:

```bash
deploy/container/test-instance.sh build
TEST_ADMIN=STEAM_0:0:123 deploy/container/test-instance.sh up coop-commando
deploy/container/test-instance.sh rcon sm plugins list
deploy/container/test-instance.sh down
```

The server is then at this machine's address, port 27015, which `up` prints.
Not at `127.0.0.1`: rootless Podman passes connections from there on from the
pod's own address, and the server drops them. `build` and `up` take the packages
and
SourceBans++'s tables from the pacman repository in `AUR_REPO`
(`/var/lib/aurutils-repo` by default). `tools/rcon.py` is the RCON client, with
the password in `RCON_PASSWORD`.

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
playlist restrictions. It changes a few bytes, which `update_game.sh` writes
with `xxd -r` (from the `vim` or `tinyxxd` package). The script checks the
library's SHA-256 before and after, so it stops if a game update changes the
library.

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
