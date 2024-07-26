#include <sourcemod>
#include <sdktools>

public Plugin myinfo =
{
  name    = "DoI difficulty scaler",
  author    = "REV-CREW",
  description = "Scale difficulty dynamically",
  version   = "1.0",
  url   = "https://rev-crew.info"
}

public OnPluginStart() {
  HookEvent("player_connect", Event_Connect, EventHookMode_Pre);
  HookEvent("player_disconnect", Event_Connect, EventHookMode_Pre);
  AddCommandListener(exec, "exec");
}

GetPlayerCount()
{
    new players;
    for (new i = 1; i <= MaxClients; i++)
    {
        if (IsClientInGame(i) && !IsFakeClient(i))
            players++;
    }
    return players;
}

public Event_Connect(Handle:event, const String:name[], bool:dontBroadcast) {
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

public AdjustDifficulty() {
  if(!StrEqual(CurrentGameMode, "stronghold"))
  {
        SetVarValue("doi_bot_count_override", 0);
        return;
  }
  SetVarValue("doi_bot_count_override", 1);

  new clientcount = GetPlayerCount();
  new botcount = 4 + clientcount * 2;
  if(botcount > 32)
    botcount = 32;
  SetVarValue("doi_bot_count_default_enemy_max_players", botcount);
  SetVarValue("doi_bot_count_default_enemy_min_players", botcount);
  //SetVarValue("mp_cp_capture_time", 120 + clientcount * 15);
}
