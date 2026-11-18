// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// What the plugins of doi-config share: the games they run in, New World Interactive's Day of Infamy
// and Insurgency (2014), which share their engine branch, game modes and most of their code

#if defined _nwi_included
 #endinput
#endif
#define _nwi_included

enum NWIGame
{
    NWIGame_Other = 0,
    NWIGame_DoI,        // Day of Infamy, game folder doi
    NWIGame_Insurgency  // Insurgency (2014), game folder insurgency
};

// The game the server runs, by its game folder
stock NWIGame NWI_GetGame()
{
    char game[PLATFORM_MAX_PATH];
    GetGameFolderName(game, sizeof(game));
    if (StrEqual(game, "doi"))
        return NWIGame_DoI;
    if (StrEqual(game, "insurgency"))
        return NWIGame_Insurgency;
    return NWIGame_Other;
}

// Stops the plugin in a game that isn't one of New World Interactive's, for plugins that work in
// both Day of Infamy and Insurgency
stock NWIGame NWI_RequireGame()
{
    NWIGame game = NWI_GetGame();
    if (game == NWIGame_Other)
    {
        char folder[PLATFORM_MAX_PATH];
        GetGameFolderName(folder, sizeof(folder));
        SetFailState("This plugin is for Day of Infamy (doi) and Insurgency (insurgency), not %s", folder);
    }
    return game;
}

// Stops the plugin in another game than Day of Infamy, for what only Day of Infamy has
stock void NWI_RequireDoI()
{
    if (NWI_RequireGame() != NWIGame_DoI)
        SetFailState("This plugin is for Day of Infamy (doi) only, not Insurgency");
}

// The players a team may have in Day of Infamy's coop modes, by the game's rules: the human players
// and the friendly bots on one team, the enemy bots on the other. The PvP modes allow 20.
#define NWI_DOI_COOP_TEAM_SLOTS 16

// The players a team can have: half of the server's slots (maxplayers), without the one of
// SourceTV, and at most the limit of the game's rules, e.g. 2 x 16 + 1 for SourceTV = 33 slots
stock int NWI_TeamSlots(int limit)
{
    int slots = MaxClients;
    ConVar tv = FindConVar("tv_enable");
    if (tv != null && tv.BoolValue)
        slots--;
    slots /= 2;
    return slots < limit ? slots : limit;
}
