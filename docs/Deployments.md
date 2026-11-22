<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# systemd and containers

The servers run in one of two ways (see the [README](../README.md)): as
systemd services on the host (`deploy/systemd`, with the package of
`deploy/arch`), or in containers of the image (`deploy/container`), with
rootless Podman's Quadlet units (`deploy/quadlet`). Both run the same server
with the same configs and plugins, and download the games and the workshop
items the same way, into a state folder with versions of each. They differ in
what they do around it, and the systemd units do more. This is what differs.

| | systemd | Containers |
| --- | --- | --- |
| Configs and plugins | of config sources, each a repository and branch or tag, pulled by every update | the image's, of the checkout it's built of; new ones with a new image (`nwi-build.service`) |
| SourceMod, Metamod:Source and plugin packages | the host's, copied when they change | the image's |
| A new version of a layer | on trial: a server that fails falls back to the version before, blamed by where it failed (`nwi-server health`) | used as soon as it's there: no trial, no fallback |
| Workshop approval: new versions | held unless approved or signed (`workshop/approved.toml`) | the same |
| Workshop approval: what a server lists | only the items whose version it runs is the Workshop's; their maps leave the mapcycle | every item of its list, see below |
| Workshop collections | kept in step with the lists, without held items | not changed |
| Notifications (mail, Discord) | of held versions, failed servers, versions without tries left | none: the update's go nowhere |
| Each server's user | a user of its own (`DynamicUser=`): no server can touch another's files | the image's user, mapped to the host's, the same for all; each container has its own files |
| Sandbox | the unit's (`systemd-analyze security` 2.0, see [Hardening](Hardening.md#systemd)) | the container runtime's |
| Secrets | systemd credentials, each server only its own | `~/.config/nwi-server/secrets`, laid out like the game's folder, the same for every server |
| RCON password | generated at every start, for the group `nwi-rcon` (`nwi-rcon --server`) | from the secrets |
| Hung server | systemd's watchdog restarts it, after it dumped its core | the health check (A2S) kills and restarts it |
| Metrics | `nwi-metrics.service` | none |
| Updates and restarts | `nwi-restart.timer`, `nwi-update-check.timer` | the same, as user units, with a new image first |

## Workshop items in containers

The systemd units mount each workshop item as a layer of its own, and a
server's mount writes its workshop list and mapcycle without the items whose
version isn't the Workshop's newest (`src/nwi_server_kit/mount.py`). Players'
clients always download an item's newest version, so a server that ran an
older one would have files that differ from the players', which breaks the
game.

A container mounts one folder of all its game's items, each in its newest
version that passed the update (`nwi-server update --image`), and its server
lists every item of its config's list. So in a container:

- a held version (not approved, or held by the scan) stays off the server, but
  the item stays on its list: players download the held version, the server
  runs the one before.
- an item without any approved version, e.g. of a source without
  `workshop/approved.toml`, isn't in the folder at all, and the game downloads
  an item of its list that it doesn't have itself: past the approval and the
  scan.

Until containers filter their lists like the mounts do: give a container's
configs a complete `workshop/approved.toml` (`nwi-server workshop freeze`),
and when a version is held, take its item off the lists of the container
servers until it's approved.

## Choosing

For a machine of its own, the systemd units: the trial, the notifications and
the stricter separation of the servers are worth the package. Containers suit a
host that runs other things, or where installing a package isn't an option, and
`tests/integration/instance.py` uses them for the tests.
