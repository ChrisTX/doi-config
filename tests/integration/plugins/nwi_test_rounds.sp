// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// The integration tests' plugin of the rounds (tests/integration/rounds.py): logs the game's round
// and objective events with the prefix "nwi_test_rounds:", and the players of each team, bots and
// humans, when a round begins. The tests read SourceMod's log of them. Not one of the servers'.

#include <sourcemod>
#include <sdktools>

#pragma semicolon 1
#pragma newdecls required

public Plugin myinfo =
{
    name        = "NWI test rounds",
    author      = "DOI revival project",
    description = "Logs the rounds' events for the integration tests",
    version     = "1.0",
    url         = "https://github.com/ChrisTX/doi-config"
};

static const char g_events[][] = {
    "game_start",
    "game_end",
    "round_start",
    "round_begin",
    "round_end",
    "controlpoint_captured",
    "flag_captured",
};

int g_deaths;
// Whether SDK Tools finds the game rules: SourceMod's gamedata has them of 32-bit Windows and Linux
// only, the Windows test turns it off on 64-bit servers
ConVar g_gameState;

public void OnPluginStart()
{
    for (int i = 0; i < sizeof(g_events); i++)
    {
        if (!HookEventEx(g_events[i], Event_Logged, EventHookMode_PostNoCopy))
            LogError("nwi_test_rounds: no event %s", g_events[i]);
    }
    HookEvent("round_begin", Event_Begin, EventHookMode_PostNoCopy);
    HookEvent("player_death", Event_Death, EventHookMode_PostNoCopy);
    RegServerCmd("nwi_test_rounds_status", Command_Status, "Logs the teams and the deaths so far");
    g_gameState = CreateConVar("nwi_test_rounds_game_state", "1",
        "Whether the game rules' state is there: without, it's logged as -1", _, true, 0.0, true, 1.0);
    RegServerCmd("nwi_test_rounds_state", Command_State, "nwi_test_rounds_state <state>: sets the game rules' state");
}

public void OnMapStart()
{
    char map[64];
    GetCurrentMap(map, sizeof(map));
    LogMessage("nwi_test_rounds: map %s", map);
}

void Event_Logged(Event event, const char[] name, bool dontBroadcast)
{
    LogMessage("nwi_test_rounds: %s", name);
}

void Event_Begin(Event event, const char[] name, bool dontBroadcast)
{
    LogTeams();
}

void Event_Death(Event event, const char[] name, bool dontBroadcast)
{
    g_deaths++;
}

Action Command_Status(int args)
{
    LogTeams();
    return Plugin_Handled;
}

Action Command_State(int args)
{
    if (!g_gameState.BoolValue)
    {
        LogError("nwi_test_rounds: no game rules to set the state of (nwi_test_rounds_game_state 0)");
        return Plugin_Handled;
    }
    int state = GetCmdArgInt(1);
    LogMessage("nwi_test_rounds: setting the game state %d to %d", GameState(), state);
    GameRules_SetProp("m_iGameState", state);
    return Plugin_Handled;
}

// The game rules' state (DT_GameRulesProxy's m_iGameState), -1 without the game rules
int GameState()
{
    return g_gameState.BoolValue ? GameRules_GetProp("m_iGameState") : -1;
}

// The players of the two playing teams (2 and 3): bots and humans
void LogTeams()
{
    int bots[4], humans[4];
    for (int client = 1; client <= MaxClients; client++)
    {
        if (!IsClientInGame(client) || IsClientSourceTV(client))
            continue;
        int team = GetClientTeam(client);
        if (team < 2 || team > 3)
            continue;
        if (IsFakeClient(client))
            bots[team]++;
        else
            humans[team]++;
    }
    LogMessage("nwi_test_rounds: teams 2: %d bots %d humans, 3: %d bots %d humans, %d deaths, game state %d",
        bots[2], humans[2], bots[3], humans[3], g_deaths, GameState());
}
