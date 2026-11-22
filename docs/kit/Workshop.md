<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# Workshop items

## Workshop items

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
failures too.

A source without `workshop/approved.toml` approves no version: its servers
mount no workshop items, and the admins are told once. `nwi-server workshop
freeze` (below) makes the file of the current versions. A source that doesn't
want the gate says so explicitly, at the top of the file, which lets every
version through without review, except those the scan holds:

```toml
approve_all = true
```

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

## ClamAV

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
