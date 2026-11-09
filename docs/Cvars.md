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
  of human players. In coop that's 16, the human slots of the players' team
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
