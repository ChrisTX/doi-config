// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// Scales the number of bots in the coop modes to the number of human players at the start of
// each round, independently of the map's scripting. The game mode comes from the
// server_<gamemode>.cfg the game executes for it, see README.md.

#include <sourcemod>
#include <sdktools>

public Plugin myinfo =
{
    name    = "DOI difficulty scaler",
    author    = "DOI revival project",
    description = "Scale difficulty dynamically",
    version   = "1.1",
    url   = "https://rev-crew.info"
}

public OnPluginStart() {
    // The bot counts are set anew at every round start
    HookEvent("round_start", EventHandler, EventHookMode_Post);
    AddCommandListener(exec, "exec");
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

// The game mode of the last server_<gamemode>.cfg executed, empty until one is
char CurrentGameMode[30];

// We need to identify the game mode if possible. The game executes server_<gamemode>.cfg when
// a game mode starts; its argument string is taken to be quoted, "server_<gamemode>.cfg", so
// "server_" starts at index 1 and the mode at index 8, after the quote and "server_". The
// mode ends at the last dot, which also drops the closing quote.
public Action exec(int client, const char[] command, int arg)
{
    char cfgfilename[MAX_NAME_LENGTH];
    GetCmdArgString(cfgfilename, sizeof(cfgfilename));

    if(StrContains(cfgfilename, ".cfg") < 8 || StrContains(cfgfilename, "server_") != 1)
        return Plugin_Continue;


    Format(CurrentGameMode, sizeof(CurrentGameMode), "%s", cfgfilename[8]);
    int dot = FindCharInString(CurrentGameMode, '.', true);

    if(dot != -1)
        CurrentGameMode[dot] = '\0';

    return Plugin_Continue;
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

// At most 32 bots in all, which fits the 49 slots of basic_coop.cfg with its lobby of 16 players
// and SourceTV, the enemies first: 3 enemies and 2 more per player, 5 friendlies and 1 more per player
public SetBotsForStronghold(int playercount) {
    int botcount = 3 + playercount * 2;
    if(botcount > 32)
        botcount = 32;

    int friendly_botcount = 5 + playercount;
    int botlimit = 32 - botcount;
    if(friendly_botcount > botlimit)
        friendly_botcount = botlimit;

    SetBotCounts(friendly_botcount, botcount);
}

// Like Stronghold, with 6 enemies and 3 friendlies to start with
public SetBotsForEntrenchment(int playercount) {
    int botcount = 6 + playercount * 2;
    if(botcount > 32)
        botcount = 32;

    int friendly_botcount = 3 + playercount;
    int botlimit = 32 - botcount;
    if(friendly_botcount > botlimit)
        friendly_botcount = botlimit;

    SetBotCounts(friendly_botcount, botcount);
}

// Only the coop modes are scaled, raid like Stronghold
public AdjustDifficulty() {

    int playercount = GetPlayerCount();
    bool have_scaled = false;

    if(StrEqual(CurrentGameMode, "stronghold") || StrEqual(CurrentGameMode, "raid"))
    {
        SetBotsForStronghold(playercount);
        have_scaled = true;
    }
    else if(StrEqual(CurrentGameMode, "entrenchment"))
    {
        SetBotsForEntrenchment(playercount);
        have_scaled = true;
    }

    if(have_scaled)
        PrintToServer("Difficulty Scaler: Scaling for %d players", playercount);
}
