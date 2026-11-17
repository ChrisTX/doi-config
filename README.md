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
- `src/nwi_server_kit` is the Python package of the servers' tools, with the
  command `nwi-server` (`nwi-server` without arguments lists its commands),
  `tools` the other scripts that set up and monitor a server, `deploy` the
  systemd units, the container and the package.

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
configs_after = ["doi-config/basic_coop.cfg"]
```

With `ruleset`, a server runs one of its playlist's rulesets, e.g. a campaign
of Coop Commando, `ruleset = "american_campaign"`, which keeps its maps and
teams (see [Playlists](#playlists)).

With `game = "insurgency"`, a server runs Insurgency instead of Day of Infamy,
like the test server `servers/ins-test`. The tools only keep the apps of the
games' dedicated servers (`nwi-server games`) and find the rest: the depots,
the game's folder (`doi` or `insurgency`, the one with `gameinfo.txt`) and the
workshop's app of the items. The configs of `game/cfg/doi-config` are Day of
Infamy's.

At each start, `nwi-server prepare` makes the server's `cfg/server.cfg` of
it with `nwi-server server-config`, which describes the keys: the names of the
server and SourceTV, and the configs it runs (see [Configs](#configs)). It also
copies the server's list of workshop items to `subscribed_file_ids.txt` in the
`doi` folder, the list the game downloads and mounts by default. The launcher,
`nwi-server start`, takes the server's slots, whether it's a LAN server,
the first map, the theater and its own options of the command line from it, and
starts it with the workshop if it has a list. Its passwords and other secrets
are credentials (see [Secrets](#secrets)).

A server without a `server.toml`, of no config of `servers`, needs its own
`cfg/server.cfg`.

### Running with systemd

The servers run as system services, one instance per server, which share one
install of each game. The games, and the workshop items, are those of the
servers: each `/etc/nwi-server/<server>.env` is a server, its game its config's
or `GAME` of its environment file without one (`nwi-server games`). Each server
and the updater run as users of their own (`DynamicUser=`): a server can't
change another's files, nor the layers they share, which the updater makes. Each
server is put together with overlayfs from read-only layers, top first:

- the server's folder in `servers`, if there's one
- this repository's plugins, compiled by `nwi-update.service`
- the mods of `mods/<game>` and the playlists' configs, made by
  `nwi-update.service`
- `game` of this repository
- SourceMod, Metamod:Source and the plugins from their packages, copies of
  `/usr/lib/sourcemod` and `/usr/lib/metamod` made by `nwi-update.service`
  when the packages changed, so that their update reaches a server when it
  restarts, on trial, not while it runs (`sourcemod`, `metamod-source`,
  `sourcemod-sourcebans-pp`, `sourcemod-sourcebans-pp-discord-forward`,
  `sourcemod-advertisements`, `sourcemod-multicolors`, `sourcemod-smjansson`,
  `sourcemod-steamworks`)
- the record of the server's workshop items, which the game reads, the items,
  each a layer of its own, and the game's depots

The layers are versions, each a folder that doesn't change once it's made, of
which a server mounts the newest when it starts (`nwi-server mount`). Their
writable layer starts empty whenever they're mounted, so new versions always
show. What the server writes and keeps, like its logs, is
bind-mounted from the server's state folder, `/var/lib/nwi-server/servers/<server>`,
instead. The layers are mounted while the server runs, in
`/run/nwi-server/<server>`, mapped to the server's user (see
`src/nwi_server_kit/mount.py`).

The units are in `deploy/systemd`, the group `nwi-rcon` in `deploy/sysusers.d`.
They run the tools installed with them (`make install`, or the package of
`deploy/arch/PKGBUILD`), the command `nwi-server`, which reads the configs
of the servers' config sources (see [Config sources](#config-sources)).
SourceMod and Metamod:Source are copied from `SOURCEMOD_DIR` and `METAMOD_DIR`,
`/usr/lib/sourcemod` and `/usr/lib/metamod` by default.

- `nwi-update.service` updates the layers (`nwi-server update`), in its state
  `/var/lib/nwi-server/layers`, as versions of what it downloads and builds
  (see `src/nwi_server_kit/update.py`): the configs of each config source
  (`config-<source>.v`) and their compiled plugins (`plugins-<source>.v`), each
  depot of the games of the servers (`depot-<depot>.v`), which the games share,
  like the Steam client library's, and of each game its servers' workshop items
  (`<game>/item-<item>.v`) and the mods of each source (`<game>/mods-<source>.v`,
  see [Mods](#mods)). It downloads with DepotDownloader into `downloads`, the
  workshop items' current versions, which the game itself never gets once it
  has an item, and checks each game against each source's gamedata (see
  [Playlists](#playlists)). A version is a reflinked copy (btrfs, XFS), which
  shares its files' data with the download and the other versions, so it takes
  only the space of what differs, and a server never sees it change. It keeps
  the newest three versions of each layer (`NWI_KEEP_VERSIONS`) and those a
  server uses, and removes the layers no server needs any more, e.g. of an item
  no list names. It runs before the servers start, and while they run: they get
  the new versions when they start again. The downloads of earlier layouts,
  e.g. an install of SteamCMD's, are kept, and checked file by file, so only
  what differs is downloaded.
- `nwi-server@<server>.service` mounts the layers' versions at every start
  (`nwi-server mount`), of each the newest that's good or still on trial,
  configures the server (`nwi-server prepare`: its secrets, the plugins SourceBans++ needs, its website from
  `SOURCEBANS_WEBSITE`) and runs it. SourceBans++ finds the server in the panel
  by its address and port: the address the server reports, or
  `SOURCEBANS_SERVER_IP` if that's a private one, as in a container.
  `SOURCEBANS_SERVER_ID` sets the panel's ID of the server instead. Its ports
  come from `/etc/nwi-server/<server>.env` (`SERVER_PORT`, `TV_PORT`,
  `CLIENT_PORT`), which has no secrets, the rest of its settings from its
  `server.toml`. The server uses the folder of the same name in `servers`, or
  the one `SERVER_CONFIG_NAME` names; without one, `GAME` says its game, `doi`
  by default.
- `nwi-server start` runs the server and queries it with A2S. The
  service is ready once the server first answers, and systemd's watchdog
  restarts it when it hasn't answered for 90 seconds, at most 6 times an hour.
  The hung server has 30 seconds to dump its core first.
- `nwi-servers.target` starts the enabled servers, `nwi-bless.timer` and
  `nwi-notify.path`.
- A new version of a layer is on trial, with three tries. A failure of a server
  costs a try of the versions it's blamed on, by where it happened: before the
  server answered, all of them; on a map of a new workshop item, that item,
  unless the server failed on other maps too, which blames the depots, configs,
  plugins and mods instead; elsewhere, those. A version without tries left is
  passed over for the one before. Versions prove themselves: a workshop item
  once one of its maps was played to its end with at least 4 human players, the
  rest after 2 hours with at least 4 human players (`NWI_BLESS_PLAYERS`,
  `NWI_BLESS_MINUTES`). `nwi-bless.timer` blesses them every 5 minutes.
  `nwi-server health` shows the versions on trial; `nwi-server health retry
  VERSION` gives a version its tries again, `nwi-server health approve VERSION`
  blesses it by hand.
- The admins are notified of versions that used up their tries and of servers
  that failed for good: by mail to root and the addresses of `NOTIFY_MAIL` in
  `/etc/nwi-server/notify.env`, and to Discord with the webhook of the
  credential `nwi-server.discord-webhook`, if there is one.
- `nwi-restart.timer` updates and restarts the servers every day at 06:00: the
  update while they run, so that they're only down for the restart, which gives
  them the new versions.
- `nwi-update-check.timer` checks the games and the workshop items for updates
  every three hours (`nwi-server check-updates`), and on an update restarts the
  servers like `nwi-restart.timer`. The game's depots are compared, not its
  build, as the Steam client library's depot changes on its own, and the
  workshop items must be the versions the players download: theater files that
  differ break the game.

Setting up a server: the package of the tools and units, built from this
checkout's commits, which also installs `steamdepotdownloader`, `git`, `python-a2s`,
`python-srctools`, SourceMod and Metamod:Source, and the plugin packages above:

```bash
cd deploy/arch && makepkg -si && cd -
sudo pacman -S --needed --asdeps sourcemod-sourcebans-pp \
  sourcemod-sourcebans-pp-discord-forward sourcemod-advertisements \
  sourcemod-multicolors
```

Then, as root, with the server's settings in `/etc/nwi-server/coop-commando.env`
and its secrets as credentials (see [Secrets](#secrets)), and the default
config source, which the first update clones:

```bash
printf 'URL=%s\n' https://github.com/ChrisTX/doi-config.git |
  install -D -m 644 /dev/stdin /etc/nwi-server/configs/default.env
systemctl enable --now nwi-server@coop-commando.service nwi-servers.target
systemctl enable --now nwi-restart.timer nwi-update-check.timer
```

### Config sources

A server's configs, its `server.toml`, the configs of `game` and the mods,
come from a config source: a repository like this one, e.g. a community's, at a
branch or tag. `/etc/nwi-server/configs/<source>.env` names it, `URL=` the
repository and `REF=` the branch or tag (the repository's own branch, pulled,
without one); the updater keeps its clone in its state. A server takes the
source `CONFIG_SOURCE` of its environment file, `default` without one, so
servers of different communities can run on one machine, each with its own
configs, plugins and mods:

```ini
# /etc/nwi-server/configs/theirs.env
URL=https://example.org/theirs/server-configs.git
REF=live
# /etc/nwi-server/their-server.env
CONFIG_SOURCE=theirs
```

The workshop items stay one download per game for all sources, and each server
mounts the items of its own list.

### Workshop items

Players download a workshop item's newest version from the Workshop, and their
game parses it, so a broken or malicious update of an item on the servers' lists
reaches everyone who joins. So a config source approves the versions its servers
use, in `workshop/approved.toml` of its configs, by their manifests, and may name
keys (`workshop/keys/<name>.pem`) an item's versions may be signed with:

```toml
[items.3431236539]
manifests = ["7284409961546829163"]
keys = ["community"]
```

`nwi-update.service` makes a layer of a new version only if a source whose
servers list the item approves it: by its manifest, or because it's VPKs only,
each signed with one of the item's keys, which approves it by itself. Any other
version is held: the servers keep the version they have, and the admins are told
(see the notifications above). A server lists only the items whose version it
runs is the Workshop's newest, in its `subscribed_file_ids.txt`, and its mapcycle
leaves out the maps of the others, which players couldn't get; a startup map of
theirs becomes the mapcycle's first. That covers an item that fell back after
failures too. A source without `workshop/approved.toml` approves every version.

Every new version is scanned before that (`src/nwi_server_kit/scan.py`), as a
version that reaches the servers reaches the players' clients, which parse it,
e.g. of an author's account that was taken over. Its files, loose and in its
VPKs, have to be game content (maps, models, materials, sounds, scripts and the
like) in the folders the game reads it from: no configs, plugins or libraries,
which the server's search path would load as its own. And the formats the game
parses (maps, nav meshes, models, textures, sounds, particles) have to hold
together: every offset and size within the file, the dimensions within the
game's limits, the VPKs' entries matching their checksums. And ClamAV's
signatures, those its daemon `clamd` has (e.g. SecuriteInfo's too), find nothing
in any file, loose or in a VPK: each file is streamed to `clamd` over its socket,
so it needs no access to the item's folders. A file larger than `clamd` scans
(its `StreamMaxLength`) is noted, not held. Without `clamd` the scan fails, so
that nothing is served unscanned by mistake; `NWI_CLAMD=off` in the updater's
environment scans without ClamAV, and `NWI_CLAMD=<socket>` names another socket
than `clamd`'s own (`LocalSocket` of `/etc/clamav/clamd.conf`). The container
image has no `clamd` and scans without it, unless a container gets the host's
socket and `NWI_CLAMD`. A version with
findings is held for every source, approved or not, and the admins are told
what was found. A false alarm, after a review, is approved per version with
`nwi-server workshop approve --unscanned ITEM MANIFEST`. `nwi-server workshop
scan FOLDER` scans a folder by hand, e.g. a mod before its upload. It's a
defence in depth, not a proof: a file that's malformed in a way its headers
don't show passes.

The same scan protects a player's game client, with the package installed (and
`clamd`, see [ClamAV](#clamav)). `nwi-server workshop scan-client` scans the
workshop items Steam installed for Day of Infamy and Insurgency, in all of
Steam's libraries, each version once, and `--notify` shows a desktop
notification of an item with findings. The game client writes sound caches into
its items' folders, which this scan lets pass, unlike the servers'. The user
units run it whenever Steam installed or updated an item:

```bash
systemctl --user enable --now nwi-client-scan.path
```

They watch the records of Steam's default library
(`~/.local/share/Steam/steamapps/workshop/appworkshop_<app>.acf`); a game in
another library gets its record with `systemctl --user edit
nwi-client-scan.path`, see the unit. It warns, it can't block: Steam installed
the item already, so unsubscribe from it before you play. `nwi-server workshop
scan-item ITEM...` downloads items' current versions into a temporary folder
and scans them, without subscribing, e.g. mods popular with the players.

In a checkout of the configs, `nwi-server workshop freeze` approves the current
versions of all items of the servers' lists, and `nwi-server workshop approve
ITEM [MANIFEST]` one version, the current one without MANIFEST, after a review.
Authors sign their VPKs with `nwi-server workshop keygen NAME`, which makes the
private key `NAME.key` (keep it off the machine that uploads to the Workshop)
and the public key `NAME.pem` for the configs, and `nwi-server workshop sign
NAME.key MOD.vpk`; `nwi-server workshop verify` checks a VPK's signature.
`nwi-server workshop status` shows the held versions on a server.

Authors upload with `nwi-server workshop upload`, through the Steam client of
their machine, signed in as the item's owner or a contributor, and the
Steamworks SDK's library (the `steamworks-sdk` package's in `/opt`, or
`NWI_STEAM_API`; never where games would load it):

```bash
nwi-server workshop upload MOD.vpk --item ITEM --note "What changed"
nwi-server workshop upload MOD.vpk --game doi --title "Title" --preview preview.jpg
```

It uploads VPKs, a `_dir.vpk`'s archives with it, or one folder as it is, as a
new version of an item, or as a new item, private until `--visibility public`.
A version that isn't signed with a key of the configs needs their approval.

Players subscribed to a Workshop collection get its items' newest versions too.
So a source's collections that mirror its lists, in `workshop/collections.toml`,
are made the items of their lists that aren't held at every update:

```toml
[collections.3450000000]
list = "doi-config/workshop-ids-pvp.txt"
```

The update changes them signed in as an account that may, e.g. a contributor of
the collections of its own for the servers, with its refresh token, which lasts
about 200 days: `nwi-server workshop login` signs in with a QR code to scan in
the Steam app (shown with `qrencode` if it's installed) and prints it, to keep
as the credential `nwi-server.steam-refresh-token`:

```bash
nwi-server workshop login | systemd-creds encrypt \
  --name=nwi-server.steam-refresh-token - \
  /etc/credstore.encrypted/nwi-server.steam-refresh-token
```

The admins hear of a change that fails, to make it by hand, and of the sign-in a
month before it expires. The Web API can't change collections, so the update
does it as the community site does, which may change one day.

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

`nwi-server prepare` puts them into the server's folder, readable by the server
only; the passwords go into a config, not the command line, which every user
could see. Each server's RCON password is in `/run/nwi-server/rcon/<server>`,
which the members of the group `nwi-rcon` can read. `nwi-rcon` uses it:

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
which the image's updater fills with DepotDownloader, like `nwi-update.service` for
the systemd units, and which the servers mount. The packages come from the
public repository `https://repo.rev-crew.info/aurutils`, verified with its key,
`deploy/container/aurutils.asc`, or from a local pacman repository, like the one
of aurutils (`REPO_NAME` its name, `REPO_SERVER=file:///mnt/repo`, the build
context `repo` its folder). With Podman, from the repository's root:

```bash
podman build --format docker --build-context repo=$(mktemp -d) \
  --secret id=repo-key,src=deploy/container/aurutils.asc \
  -f deploy/container/Containerfile -t nwi-server .
```

`tests/integration/instance.py build` does the same, and `build --local` with
the local repository aurutils uses, e.g. for packages not published yet. The image's commands (`src/nwi_server_kit/container.py`) are the
server, `update` and `check`: `nwi-server update --image` and
`nwi-server check-updates` on the state folder, mounted at `/srv/state`, for the
servers whose environment files are mounted at `/etc/nwi-server`. The image's
configs and plugins are its own.

`deploy/quadlet` has the units for rootless Podman, the containers'
counterparts of `deploy/systemd`, with the state folder
`~/.local/state/nwi-server` and the settings in `~/.config/nwi-server`:

- `nwi-update.container` updates the state folder, as its systemd counterpart.
- `nwi-server@<server>.container` runs a server: its settings in
  `~/.config/nwi-server/<server>.env`, as for `nwi-server@.service`, its secrets
  in `~/.config/nwi-server/secrets` (which may be empty), on the host's
  network. The versions of its game's depot and workshop items are mounted with
  an overlay of the container's own (`:O`), its mods read-only, through the links
  the updater keeps in `~/.local/state/nwi-server/servers/<server>`, as a unit
  can't pick the folders by the server's game; the updater makes the workshop
  items one folder for the containers, `<game>/workshop.v`. It's ready once the image's
  health check, A2S like the systemd units' watchdog, passes, and restarted
  when the server stops answering. What it keeps goes into volumes.
- `nwi-build.service` pulls a clone of this repository and builds the image
  anew; `nwi-restart.service` builds, updates while the servers run and
  restarts them, with the new image, every day with
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

`tests/integration/instance.py` runs a server of one of the configs in a
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
tests/integration/instance.py build
# The games and the workshop items of all configs into the state folder: about
# 20 GB for Day of Infamy at first, and 10 GB for Insurgency's test server;
# with configs, e.g. update coop-commando, only theirs
tests/integration/instance.py update
tests/integration/instance.py up coop-commando
tests/integration/instance.py rcon sm plugins list
tests/integration/instance.py down
```

The server is then at this machine's address, port 27015, which `up` prints.
Not at `127.0.0.1`: rootless Podman passes connections from there on from the
pod's own address, and the server drops them. `build` and `up` take the packages
and SourceBans++'s tables from the public repository, verified with its key, or
with `NWI_TEST_REPO=local` from the local pacman repository, which they find
like aurutils: `aur repo --status`, or without aurutils the one repository of
pacman.conf with a `file://` server. `AUR_REPO` and `AUR_DBROOT` name its name
and folder, as for aurutils. `build --testing` builds the image with Arch
Linux's testing repositories, for packages built against them on a machine that
uses them. `rcon` runs a command on the server over RCON, as `nwi-rcon` does,
with the password in `RCON_PASSWORD`.

`up --developer 2` starts the server with the game's developer messages, and
options after `--` go on its command line, after those of its `server.toml`:

```bash
tests/integration/instance.py up --developer 2 coop-commando \
  -- +sv_cheats 1
```

They're `LAUNCH_OPTIONS` of the server's environment file, which
`nwi-server start` adds, for the systemd units of `up --db-only` too.

The systemd units can be tested on this machine as well, set up as in [Running
with systemd](#running-with-systemd), with only the test instance's database:
`up --db-only` starts it at `127.0.0.1:3306` (`TEST_DB_PORT` for another port)
and prints the commands that copy the server's environment file to
`/etc/nwi-server` and its database's credential to `/etc/credstore`, unencrypted
for the test. `down` removes the database again.

The admins get into the database and, through the server's environment file,
into SourceMod's `admins_simple.ini` (`nwi-server prepare`). So
`TEST_ADMIN` in the environment file of any server, e.g.
`/etc/nwi-server/<server>.env`, makes test admins on a server without the
database, too. The live servers' environment files don't have it.

```bash
tests/integration/instance.py up --db-only coop-commando
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

`tests/integration/sanitiser` builds an image on top of the usual one with these
packages and the sanitisers' 32-bit runtime (`compiler-rt`), from that
repository's folder. With `SANITISER` set to the sanitisers of the build,
`instance.py up` starts the server from that image, and
`nwi-server start` preloads the runtime into srcds. The reports go to the
server's output, with stack traces:

```bash
podman build --format docker --build-context packages=/tmp/aur-build.XXXXXX \
  -f tests/integration/sanitiser/Containerfile \
  -t localhost/nwi-server-sanitiser .
SANITISER=undefined tests/integration/instance.py up soak-bots
podman logs nwi-test-server 2>&1 |
  grep -E 'runtime error:|ERROR: AddressSanitizer'
```

The soak test runs the `soak-bots` server for hours without players: 20 bots a
team on the frontline maps at 128 tick, the maps changing as in a game. Its
config is a test's, in `tests/integration/servers/soak-bots`, with its own settings and
mapcycle in its `cfg` folder; the test instance mounts it among the image's
configs, so it runs in the container only. `instance.py soak` updates and
starts it, with `tests/integration/soak_watch.py` logging the map, the bots, srcds' memory
and the number of sanitiser reports every five minutes as TSV, adding the bots
again when a map change lost them. At the end, or when it's stopped, it keeps
the server's output next to the log and removes the test instance.
AddressSanitizer takes a lot more memory and time than
UndefinedBehaviorSanitizer, so a long run with it is best left overnight:

```bash
SANITISER=address tests/integration/instance.py soak --hours 8 soak.tsv
```

The round test has bots play a config's rounds and checks that they do:
`instance.py rounds` updates and starts each config in turn, `coop-commando`
and `soak-bots` by default, puts in its plugin
(`tests/integration/plugins/nwi_test_rounds.sp`, which logs the game's round
events), lets bots play with `nwi_bot_only_rounds` and checks, each in its
time, that the game and a round start, that the bots take an objective and
die, and that SourceMod reports no errors of our plugins
(`tests/integration/rounds.py`). It takes a few minutes a config:

```bash
tests/integration/instance.py rounds
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
and don't try to load it. The update removes the outdated copies of
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
servers take over; `nwi-server make-mods` makes the playlist's config of them
from the installed game, `cfg/doi-config/playlists/<playlist>.cfg`.

At every map start the game runs its own config of the game mode,
`cfg/default_server_<mode>.cfg`. The `nwi_mode_config` plugin takes the game
mode from it and runs the game mode's configs that exist, each later one
replacing an earlier one's settings:

1. `basic_mode_<coop|pvp>.cfg`: all coop or PvP game modes
2. `basic_mode_<coop|pvp>-<mode>.cfg`: the game mode, in every playlist
3. `playlists/<playlist>-<mode>.cfg`: the settings the playlist forces in the
   game mode, made by `nwi-server make-mods`
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

`checks/check_configs.py`, a check before each commit, formats the configs (the
cvar bare, its value quoted) and checks them against the game's cvars and
commands in `checks/cvars.json`: unknown names, values out of their bounds, cheat
cvars and the rules above. `checks/dump_cvars.py` makes `checks/cvars.json` from
a running server, after a game update; for the game's own bounds, start it
without the unlocker, e.g. with
`DISABLE_PLUGINS=nwi_cvar_unlocker tests/integration/instance.py up`.

### Tickrate

The servers run at 128 tick by default, where Day of Infamy's default is 64:
`tickrate` of a server's `server.toml`, e.g. `tickrate = 64`, sets it
(`-tickrate` on its command line), and its `server.cfg` makes clients send and
get as many updates per second, whatever their own settings, which default to
64.

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
`nwi_gamedata.inc`), whose gamedata covers Windows as well, 32-bit and 64-bit,
found in the game's server.dll but not tested on a Windows server.

On 64-bit Windows, it takes SourceMod 1.13 to compile `nwi_gamedata`: what
matters is the SourceMod whose compiler and include files built the plugin, not
the one the server runs. There, the game's code reaches the physics environment
and the playlists' globals relative to the instruction (x86-64's RIP), which
SourceMod's gamedata can't follow, so `nwi_gamedata` works out their addresses
itself and reads 64-bit pointers there, which only 1.13's
`LoadAddressFromAddress` can. A plugin built with 1.12 leaves the step as the
game sets it, and above 64 tick logs an error that grenades bounce more; the
playlists' replacements are left out with an error too. Linux and 32-bit
Windows work with either version.

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

### Rounds with bots only

The game doesn't start a round without human players, also with bots on the
teams: it waits for players, and a dedicated server stays in its pregame
state until one is on it. The coop modes also lose a round at once without
human players on the players' team. `nwi_bot_only_rounds 1` (`nwi_gamedata`,
off by default) lets bots play: while bots are on the playing teams, the game
doesn't wait for players, starts without them, and, until a human player
connects, counts the bots of a team as its human players. That keeps a server,
say a casual PvP one, playing with bots until players join, and the round test
uses it. Coop needs bots on the players' team for it, the game's AI teammates
(`mp_coop_ai_teammates 1`). Its gamedata is Linux's only so far.

### Difficulty scaler

The `nwi_difficulty_scaler` SourceMod plugin adjusts the number of bots to the
number of players at every round start, independently of the map's scripting,
within the 16 players of a coop team. A game mode's config sets the numbers
with `nwi_mode_cvar` (see [Configs](#configs)), so they change with the game
mode, and a game mode without them isn't scaled:

```text
nwi_mode_cvar "nwi_scaler_enabled" "1"
nwi_mode_cvar "nwi_scaler_enemy_base" "3"
nwi_mode_cvar "nwi_scaler_enemy_per_player" "2"
nwi_mode_cvar "nwi_scaler_friendly_base" "5"
nwi_mode_cvar "nwi_scaler_friendly_per_player" "1"
```

Stronghold and Raid have these, Entrenchment 6 enemies and 3 friendlies to
start with (`basic_mode_coop-<mode>.cfg`). Day of Infamy's own scaling of
`doi_bot_count_default_*_min_players` to `_max_players` is linear in the players
as well, but caps nothing: measured with `doi_fake_human_players`, 3 + 2 a
player gives 19 enemies at 8 players, more than a team's 16 slots. In
Insurgency, the plugin sets the game mode's `ins_bot_count_<mode>`, e.g.
`ins_bot_count_checkpoint`; no Insurgency game mode has settings yet. The plugin sets
the counts, and Day of Infamy's `doi_bot_count_override` unless it's on
already, as `nwi_mode_cvar` does, so they come back when the game mode changes.

### Mods

The mods add game modes to maps that don't have them, e.g. invasion, the
cooperative offensive, to maps that only have offensive. A map's script
(`maps/<map>.txt`) has a block for each of its game modes, with its control
points, spawn zones and entities. The scripts come from the game's VPKs or from
a map's workshop item, so they aren't part of this repository: each
`mods/<game>/<mod>.toml` says which blocks of which maps to copy and how to adjust the
copies, and `nwi-server make-mods` makes the mod folder `custom/<mod>` from the
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
nwi-server make-mods --game GAME --workshop WORKSHOP OUTPUT mods/doi
nwi-server make-mods --game GAME --workshop WORKSHOP --check
```

`GAME` is the game's install, with `doi` in it, `WORKSHOP` the folder of the
workshop items, and `OUTPUT`, which is replaced, gets the `custom` folder
for the server's `doi` folder.

### Playlists

The `nwi_playlist_unlock` plugin lifts the playlists' restrictions, in Day of
Infamy and Insurgency: the server takes each playlist from a replacement in
`cfg/doi-config/playlists/<playlist>.playlist` where there is one, which
`nwi-server make-mods` makes by the `[[replace]]` tables of `mods/<game>/*.toml`. Ours
(`mods/doi/playlists.toml`) drop `allowed_maps`, the forced settings and the
required slots from every playlist, in its own keys and its rulesets: any map
and game mode may run, the playlists force no settings (their configs, also
from `nwi-server make-mods`, take over those we keep), and any number of slots is
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
enforced them. Not tested yet: the registration for the stats, and Windows,
whose gamedata (32-bit and 64-bit) was found in the game's server.dll. There,
`Playlist::SetData` has no function of its own, so `nwi_gamedata` loads the
replacement before each merge of the playlist's data instead, and on 64-bit
Windows it needs SourceMod 1.13, as the physics step does (see
[Tickrate](#tickrate)).

After each game update, the update checks that the game still has the
functions of the plugins' gamedata, by their symbols (`nwi-server
check-gamedata`), so an update that moved them fails there rather
than leaving the servers with the playlists' restrictions.

### GeoIP2 databases

SourceMod and the SourceBans++ web panel both use MaxMind's GeoIP2 databases.
Both ship MMDB files, but those haven't been updated in years. Instead, install
and configure [geoipupdate](https://github.com/maxmind/geoipupdate), which needs
a free MaxMind account and keeps current databases in `/var/lib/GeoIP`.
The `sourcemod` package and the web panel of the
[sourcebans-pp](https://aur.archlinux.org/packages/sourcebans-pp) package link
their databases from there. The systemd units' servers read them there; the
container image links them there too, so a container needs the host's folder:
the test instance mounts it when it exists, and the Quadlet unit
`nwi-server@.container` has the line to uncomment. A server whose plugins need
them says so with `geoip = true` in its `server.toml`: it then doesn't start
without a database, rather than run with plugins that can't locate players.

### ClamAV

The scan of new workshop versions (see [Workshop items](#workshop-items)) needs
ClamAV's daemon on the server: the `clamav` package, with `clamav-daemon.service`
and `clamav-freshclam.service` enabled, which keep its signatures current. Without
a running `clamd`, the updater holds every new version. More signatures catch more:
the servers also use SecuriteInfo's, e.g. through
[fangfrisch](https://rseichter.github.io/fangfrisch/) or SecuriteInfo's own
instructions, which need a free account.

`clamd` scans a stream up to its `StreamMaxLength`, 100 MB by default, while maps
are often 100 to 500 MB: a larger file isn't scanned by ClamAV, only by the
structural checks, and the update's log says so. So raise the limits in
`/etc/clamav/clamd.conf`, then restart `clamav-daemon.service`:

```text
# Workshop maps up to 1 GB (nwi-server-kit's scan streams each file)
StreamMaxLength 1G
MaxScanSize 1G
MaxFileSize 1G
```

The updater reaches `clamd` over its socket (`LocalSocket`, `/run/clamav/clamd.ctl`
by default), which every user may connect to. The scan streams each file there, so
`clamd` needs no access to the state folder.

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
aren't part of this repository: `nwi-server make-mods` makes them from the game's
own when a server is set up, so they remain New World Interactive's.

`REUSE.toml`, the file headers and the `LICENSES` folder say this in the
[REUSE](https://reuse.software/) format.
