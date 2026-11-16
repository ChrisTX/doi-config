// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// Lifts the restrictions of the playlists, in Day of Infamy and Insurgency, so that servers with their
// own maps and settings stay in the playlists' browser: the server takes each playlist from its
// replacement in cfg/doi-config/playlists, where there is one, through nwi_gamedata
// (NWI_ReplacePlaylists). nwi-server make-mods makes the replacements by the [[replace]] tables of
// mods/<game>/*.toml, e.g. without allowed_maps, forced_cvars, forced_cvars_dedicated and
// require_maxplayers_min/_max. The game's files stay as they are, as do their checksums, which the
// game takes before it reads them.
//
// In Day of Infamy, the server also registers for the game's stats with workshop content.

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
    version     = "2.0",
    url         = "https://rev-crew.info"
};

// The folder of the replacements, relative to the game folder
#define REPLACEMENTS "cfg/doi-config/playlists"

public void OnPluginStart()
{
    NWI_RequireGame();
}

public void OnAllPluginsLoaded()
{
    ReplacePlaylists();
}

public void OnLibraryAdded(const char[] name)
{
    if (StrEqual(name, NWI_GAMEDATA_LIBRARY))
        ReplacePlaylists();
}

void ReplacePlaylists()
{
    if (NWI_IsGamedataLoaded() && !NWI_ReplacePlaylists(REPLACEMENTS))
        LogError("Can't replace the playlists: nwi_gamedata lacks the playlists' functions");
}

public void NWI_OnStatsWorkshopCheck(bool &workshop)
{
    workshop = false;
}
