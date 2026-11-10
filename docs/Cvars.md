# Day of Infamy cvars

Notes on cvars whose effect in Day of Infamy isn't what their name or
description suggests, tested on our servers. A full list of the cvars with
their defaults, bounds and flags is in `tools/cvars.json` (made by
`tools/dump_cvars.py`).

## sv_visiblemaxplayers

> Overrides the max players reported to prospective clients

It changes the **maximum** a server reports to the server browser, and nothing
else: not the number of players, and not who can join. On a coop server with
`maxplayers 33`, without players, the server answers queries (A2S_INFO) like
this:

| `sv_visiblemaxplayers` | Players | Maximum | Bots |
| --- | --- | --- | --- |
| `-1` (default) | 0 | 16 | 0 |
| `10` | 0 | 10 | 0 |
| `40` | 0 | 40 | 0 |

Things to know:

- Without it, the reported maximum isn't `maxplayers` but the game's maximum
  of human players. In coop that's `mp_coop_lobbysize`, 16 on our servers (see
  [below](#mp_coop_lobbysize)), at most the slots of the players' team
  (`maxplayers 33` is 2 × 16 and SourceTV's slot).
- The server leaves bots out of its answers: `status` showed 20 bots at the
  same time, but the query reports 0 players and 0 bots. The player count of
  the server browser is the number of humans.
- In the engine, `CBaseServer::GetMasterServerPlayerCounts` computes all
  three numbers: the human players, the maximum of human players or
  `sv_visiblemaxplayers` if it's above 0, and the bots. The query answers and
  the details sent to Steam take them from there, as do the server's tags,
  `status` and the server information connecting players get.
- Whether the server also refuses players once the visible maximum is reached
  isn't tested yet.

It's what reserved slots use: a server with 33 slots and
`sv_visiblemaxplayers 30` looks full at 30 players, and the last slots stay
free for admins.

### It doesn't make busy servers visible

`sv_visiblemaxplayers` can't keep a busy server in the game's server browser,
which it looks like it might. The game's browser of a playlist's servers, e.g.
those of Coop Commando, works like this:

1. It asks Steam for the servers of the playlist: dedicated, VAC-secured
   servers whose game data names the playlist (`mm/playlist:<name>`), and only
   servers with players if the players filter's minimum is above 0. A server
   only names its playlist when it passes the playlist's requirements, e.g. its
   number of slots.
2. It queries each of those servers itself and hides those whose number of
   human players (players minus bots) is outside the players filter.
3. The players filter's range comes from the playlist file in the player's
   game (`filters`, then `players`, `min` and `max`), and the filter can't go
   beyond it. In NWI's coop playlists it's 0 to 8.

So a coop server disappears from the playlist's browser as soon as more than 8
players are on it, exactly when it's busy, and players can't widen the filter.
The maximum the server reports doesn't take part in this, only the number of
players. Favourites, the Internet tab of the server browser and community
server lists still show it.

## mp_coop_lobbysize

> Size of coop lobby

The number of human players in coop: the "maximum of human players" of
[sv_visiblemaxplayers](#sv_visiblemaxplayers), which the server reports to the
server browser and in `status`. Its default of 6 is the one of the Insurgency code it
comes from; NWI's coop playlists set it to 8 in their `cvars`, the settings a
server may change (not in `forced_cvars`). `basic_coop.cfg` sets
it to 16, all the slots of the players' team.

In the game's code (`server_srv.so`), `CINSRules::GetMaxHumanPlayers`, which
Day of Infamy's coop (`CDOIRulesCoop`) doesn't override, returns in coop:

1. `mp_coop_lobbysize`, or `maxplayers` if it's 0 or less,
2. at most the capacity of the players' team.

The engine asks the game for this number through `IServerGameClients`
(`CServerGameClients::GetMaxHumanPlayers`, which calls the game rules'
`GetMaxHumanPlayers`, a virtual function: Ghidra shows no calls to it, only the
game modes' vtables). Insurgency's coop modes, which are still in the code
(Conquer, Survival, Outpost, Hunt, `CINSRulesCoopBase`), also take their bot
counts from it; Day of Infamy's coop doesn't, it has `doi_coop_lobby_size`.

Whether a server refuses players beyond it isn't tested yet. It doesn't keep a
busy server in the playlist's server browser either: like
[sv_visiblemaxplayers](#it-doesnt-make-busy-servers-visible) it changes the
maximum, which the browser doesn't filter on.

## doi_coop_lobby_size

> Size of DOI coop lobby

Not the players of a lobby, but the number of players at which Day of Infamy's
coop reaches its most bots. Its default is 8, the players of NWI's coop lobbies;
`basic_coop.cfg` sets it to 16, like `mp_coop_lobbysize`, so the bots grow with
the players up to the 16 of a team.

`CDOIRulesCoop::UpdateDesiredBotCount` computes the bots of each team from the
number of human players on the players' team (or `doi_fake_human_players` if
it's above 0):

```text
scale = (players - 1) / (doi_coop_lobby_size - 1), between 0 and 1
bots  = min + (max - min) × scale
```

To this it adds a number per team from another of the game rules' functions,
which isn't examined yet. `min` and `max` are the game rules' own counts, e.g.
of the objective, and where there are none (or `doi_bot_count_override` is set)
`doi_bot_count_default_enemy_min_players` and
`doi_bot_count_default_enemy_max_players` for the bots' team (`…_friendly_…`
for bots on the players' team, `doi_bot_count_solo_*` in solo games). With the
default 8, a server reaches its most bots with 8 players, and more players get
no more bots.

Both lobby sizes come from the game's code (`server_srv.so` of 3.2.1.5, read
with Ghidra); the numbers of `mp_coop_lobbysize` are the ones measured for
[sv_visiblemaxplayers](#sv_visiblemaxplayers).

## sv_battleye

> Enable BattlEye?

Does nothing any more: the game no longer ships BattlEye, which it removed in
December 2025 ([the update's notes](https://steamdb.info/patchnotes/21294077/),
the [change of the Linux server's depot](https://steamdb.info/depot/462311/history/?changeid=M:9106077001589815964)).
The cvar still exists, and NWI's playlists still set it to 1 in their
`forced_cvars_dedicated`.

The Linux server has the engine's side of it (`CBattleyeServer` in
`engine_srv.so`), which loads the BattlEye server module only when the cvar is
set. With `sv_battleye 1`, it tries `bin/BattlEye/BEServer.so`, which isn't
there any more, logs

```text
[CBattleyeServer] Failed to load BattlEye server module.
```

and goes on without it, the cvar staying at 1. The default is 0. On our test
server, a playlist's `forced_cvars_dedicated` with `sv_battleye 1` didn't set
it on map changes; the message only appeared when it was set by hand.
