<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# Configs

A server's configs run once, when it starts, from the `server.cfg` its
`server.toml` makes: its `configs_before`, SourceTV's settings, the settings the
playlist forces, as far as we take them over, then ours, those all servers
share (`basic_settings.cfg`), and its `configs_after`, like those of the coop or
PvP servers (`basic_coop.cfg`, `basic_pvp.cfg`). The game forces a playlist's settings, but the server
library's patch stops it, so `mods/doi/playlists.toml` says which of them the
servers take over; `nwi-server make-mods` makes the playlist's config of them
from the installed game, `cfg/nwi-config/playlists/<playlist>.cfg`.

At every map start the game runs its own config of the game mode,
`cfg/default_server_<mode>.cfg`. The `nwi_mode_config` plugin takes the game
mode from it and runs the game mode's configs that exist, each later one
replacing an earlier one's settings, each of `cfg/nwi-config` (the shared and
Insurgency's) and then of `cfg/doi-config` (Day of Infamy's):

1. `basic_mode_<coop|pvp>.cfg`: all coop or PvP game modes
2. `basic_mode_<coop|pvp>-<mode>.cfg`: the game mode, in every playlist
3. `playlists/<playlist>-<mode>.cfg`: the settings the playlist forces in the
   game mode, made by `nwi-server make-mods` (in `cfg/nwi-config` only)
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
cvar bare, its value quoted) and checks them against the cvars and commands of
the games they run in, `checks/cvars/<game>.json`: those of `game/common`
against both games', those of `game/<game>` and a server's own against their
game's. It finds unknown names, values out of their bounds, cheat cvars and the
rules above, and checks the commands' arguments by their signatures in
`checks/commands.toml`, which editors can use too: the game's help describes them
in a sentence, if at all. After a game update, the test instance dumps a game's cvars anew
from its test server, started without the unlocker for the game's own bounds:

```bash
tests/integration/instance.py dump-cvars doi
tests/integration/instance.py dump-cvars --with-descriptions insurgency
```

With `--with-descriptions`, the help texts of the cvars and commands go into
`checks/cvars/descriptions/<game>.json` too, for editors on your own machine.
They're the game's and SourceMod's texts, so git ignores them: the repository
only has the names, defaults, bounds and flags.
