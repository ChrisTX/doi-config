// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// Lifts the restrictions of the playlists, in Day of Infamy and Insurgency, so that servers with their
// own maps and settings stay in the playlists' browser:
//
// - allowed_maps: any map and game mode may run, not only those the playlist lists
// - forced_cvars and forced_cvars_dedicated: the playlist no longer forces its settings, which the
//   servers' configs set instead (the playlists' configs of tools/make_mods.py)
// - require_maxplayers_min and _max: any number of slots
//
// In the playlist's own keys and in each of its rulesets' blocks, with what the rulesets merge in (the
// <key>_merge_method keys). In Day of Infamy, the server also registers for the game's stats with
// workshop content. It edits the playlists through nwi_gamedata (NWI_AddPlaylistEditor), in memory:
// the files stay as they are, as do their checksums, which the game takes before it reads them.

#include <sourcemod>
#include <nwi>
#include <nwi_gamedata>

#pragma semicolon 1
#pragma newdecls required

public Plugin myinfo =
{
    name        = "NWI playlist unlock",
    author      = "DOI revival project",
    description = "Lifts the restrictions of the playlists: maps, forced settings, slots",
    version     = "1.0",
    url         = "https://rev-crew.info"
};

// The blocks and keys a playlist restricts the server with
char g_dropped[][] = {
    "allowed_maps",
    "forced_cvars",
    "forced_cvars_dedicated",
    "require_maxplayers_min",
    "require_maxplayers_max",
};

// Whether the editor is added to the nwi_gamedata that's loaded
bool g_added = false;

public void OnPluginStart()
{
    NWI_RequireGame();
}

public void OnAllPluginsLoaded()
{
    AddEditor();
}

public void OnLibraryAdded(const char[] name)
{
    if (StrEqual(name, NWI_GAMEDATA_LIBRARY))
        AddEditor();
}

public void OnLibraryRemoved(const char[] name)
{
    if (StrEqual(name, NWI_GAMEDATA_LIBRARY))
        g_added = false;
}

void AddEditor()
{
    if (g_added || !NWI_IsGamedataLoaded())
        return;
    g_added = NWI_AddPlaylistEditor(EditPlaylist);
    if (!g_added)
        LogError("Can't edit the playlists: nwi_gamedata lacks the playlists' functions");
}

Action EditPlaylist(const char[] playlist, const char[] ruleset, KeyValues data)
{
    // Without require_maxplayers_min and _max, the game's GetRequiredMaxPlayers answers 1 and -1 (no
    // limit), its defaults, which the patch of the server library forced as well
    Unlock(data, "", 0);
    NWI_KvForEachRuleset(data, Unlock);
    return Plugin_Changed;
}

void Unlock(KeyValues kv, const char[] name, any data)
{
    char mergeMethod[64];
    for (int i = 0; i < sizeof(g_dropped); i++)
    {
        NWI_KvDeleteAll(kv, g_dropped[i]);
        FormatEx(mergeMethod, sizeof(mergeMethod), "%s_merge_method", g_dropped[i]);
        NWI_KvDeleteAll(kv, mergeMethod);
    }
}

public void NWI_OnStatsWorkshopCheck(bool &workshop)
{
    workshop = false;
}
