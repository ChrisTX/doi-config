// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// Scales the number of bots in the coop modes to the number of human players at the start of each
// round, independently of the map's scripting, in Day of Infamy and Insurgency.
//
// The game modes' configs set the numbers with nwi_mode_cvar (nwi_mode_config.smx), which puts the
// cvars back when the game mode changes, so a game mode without them isn't scaled:
//
//     nwi_scaler_enabled              1 to scale the game mode's bots
//     nwi_scaler_enemy_base           the enemy bots without players
//     nwi_scaler_enemy_per_player     the enemy bots each human player adds
//     nwi_scaler_friendly_base        the friendly bots without players (Day of Infamy)
//     nwi_scaler_friendly_per_player  the friendly bots each human player adds (Day of Infamy)
//
// Each side has at most the slots of a team (nwi.inc), which the friendly bots share with the players.
// Day of Infamy's own scaling between doi_bot_count_default_*_min_players and _max_players is linear
// in the players too, but caps nothing, e.g. 19 enemies at 8 players with 3 + 2 a player, more than a
// team's 16 slots: so the plugin sets both to its count, and doi_bot_count_override, unless it's on
// already, which makes the game use them rather than the map's. In Insurgency it sets the game mode's
// set bot count, ins_bot_count_<mode> (e.g. ins_bot_count_checkpoint), which overrides the game's own
// scaling above 0 and has no friendly bots. It sets them all as nwi_mode_cvar does (NWI_SetModeCvar),
// so they come back when the game mode changes, whether a config set them or not.

#include <sourcemod>
#include <sdktools>
#include <nwi>
#include <nwi_mode_config>

#pragma semicolon 1
#pragma newdecls required

public Plugin myinfo =
{
    name        = "NWI difficulty scaler",
    author      = "DOI revival project",
    description = "Scale the coop modes' bots to the players",
    version     = "3.0",
    url         = "https://rev-crew.info"
};

NWIGame g_game;
ConVar g_enabled;
ConVar g_enemyBase;
ConVar g_enemyPerPlayer;
ConVar g_friendlyBase;
ConVar g_friendlyPerPlayer;

public void OnPluginStart()
{
    g_game = NWI_RequireGame();
    g_enabled = CreateConVar("nwi_scaler_enabled", "0",
        "1 to scale the game mode's bots to the players (set by the game mode's config)", _, true, 0.0,
        true, 1.0);
    g_enemyBase = CreateConVar("nwi_scaler_enemy_base", "0", "The enemy bots without players", _,
        true, 0.0);
    g_enemyPerPlayer = CreateConVar("nwi_scaler_enemy_per_player", "0",
        "The enemy bots each human player adds", _, true, 0.0);
    g_friendlyBase = CreateConVar("nwi_scaler_friendly_base", "0",
        "The friendly bots without players (Day of Infamy)", _, true, 0.0);
    g_friendlyPerPlayer = CreateConVar("nwi_scaler_friendly_per_player", "0",
        "The friendly bots each human player adds (Day of Infamy)", _, true, 0.0);
    // The bot counts are set anew at every round start, which a server without players doesn't have
    HookEvent("round_start", Event_RoundStart, EventHookMode_Post);
    RegServerCmd("nwi_scaler_apply", Command_Apply,
        "Scale the bots to the players now, e.g. after changing the numbers");
}

public Action Command_Apply(int args)
{
    if (g_enabled.BoolValue)
        AdjustDifficulty();
    else
        PrintToServer("Difficulty scaler: the game mode isn't scaled (nwi_scaler_enabled 0)");
    return Plugin_Handled;
}

// The human players in game; bots and players still connecting don't count
int GetPlayerCount()
{
    int players = 0;
    for (int i = 1; i <= MaxClients; i++)
    {
        if (IsClientInGame(i) && !IsFakeClient(i))
            players++;
    }
    return players;
}

public void Event_RoundStart(Event event, const char[] name, bool dontBroadcast)
{
    if (g_enabled.BoolValue)
        AdjustDifficulty();
}

// Sets a cvar until the game mode changes (nwi_mode_config.smx)
void SetVarValue(const char[] name, int value)
{
    char text[16];
    IntToString(value, text, sizeof(text));
    // A cvar a game update removed
    if (!NWI_SetModeCvar(name, text))
        LogError("Can't find the cvar %s", name);
}

// BASE and PER_PLAYER bots a player, at most LIMIT and none fewer than 0
int Scaled(int base, int perPlayer, int players, int limit)
{
    int bots = base + perPlayer * players;
    if (bots > limit)
        bots = limit;
    return bots > 0 ? bots : 0;
}

void AdjustDifficulty()
{
    int players = GetPlayerCount();
    int slots = NWI_TeamSlots(NWI_DOI_COOP_TEAM_SLOTS);
    int enemies = Scaled(g_enemyBase.IntValue, g_enemyPerPlayer.IntValue, players, slots);

    if (g_game == NWIGame_DoI)
    {
        // The friendly bots share their team's slots with the players
        int friendlies = Scaled(g_friendlyBase.IntValue, g_friendlyPerPlayer.IntValue, players,
            slots - players);
        ConVar override = FindConVar("doi_bot_count_override");
        if (override != null && !override.BoolValue)
            SetVarValue("doi_bot_count_override", 1);
        // The same count for the fewest and the most players, so the game's own scaling by players
        // doesn't change it
        SetVarValue("doi_bot_count_default_enemy_min_players", enemies);
        SetVarValue("doi_bot_count_default_enemy_max_players", enemies);
        SetVarValue("doi_bot_count_default_friendly_min_players", friendlies);
        SetVarValue("doi_bot_count_default_friendly_max_players", friendlies);
        PrintToServer("Difficulty scaler: %d enemy and %d friendly bots for %d players", enemies,
            friendlies, players);
    }
    else
    {
        char mode[NWI_MODE_LENGTH];
        NWI_GetGameMode(mode, sizeof(mode));
        char cvar[64];
        Format(cvar, sizeof(cvar), "ins_bot_count_%s", mode);
        SetVarValue(cvar, enemies);
        PrintToServer("Difficulty scaler: %d bots for %d players (%s)", enemies, players, cvar);
    }
}
