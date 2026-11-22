<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# Mods and playlists

## Mods

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

## Playlists

The `nwi_playlist_unlock` plugin lifts the playlists' restrictions, in Day of
Infamy and Insurgency: the server takes each playlist from a replacement in
`cfg/nwi-config/playlists/<playlist>.playlist` where there is one, which
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
still before the first map's settings: before each merge of a playlist's
data with its ruleset, it loads the replacement into the playlist's data. A
playlist without a replacement stays as the game has it.

It replaces the patch of the server library that earlier versions of this
repository applied in memory, with a library preloaded into srcds. Tested
against that patch on a local `coop-commando` server: the playlist's limits,
forced settings and maps were the same with either, and without both, the game
enforced them. Not tested yet: the registration for the stats, and Windows,
whose gamedata (32-bit and 64-bit) was found in the game's server.dll. On
64-bit Windows it needs SourceMod 1.13, as the physics step does (see
[Tickrate](Plugins.md#tickrate)).

After each game update, the update checks that the game still has the
functions of the plugins' gamedata, by their symbols (`nwi-server
check-gamedata`), so an update that moved them fails there rather
than leaving the servers with the playlists' restrictions.
