// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// Scales the number of bots in the coop modes to the number of human players at the start of
// each round, independently of the map's scripting. The game mode comes from nwi_mode_config.smx
// (nwi_mode_config.inc).
//
// Day of Infamy only so far: Insurgency's bot counts are cvars of each game mode
// (ins_bot_count_<mode>_min and _max, e.g. checkpoint's), not Day of Infamy's doi_bot_count_*.

#include <sourcemod>
#include <sdktools>
#include <nwi>
#include <nwi_mode_config>

public Plugin myinfo =
{
    name    = "NWI difficulty scaler",
    author    = "DOI revival project",
    description = "Scale difficulty dynamically",
    version   = "2.0",
    url   = "https://rev-crew.info"
}

// Whether the bot counts are this plugin's, which a game mode it doesn't scale gives back to the game
bool g_scaled = false;

public OnPluginStart() {
    NWI_RequireDoI();
    // The bot counts are set anew at every round start
    HookEvent("round_start", EventHandler, EventHookMode_Post);
}

// The human players in game; bots and players still connecting don't count
GetPlayerCount()
{
    int players = 0;
    for (int i = 1; i <= MaxClients; i++)
    {
        if (IsClientInGame(i) && !IsFakeClient(i))
            players++;
    }
    return players;
}

public EventHandler(Handle:event, const String:name[], bool:dontBroadcast) {
    AdjustDifficulty();
}

// Sets a cvar silently, without announcing the change to the players
public SetVarValue(const String:name[], int value) {
    Handle my_cvar = FindConVar(name);
    // A cvar a game update removed would stop the remaining changes with a native error
    if (my_cvar == null) {
        LogError("Can't find the cvar %s", name);
        return;
    }
    SetConVarInt(my_cvar, value, false, false);
}

// Sets the bots of each side, the same count for the fewest and the most players, so the game's
// own scaling by players doesn't change it; the override makes the game use these counts
public SetBotCounts(int friendly_count, int enemy_count) {
    SetVarValue("doi_bot_count_override", 1);

    SetVarValue("doi_bot_count_default_enemy_min_players", enemy_count);
    SetVarValue("doi_bot_count_default_enemy_max_players", enemy_count);

    SetVarValue("doi_bot_count_default_friendly_min_players", friendly_count);
    SetVarValue("doi_bot_count_default_friendly_max_players", friendly_count);
}

// The enemies: enemy_base and 2 more per player; the friendlies: friendly_base and 1 more per player.
// Each side has the slots of a team (nwi.inc), which the friendlies share with the players.
public SetBots(int playercount, int enemy_base, int friendly_base) {
    int slots = NWI_TeamSlots(NWI_DOI_COOP_TEAM_SLOTS);

    int botcount = enemy_base + playercount * 2;
    if(botcount > slots)
        botcount = slots;

    int friendly_botcount = friendly_base + playercount;
    int friendly_slots = slots - playercount;
    if(friendly_botcount > friendly_slots)
        friendly_botcount = friendly_slots > 0 ? friendly_slots : 0;

    SetBotCounts(friendly_botcount, botcount);
}

// Only the coop modes are scaled: Stronghold and Raid with 3 enemies and 5 friendlies to start
// with, Entrenchment with 6 and 3
public AdjustDifficulty() {
    int playercount = GetPlayerCount();
    char mode[NWI_MODE_LENGTH];
    NWI_GetGameMode(mode, sizeof(mode));

    if(StrEqual(mode, "stronghold") || StrEqual(mode, "raid"))
        SetBots(playercount, 3, 5);
    else if(StrEqual(mode, "entrenchment"))
        SetBots(playercount, 6, 3);
    else
    {
        // Another game mode gets the game's own bot counts back
        if(g_scaled)
            SetVarValue("doi_bot_count_override", 0);
        g_scaled = false;
        return;
    }

    g_scaled = true;
    PrintToServer("Difficulty Scaler: Scaling for %d players", playercount);
}
