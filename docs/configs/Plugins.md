<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# Plugins

## Tickrate

*Both games; the fix of 128 tick is tested with Day of Infamy only, and
Insurgency's test server runs 64 tick.*

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

## Server visibility

*Day of Infamy: its playlists' browser, as measured. Insurgency is untested.*

The game's browser of a playlist's servers hides servers whose players, less
their bots, are outside the playlist's players filter, 0 to 8 in the coop
playlists, so a coop server disappears once it's busy (see
[Cvars](../games/Cvars.md#it-doesnt-make-busy-servers-visible)). The `nwi_server_visibility` plugin counts the
players above the playlist's maximum as bots in what the server sends to Steam:
12 players on a coop server are 12 players and 4 bots there, which the browser
counts as 8. The number of players stays true, as do `status` and the server's
own answers. `nwi_visibility_max_humans` sets the maximum: -1 (the default)
takes the playlist's, 0 turns it off.

It needs a pre-callback of DHooks (through `nwi_gamedata`), which the
`sourcemod` package's builds before 1.12.0.7260-4 didn't call: a signed
overflow in AMTL's hashes, which LTO miscompiled
([alliedmodders/amtl#142](https://github.com/alliedmodders/amtl/pull/142)).

## Rounds with bots only

The game doesn't start a round without human players, also with bots on the
teams: it waits for players, and a dedicated server stays in its pregame
state until one is on it. The coop modes also lose a round at once without
human players on the players' team. `nwi_bot_only_rounds 1` (`nwi_gamedata`,
off by default) lets bots play: while bots are on the playing teams, the game
doesn't wait for players, starts without them, and, until a human player
connects, counts the bots of a team as its human players. That keeps a server,
say a casual PvP one, playing with bots until players join, and the round test
uses it. Coop needs bots on the players' team for it, the game's AI teammates
(`mp_coop_ai_teammates 1`). Its gamedata covers Windows as well, 32-bit and
64-bit, tested with Day of Infamy's PvP and coop rounds under Wine. On 64-bit
Windows, it needs fixes of DHooks that SourceMod 1.13 doesn't have yet: its
detours crash without arguments, and its post-callbacks hand the caller the
return address instead of the function's return value, so the game would go on
waiting for players, and the coop modes would lose their rounds at once.

## Difficulty scaler

*Both games; no Insurgency game mode has settings yet.*

The `nwi_difficulty_scaler` SourceMod plugin adjusts the number of bots to the
number of players at every round start, independently of the map's scripting,
within the 16 players of a coop team. A game mode's config sets the numbers
with `nwi_mode_cvar` (see [Configs](Configs.md)), so they change with the game
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
