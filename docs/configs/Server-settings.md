<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# Server settings

A server's settings are its `servers/<config>/server.toml`: what the server is,
the same wherever it runs. What depends on the machine, its ports and
passwords, is in its environment file instead (see below). For example, Coop
Commando's
[`servers/coop-commando/server.toml`](../../servers/coop-commando/server.toml):

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
teams (see [Playlists](Mods-and-playlists.md#playlists)).

With `game = "insurgency"`, a server runs Insurgency instead of Day of Infamy,
like the test server `servers/ins-test`. A config without `game` is of its
config source's game: the one it has a folder of in `game`, e.g. Insurgency for
a community's configs with only `game/insurgency`, or Day of Infamy if the
source has both, like this one. `nwi-server configs` lists a source's configs
with their games. The tools only keep the apps of the
games' dedicated servers (`nwi-server games`) and find the rest: the depots,
the game's folder (`doi` or `insurgency`, the one with `gameinfo.txt`) and the
workshop's app of the items. The configs of `game/doi` are Day of Infamy's,
those of `game/insurgency` Insurgency's.

At each start, `nwi-server prepare` makes the server's `cfg/server.cfg` of
it with `nwi-server server-config`, which describes the keys: the names of the
server and SourceTV, and the configs it runs (see [Configs](Configs.md)). It also
copies the server's list of workshop items to `subscribed_file_ids.txt` in the
`doi` folder, the list the game downloads and mounts by default. The launcher,
`nwi-server start`, takes the server's slots, whether it's a LAN server,
the first map, the theater and its own options of the command line from it, and
starts it with the workshop if it has a list. Its passwords and other secrets
are credentials (see [Secrets](../kit/Secrets.md)).

A server without a `server.toml`, of no config of `servers`, needs its own
`cfg/server.cfg`.
