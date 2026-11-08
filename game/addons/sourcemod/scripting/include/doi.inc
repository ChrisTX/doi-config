// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// What the plugins of doi-config share

#if defined _doi_included
 #endinput
#endif
#define _doi_included

// The players a team may have in the coop modes, by the game's rules: the human players and the
// friendly bots on one team, the enemy bots on the other. The PvP modes allow 20.
#define DOI_COOP_TEAM_SLOTS 16

// Stops the plugin in another game than Day of Infamy, whose cvars and game modes it relies on
stock void DOI_RequireGame()
{
    char game[PLATFORM_MAX_PATH];
    GetGameFolderName(game, sizeof(game));
    if (!StrEqual(game, "doi"))
        SetFailState("This plugin is for Day of Infamy (doi) only, not %s", game);
}

// The players a team can have: half of the server's slots (maxplayers), without the one of
// SourceTV, and at most the limit of the game's rules, e.g. 2 x 16 + 1 for SourceTV = 33 slots
stock int DOI_TeamSlots(int limit)
{
    int slots = MaxClients;
    ConVar tv = FindConVar("tv_enable");
    if (tv != null && tv.BoolValue)
        slots--;
    slots /= 2;
    return slots < limit ? slots : limit;
}
