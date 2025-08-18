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
    HookEvent("round_start", EventHandler, EventHookMode_Post);
    AddCommandListener(exec, "exec");
}

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

char CurrentGameMode[30];

// We need to identify the game mode if possible.
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

public SetVarValue(const String:name[], int value) {
    Handle my_cvar = FindConVar(name);
    SetConVarInt(my_cvar, value, false, false);
}

public SetBotCounts(int friendly_count, int enemy_count) {
    SetVarValue("doi_bot_count_override", 1);

    SetVarValue("doi_bot_count_default_enemy_min_players", enemy_count);
    SetVarValue("doi_bot_count_default_enemy_max_players", enemy_count);

    SetVarValue("doi_bot_count_default_friendly_min_players", friendly_count);
    SetVarValue("doi_bot_count_default_friendly_max_players", friendly_count);
}

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
