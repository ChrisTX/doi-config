<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# Running with systemd

[systemd and containers](Deployments.md) compares this with running the
servers in containers: the systemd units do more around the servers, e.g. the
trial of new versions and the notifications.

The servers run as system services, one instance per server, which share one
install of each game. The games, and the workshop items, are those of the
servers: each `/etc/nwi-server/<server>.env` is a server, its game its config's
or `GAME` of its environment file without one (`nwi-server games`), which
`nwi-server add` writes. Each server
and the updater run as users of their own (`DynamicUser=`): a server can't
change another's files, nor the layers they share, which the updater makes. Each
server is put together with overlayfs from read-only layers, top first:

- the server's folder in `servers`, if there's one
- this repository's plugins, compiled by `nwi-update.service`
- the mods of `mods/<game>` and the playlists' configs, made by
  `nwi-update.service`
- `game/<game>` of this repository, then its `game/common`
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
of the servers' config sources (see [Config sources](Config-sources.md)).
SourceMod and Metamod:Source are copied from `SOURCEMOD_DIR` and `METAMOD_DIR`,
`/usr/lib/sourcemod` and `/usr/lib/metamod` by default.

- `nwi-update.service` updates the layers (`nwi-server update`), in its state
  `/var/lib/nwi-server/layers`, as versions of what it downloads and builds
  (see `src/nwi_server_kit/update.py`): the configs of each config source
  (`config-<source>.v`) and their compiled plugins (`plugins-<source>.v`), each
  depot of the games of the servers (`depot-<depot>.v`), which the games share,
  like the Steam client library's, and of each game its servers' workshop items
  (`<game>/item-<item>.v`) and the mods of each source (`<game>/mods-<source>.v`,
  see [Mods](../configs/Mods-and-playlists.md#mods)). It downloads with DepotDownloader into `downloads`, the
  workshop items' current versions, which the game itself never gets once it
  has an item, and checks each game against each source's gamedata (see
  [Playlists](../configs/Mods-and-playlists.md#playlists)). A version is a reflinked copy (btrfs, XFS), which
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
  the one `SERVER_CONFIG_NAME` names; without one, `GAME` says its game, its
  config source's by default.
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

Then, as root, the default config source, which the first update clones, and a
server of one of its configs, with its secrets as credentials (see
[Secrets](Secrets.md)). `nwi-server configs` lists the source's configs and their
games, and `nwi-server add` writes the server's settings,
`/etc/nwi-server/coop-commando.env`: its config, the one of its name without
`--config`, and ports that the other servers don't use. It says the server's
game and how to start it:

```bash
printf 'URL=%s\n' https://github.com/ChrisTX/doi-config.git |
  install -D -m 644 /dev/stdin /etc/nwi-server/configs/default.env
nwi-server configs
nwi-server add coop-commando
systemctl enable --now nwi-server@coop-commando.service nwi-servers.target
systemctl enable --now nwi-restart.timer nwi-update-check.timer
```

A second server of the same config gets a name of its own,
`nwi-server add coop-2 --config coop-commando`, one of another source
`--source`, and a server without a config its game, `--game insurgency`.
