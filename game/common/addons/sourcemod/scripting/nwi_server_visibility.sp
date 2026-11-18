// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// Keeps busy servers visible in the game's server browser of a playlist, in Day of Infamy and
// Insurgency.
//
// The browser of a playlist's servers hides those whose players, less their bots, are outside its
// players filter, and the filter's range is the playlist's (filters, players, min and max of its file):
// 0 to 8 in both games' coop playlists. So a coop server disappears as soon as more than 8 players are
// on it, exactly when it's busy, and players can't widen the filter (docs/Cvars.md). The server leaves
// its bots out of the counts it sends to Steam, which answers the browsers' queries.
//
// For the counts it sends to Steam (nwi_gamedata.inc, NWI_OnSteamServerDetails), the plugin counts the
// players above the playlist's maximum as bots: 12 players on a coop server are 12 players and 4 bots
// then, which the browser counts as 8. The number of players stays true, as do status and the server's
// own answers. nwi_visibility_max_humans sets the maximum: -1 takes the playlist's (none without a
// playlist, or one without a players filter, like the PvP playlists), 0 turns the plugin off.
//
// It needs DHooks' pre-callbacks (nwi_gamedata), which the sourcemod package's builds before
// 1.12.0.7260-4 didn't call: a signed overflow in AMTL's hashes, which LTO miscompiled
// (alliedmodders/amtl#142).

#include <sourcemod>
#include <nwi>
#include <nwi_gamedata>

#pragma semicolon 1
#pragma newdecls required

public Plugin myinfo =
{
    name        = "NWI server visibility",
    author      = "DOI revival project",
    description = "Keep busy servers visible in the playlists' server browser",
    version     = "1.0",
    url         = "https://rev-crew.info"
};

ConVar g_maxHumans;
ConVar g_playlist;
// The playlist's maximum of players in its filter, 0 for none
int g_playlistMax = 0;

public void OnPluginStart()
{
    NWI_RequireGame();
    g_maxHumans = CreateConVar("nwi_visibility_max_humans", "-1",
        "The most players the server reports to Steam beyond its bots, the rest as bots: -1 for the playlist's filter, 0 off",
        _, true, -1.0);
    g_playlist = FindConVar("sv_playlist");
    if (g_playlist != null)
        g_playlist.AddChangeHook(OnPlaylistChanged);
    ReadPlaylist();
}

public void OnConfigsExecuted()
{
    ReadPlaylist();
}

void OnPlaylistChanged(ConVar convar, const char[] oldValue, const char[] newValue)
{
    ReadPlaylist();
}

// The maximum of the players filter of the playlist's file, scripts/playlists/<sv_playlist>.playlist
void ReadPlaylist()
{
    g_playlistMax = 0;
    char playlist[PLATFORM_MAX_PATH], path[PLATFORM_MAX_PATH];
    if (g_playlist == null)
        return;
    g_playlist.GetString(playlist, sizeof(playlist));
    if (playlist[0] == '\0')
        return;
    Format(path, sizeof(path), "scripts/playlists/%s.playlist", playlist);
    KeyValues kv = new KeyValues("playlist");
    if (!kv.ImportFromFile(path))
    {
        LogError("Can't read %s, the playlist of sv_playlist", path);
    }
    else if (kv.JumpToKey("filters") && kv.JumpToKey("players"))
    {
        g_playlistMax = kv.GetNum("max", 0);
    }
    delete kv;
    if (g_playlistMax > 0)
        LogMessage("The playlist %s shows servers with up to %d players beyond their bots", playlist, g_playlistMax);
}

public void NWI_OnSteamServerDetails(int &humans, int &maximum, int &bots)
{
    int max = g_maxHumans.IntValue;
    if (max < 0)
        max = g_playlistMax;
    if (max > 0 && humans > max)
        bots += humans - max;
}
